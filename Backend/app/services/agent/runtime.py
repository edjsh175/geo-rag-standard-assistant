"""Main Controller → Tool → Observation loop for GeoRAG Agent mode."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
import json
import logging
from time import monotonic
from typing import Any, AsyncIterator, Callable, Mapping
from uuid import NAMESPACE_URL, uuid4, uuid5

logger = logging.getLogger(__name__)

from app.services.agent.distributed_lock import (
    DistributedSessionLock,
    LocalAsyncioSessionLock,
)
from app.services.agent.answer_generator import GeneratedAnswer
from app.services.agent.conversation_memory import (
    ConversationMemoryPlanner,
    conversation_memory_matches_sources,
    extract_authoritative_memory_facts,
)
from app.services.agent.controller import ControllerOutputError
from app.services.agent.context import ContextEngine
from app.services.agent.contracts import FrozenEvidenceSnapshot, MapAction
from app.services.agent.events import AgentEvent
from app.services.agent.graph import PlanningGraphContext, build_planning_graph
from app.services.agent.orchestration import (
    AnswerPublicationPipeline,
    ContextProjector,
    Publisher,
    ReviewerPipeline,
    ToolExecutionCoordinator,
    TurnLifecycleCoordinator,
)
from app.services.agent.orchestration.compat import supported_kwargs
from app.services.agent.publication import (
    AgentPublicationResult,
    BrowserToolExecutionRequired,
    ClarificationRequired,
    DirectAnswerResult,
    KnowledgeAnswerResult,
    NoSafeAnswer,
    PublishedResult,
    SafeLimitation,
)
from app.services.agent.provider_health import FAIL_CLOSED_PROVIDER_HEALTH
from app.services.agent.session import PendingBrowserExecution
from app.services.agent.region_scope import RegionScopeProjector
from app.services.agent.stage_policy import LLMStagePolicy
from app.services.agent.tool_runtime import (
    RetrievalRequestConstraints,
    ResourceFuse,
    ResourceFuseExceeded,
    ToolObservation,
    ToolRuntime,
)
from app.services.agent.tools import CONTROL_ACTION_NAMES, build_default_tool_registry
from app.services.rag.contracts import RetrievalPort
from app.services.agent.turn_context import TurnExecutionContext

_DEFAULT_LOCAL_SESSION_LOCK = LocalAsyncioSessionLock()


@dataclass(frozen=True, slots=True)
class AgentRunRequest:
    question: str
    session_id: str
    principal_id: str
    reviewer_enabled: bool = False
    thinking: bool = False
    max_steps: int = 12
    max_elapsed_seconds: float = 60.0
    request_context: Mapping[str, Any] = field(default_factory=dict)
    continuation_token: str | None = None
    browser_tool_receipt: Mapping[str, Any] | None = None
    legacy_history: tuple[Mapping[str, str], ...] = ()
    retrieval_constraints: RetrievalRequestConstraints = field(
        default_factory=RetrievalRequestConstraints
    )


@dataclass(frozen=True, slots=True, init=False)
class AgentRunResult:
    session_id: str
    turn_id: str
    trace_id: str
    result: AgentPublicationResult
    frozen_evidence: FrozenEvidenceSnapshot | None
    review: Any | None
    events: tuple[AgentEvent, ...]
    remaining_steps: int | None = None
    remaining_seconds: float | None = None

    def __init__(
        self,
        *,
        session_id: str,
        turn_id: str,
        trace_id: str,
        result: AgentPublicationResult | None = None,
        frozen_evidence: FrozenEvidenceSnapshot | None,
        review: Any | None,
        events: tuple[AgentEvent, ...],
        remaining_steps: int | None = None,
        remaining_seconds: float | None = None,
        # Compatibility-only constructor surface. These values are converted
        # immediately and are never stored as a second publication authority.
        publication_state: str | None = None,
        answer: GeneratedAnswer | MapAction | str | None = None,
        clarification: str | None = None,
        limitation: str | None = None,
        pending_tool_call_id: str | None = None,
        continuation_token: str | None = None,
    ) -> None:
        if result is not None and any(
            value is not None
            for value in (
                publication_state,
                answer,
                clarification,
                limitation,
                pending_tool_call_id,
                continuation_token,
            )
        ):
            raise ValueError("AgentRunResult accepts either result or legacy publication fields, not both")
        effective_result = result or self._result_from_legacy(
            publication_state=publication_state,
            answer=answer,
            clarification=clarification,
            limitation=limitation,
            pending_tool_call_id=pending_tool_call_id,
            continuation_token=continuation_token,
        )
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "turn_id", turn_id)
        object.__setattr__(self, "trace_id", trace_id)
        object.__setattr__(self, "result", effective_result)
        object.__setattr__(self, "frozen_evidence", frozen_evidence)
        object.__setattr__(self, "review", review)
        object.__setattr__(self, "events", events)
        object.__setattr__(self, "remaining_steps", remaining_steps)
        object.__setattr__(self, "remaining_seconds", remaining_seconds)

    @staticmethod
    def _result_from_legacy(
        *,
        publication_state: str | None,
        answer: GeneratedAnswer | MapAction | str | None,
        clarification: str | None,
        limitation: str | None,
        pending_tool_call_id: str | None,
        continuation_token: str | None,
    ) -> AgentPublicationResult:
        state = str(publication_state or "").strip()
        if not state:
            raise ValueError("AgentRunResult requires a typed result or publication_state")
        if state == "tool_execution_required":
            if not isinstance(answer, MapAction):
                raise ValueError("tool_execution_required requires MapAction")
            if not pending_tool_call_id or not continuation_token:
                raise ValueError("tool_execution_required requires tool_call_id and continuation_token")
            return BrowserToolExecutionRequired(
                tool_call_id=pending_tool_call_id,
                tool_name=answer.type,
                continuation_token=continuation_token,
                map_action=answer,
            )
        if state in {"clarification", "clarification_required"}:
            if not str(clarification or "").strip():
                raise ValueError("clarification result requires clarification text")
            return ClarificationRequired(question=str(clarification).strip())
        if state == "limitation":
            if not str(limitation or "").strip():
                raise ValueError("limitation result requires limitation text")
            return SafeLimitation(message=str(limitation).strip())
        if state in {"published", "grounded"}:
            if isinstance(answer, GeneratedAnswer):
                if answer.kind == "direct_answer":
                    return DirectAnswerResult(answer=answer)
                if answer.kind == "direct":
                    return DirectAnswerResult(
                        answer=GeneratedAnswer(
                            kind="direct_answer",
                            answer=answer.answer,
                            citations=(),
                            units=(),
                        )
                    )
                if answer.kind == "knowledge_answer":
                    return KnowledgeAnswerResult(answer=answer)
                raise ValueError(f"unsupported published answer kind: {answer.kind}")
            if isinstance(answer, str) and answer.strip():
                return DirectAnswerResult(
                    answer=GeneratedAnswer(
                        kind="direct_answer",
                        answer=answer.strip(),
                        citations=(),
                        units=(),
                    )
                )
            raise ValueError("published result requires an answer")
        return NoSafeAnswer(
            reason=state,
            message=str(limitation or "答案未通过发布契约，未发布。").strip(),
        )

    @property
    def publication_state(self) -> str:
        if isinstance(self.result, (DirectAnswerResult, KnowledgeAnswerResult)):
            return "published"
        if isinstance(self.result, ClarificationRequired):
            return "clarification"
        if isinstance(self.result, BrowserToolExecutionRequired):
            return "tool_execution_required"
        if isinstance(self.result, SafeLimitation):
            return "limitation"
        return self.result.reason

    @property
    def answer(self) -> GeneratedAnswer | MapAction | None:
        if isinstance(self.result, (DirectAnswerResult, KnowledgeAnswerResult)):
            return self.result.answer
        if isinstance(self.result, BrowserToolExecutionRequired):
            return self.result.map_action
        return None

    @property
    def clarification(self) -> str | None:
        return self.result.question if isinstance(self.result, ClarificationRequired) else None

    @property
    def limitation(self) -> str | None:
        if isinstance(self.result, SafeLimitation):
            return self.result.message
        if isinstance(self.result, NoSafeAnswer):
            return self.result.message
        return None

    @property
    def pending_tool_call_id(self) -> str | None:
        return self.result.tool_call_id if isinstance(self.result, BrowserToolExecutionRequired) else None

    @property
    def continuation_token(self) -> str | None:
        return self.result.continuation_token if isinstance(self.result, BrowserToolExecutionRequired) else None

    def to_typed_result(
        self,
    ) -> AgentPublicationResult:
        return self.result

    @property
    def typed_result(
        self,
    ) -> AgentPublicationResult:
        return self.result

    @property
    def published_result(self) -> PublishedResult:
        if isinstance(self.result, BrowserToolExecutionRequired):
            return PublishedResult.continuation(
                publication_state="tool_execution_required",
                map_action=self.result.map_action,
                pending_tool_call_id=self.result.tool_call_id,
                continuation_token=self.result.continuation_token,
            )
        if isinstance(self.result, (DirectAnswerResult, KnowledgeAnswerResult)):
            return PublishedResult.publish(
                text=self.result.text,
                publication_state="published",
                map_action=None,
            )
        if isinstance(self.result, ClarificationRequired):
            return PublishedResult.publish(
                text=self.result.question,
                publication_state="clarification_required",
                map_action=None,
            )
        if isinstance(self.result, SafeLimitation):
            return PublishedResult.publish(
                text=self.result.message,
                publication_state="limitation",
                map_action=None,
            )
        return PublishedResult.safe_fallback(
            publication_state=self.result.reason,
            fallback_text=self.result.message,
        )


@dataclass(frozen=True, slots=True)
class AgentStreamFrame:
    event: AgentEvent | None = None
    result: AgentRunResult | None = None


class AgentRuntime:
    def __init__(
        self,
        *,
        retrieval_port: RetrievalPort,
        controller,
        answer_generator,
        session_store: Any,
        reviewer=None,
        context_engine: ContextEngine | None = None,
        conversation_memory_summarizer=None,
        spatial_service=None,
        provider_health_provider=None,
        session_lock: DistributedSessionLock | None = None,
    ) -> None:
        self.retrieval_port = retrieval_port
        self.controller = controller
        self.answer_generator = answer_generator
        self.reviewer = reviewer
        self.session_store = session_store
        self.session_lock = (
            session_lock if session_lock is not None else _DEFAULT_LOCAL_SESSION_LOCK
        )
        self.context_engine = context_engine or ContextEngine()
        self.conversation_memory_summarizer = conversation_memory_summarizer
        self.spatial_service = spatial_service
        self.provider_health_provider = provider_health_provider
        self.turn_lifecycle = TurnLifecycleCoordinator(session_store)
        self.context_projector = ContextProjector(self.context_engine)
        self.reviewer_pipeline = ReviewerPipeline(
            reviewer=reviewer,
            answer_generator=answer_generator,
            context_engine=self.context_engine,
        )
        self.publisher = Publisher(session_store)
        self.answer_publication_pipeline = AnswerPublicationPipeline(
            answer_generator=answer_generator,
            reviewer_pipeline=self.reviewer_pipeline,
            context_engine=self.context_engine,
        )
        model_client = getattr(controller, "model_client", None)
        self.endpoint_supports_reasoning = bool(
            getattr(model_client, "supports_reasoning", False)
        )

    async def request_cancellation(
        self,
        *,
        principal_id: str,
        session_id: str,
        turn_id: str,
        reason: str = "user_requested",
    ) -> AgentEvent:
        events = await self._list_runtime_events(principal_id, session_id)
        turn_events = [event for event in events if event.turn_id == turn_id]
        if not turn_events:
            raise ValueError("unknown agent turn")
        existing_request = next(
            (event for event in turn_events if event.event_type == "run_cancel_requested"),
            None,
        )
        if any(event.event_type == "publication_completed" for event in turn_events):
            raise ValueError("agent turn is already terminal")
        if any(event.event_type == "run_cancelled" for event in turn_events):
            if existing_request is not None:
                return existing_request
            raise ValueError("agent turn is already terminal")
        trace_id = next(
            (event.trace_id for event in reversed(turn_events) if event.trace_id),
            "",
        )
        event = AgentEvent(
            event_type="run_cancel_requested",
            session_id=session_id,
            turn_id=turn_id,
            trace_id=trace_id,
            payload={"reason": reason or "user_requested"},
            event_id=self._cancellation_event_id(
                principal_id,
                session_id,
                turn_id,
                "run_cancel_requested",
            ),
        )
        persisted = await self._persist_event(principal_id, event)

        pending = None
        if hasattr(self.session_store, "get_pending_execution"):
            pending = await self.session_store.get_pending_execution(
                principal_id,
                session_id,
            )
        if pending is not None and pending.turn_id == turn_id:
            if hasattr(self.session_store, "clear_pending_execution"):
                await self.session_store.clear_pending_execution(principal_id, session_id)
            await self._persist_event(
                principal_id,
                AgentEvent(
                    event_type="run_cancelled",
                    session_id=session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    payload={"reason": reason or "user_requested"},
                    event_id=self._cancellation_event_id(
                        principal_id,
                        session_id,
                        turn_id,
                        "run_cancelled",
                    ),
                ),
            )
        return persisted

    async def run(
        self,
        request: AgentRunRequest,
        *,
        event_listener: Callable[[AgentEvent], None] | None = None,
    ) -> AgentRunResult:
        async with self.session_lock.lock(request.principal_id, request.session_id):
            ctx = await self._prepare_turn_context(request, event_listener)
            await self._maybe_update_conversation_memory(ctx)
            return await self._execute_planning_graph(ctx)

    async def _prepare_turn_context(
        self,
        request: AgentRunRequest,
        event_listener: Callable[[AgentEvent], None] | None = None,
    ) -> TurnExecutionContext:
        turn_events: list[AgentEvent] = []

        async def persist_turn_event(event: AgentEvent) -> AgentEvent:
            persisted = await self._persist_event(request.principal_id, event)
            turn_events.append(persisted)
            if event_listener is not None:
                event_listener(persisted)
            return persisted

        async def persist_session_event(event: AgentEvent) -> AgentEvent:
            return await self._persist_event(request.principal_id, event)

        async def persist_lifecycle_evidence(lifecycle_session) -> None:
            await self._persist_evidence_state(request.principal_id, lifecycle_session)

        model_client = getattr(self.controller, "model_client", None)
        resolve_main_model = getattr(model_client, "resolve_main_model", None)
        prepared = await self.turn_lifecycle.prepare(
            request=request,
            append_turn_event=persist_turn_event,
            append_session_event=persist_session_event,
            persist_evidence=persist_lifecycle_evidence,
            resolve_main_model=(
                (lambda thinking: resolve_main_model(thinking=thinking))
                if callable(resolve_main_model)
                else (lambda _thinking: None)
            ),
        )

        provider_health: Mapping[str, bool] = {}
        if self.provider_health_provider is not None:
            try:
                provider_health_snapshot = await self.provider_health_provider.snapshot()
                provider_health = dict(provider_health_snapshot.provider_health)
            except Exception:
                provider_health = dict(FAIL_CLOSED_PROVIDER_HEALTH)

        fuse = ResourceFuse(
            max_steps=prepared.max_steps,
            max_elapsed_seconds=prepared.max_elapsed_seconds,
            initial_steps=prepared.initial_steps,
        )
        registry = getattr(self.controller, "tool_registry", None) or build_default_tool_registry()
        tool_runtime = ToolRuntime(
            retrieval_port=self.retrieval_port,
            evidence_ledger=prepared.session.evidence_ledger,
            registry=registry,
            resource_fuse=fuse,
            retrieval_constraints=prepared.retrieval_constraints,
            standard_scope=RegionScopeProjector.from_request_context(prepared.request_context),
            spatial_service=self.spatial_service,
        )
        tool_execution = ToolExecutionCoordinator(tool_runtime)
        stage_policy = LLMStagePolicy(
            user_thinking=prepared.thinking,
            endpoint_supports_reasoning=self.endpoint_supports_reasoning,
            runtime_deadline_at=fuse.deadline_at,
        )

        return TurnExecutionContext(
            runtime=self,
            request=request,
            session=prepared.session,
            turn_id=prepared.turn_id,
            trace_id=prepared.trace_id,
            question=prepared.question,
            effective_request_context=prepared.request_context,
            reviewer_enabled=prepared.reviewer_enabled,
            thinking=prepared.thinking,
            retrieval_constraints=prepared.retrieval_constraints,
            max_steps=prepared.max_steps,
            max_elapsed_seconds=prepared.max_elapsed_seconds,
            initial_steps=prepared.initial_steps,
            main_model_name=prepared.main_model_name,
            fuse=fuse,
            registry=registry,
            tool_execution=tool_execution,
            stage_policy=stage_policy,
            provider_health=provider_health,
            turn_events=turn_events,
            observations=list(prepared.observations),
            event_listener=event_listener,
        )

    async def _maybe_update_conversation_memory(self, ctx: TurnExecutionContext) -> None:
        session = ctx.session
        request = ctx.request
        durable_events_for_memory: list[AgentEvent] | None = None
        if session.conversation_memory is not None:
            durable_events_for_memory = await self._list_runtime_events(
                request.principal_id,
                session.session_id,
            )
            if not conversation_memory_matches_sources(
                session.conversation_memory,
                durable_events_for_memory,
            ):
                invalid_memory = session.conversation_memory
                session.conversation_memory = None
                await ctx.append_event(
                    AgentEvent(
                        event_type="conversation_memory_invalidated",
                        session_id=session.session_id,
                        turn_id=ctx.turn_id,
                        trace_id=ctx.trace_id,
                        payload={
                            "memory_id": invalid_memory.memory_id,
                            "summary_version": invalid_memory.summary_version,
                            "reason": "source_mismatch",
                        },
                    )
                )

        if (
            request.continuation_token is None
            and self.conversation_memory_summarizer is not None
        ):
            durable_events = (
                durable_events_for_memory
                if durable_events_for_memory is not None
                else await self._list_runtime_events(
                    request.principal_id,
                    session.session_id,
                )
            )
            planner = ConversationMemoryPlanner(
                estimator=self.context_engine.budget_manager.estimator,
                controller_context_tokens=(
                    self.context_engine.budget_manager.config.controller.available_context_tokens
                ),
            )
            plan = planner.plan(
                events=durable_events,
                current_turn_id=ctx.turn_id,
                previous=session.conversation_memory,
            )
            if plan.should_summarize:
                authoritative_facts = extract_authoritative_memory_facts(
                    plan.all_source_events
                )
                memory_budget_seconds = min(
                    5.0,
                    max(0.25, ctx.max_elapsed_seconds * 0.10),
                )
                memory_stage_policy = LLMStagePolicy(
                    user_thinking=False,
                    endpoint_supports_reasoning=self.endpoint_supports_reasoning,
                    runtime_deadline_at=min(
                        ctx.fuse.deadline_at,
                        monotonic() + memory_budget_seconds,
                    ),
                )
                try:
                    memory_record = await self.conversation_memory_summarizer.summarize(
                        principal_id=request.principal_id,
                        session_id=session.session_id,
                        turn_id=ctx.turn_id,
                        events_to_summarize=plan.events_to_summarize,
                        all_source_events=plan.all_source_events,
                        previous=session.conversation_memory,
                        authoritative_facts=authoritative_facts,
                        stage_policy=memory_stage_policy,
                        model_name=ctx.main_model_name,
                    )
                except Exception as exc:
                    await ctx.append_event(
                        AgentEvent(
                            event_type="conversation_memory_failed",
                            session_id=session.session_id,
                            turn_id=ctx.turn_id,
                            trace_id=ctx.trace_id,
                            payload={
                                "phase": "generate",
                                "error_type": type(exc).__name__,
                            },
                        )
                    )
                else:
                    try:
                        if hasattr(self.session_store, "save_conversation_memory"):
                            await self.session_store.save_conversation_memory(memory_record)
                    except Exception as exc:
                        latest_memory = None
                        if hasattr(self.session_store, "get_latest_conversation_memory"):
                            try:
                                latest_memory = await self.session_store.get_latest_conversation_memory(
                                    request.principal_id,
                                    session.session_id,
                                )
                            except Exception:
                                latest_memory = None
                        if latest_memory is not None:
                            session.conversation_memory = latest_memory
                        await ctx.append_event(
                            AgentEvent(
                                event_type="conversation_memory_failed",
                                session_id=session.session_id,
                                turn_id=ctx.turn_id,
                                trace_id=ctx.trace_id,
                                payload={
                                    "phase": "persist",
                                    "error_type": type(exc).__name__,
                                },
                            )
                        )
                    else:
                        session.conversation_memory = memory_record
                        await ctx.append_event(
                            AgentEvent(
                                event_type="conversation_memory_updated",
                                session_id=session.session_id,
                                turn_id=ctx.turn_id,
                                trace_id=ctx.trace_id,
                                payload={
                                    "memory_id": memory_record.memory_id,
                                    "summary_version": memory_record.summary_version,
                                    "covered_from_sequence": memory_record.covered_from_sequence,
                                    "covered_to_sequence": memory_record.covered_to_sequence,
                                    "source_hash": memory_record.source_hash,
                                },
                            )
                        )

    async def _execute_planning_graph(self, ctx: TurnExecutionContext) -> AgentRunResult:
        planning_graph = build_planning_graph()
        planning_context = PlanningGraphContext(
            project_context=ctx.project_context,
            decide=ctx.decide,
            execute_tool=ctx.execute_tool,
            should_continue=ctx.should_continue,
            after_tool=ctx.after_tool,
            handle_control=ctx.handle_control,
            finalize_terminal=ctx.finalize_terminal,
        )
        try:
            planning_state = await planning_graph.ainvoke(
                {
                    "principal_id": ctx.request.principal_id,
                    "session_id": ctx.session.session_id,
                    "turn_id": ctx.turn_id,
                    "trace_id": ctx.trace_id,
                    "question": ctx.question,
                },
                context=planning_context,
            )
        except TimeoutError:
            return await ctx.build_resource_fuse_result()
        except ControllerOutputError as exc:
            return await ctx.build_model_output_failure_result(failure_stage="controller", error=str(exc))

        if planning_context.terminal_result is not None:
            return planning_context.terminal_result
        raise RuntimeError(
            f"LangGraph terminal was not finalized: {planning_state.get('publication_kind')!r}"
        )

    async def stream(self, request: AgentRunRequest) -> AsyncIterator[AgentStreamFrame]:
        """Project observable events from the exact same ``run`` execution path."""

        queue: asyncio.Queue[AgentEvent | object] = asyncio.Queue()
        sentinel = object()
        result_holder: list[AgentRunResult] = []
        observed_turn_id: str | None = None
        observed_trace_id = ""

        async def execute() -> None:
            try:
                result = await self.run(
                    request,
                    event_listener=queue.put_nowait,
                )
                result_holder.append(result)
            finally:
                queue.put_nowait(sentinel)

        task = asyncio.create_task(execute())
        try:
            while True:
                item = await queue.get()
                if item is sentinel:
                    break
                if isinstance(item, AgentEvent):
                    observed_turn_id = item.turn_id
                    observed_trace_id = item.trace_id
                yield AgentStreamFrame(event=item)  # type: ignore[arg-type]

            await task
            yield AgentStreamFrame(result=result_holder[0])
        finally:
            if not task.done():
                cancellation_accepted = False
                if observed_turn_id:
                    try:
                        await self.request_cancellation(
                            principal_id=request.principal_id,
                            session_id=request.session_id,
                            turn_id=observed_turn_id,
                            reason="stream_closed",
                        )
                        cancellation_accepted = True
                    except ValueError:
                        cancellation_accepted = False
                if cancellation_accepted or observed_turn_id is None:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                if cancellation_accepted and observed_turn_id:
                    await self._persist_event(
                        request.principal_id,
                        AgentEvent(
                            event_type="run_cancelled",
                            session_id=request.session_id,
                            turn_id=observed_turn_id,
                            trace_id=observed_trace_id,
                            payload={"reason": "stream_closed"},
                            event_id=self._cancellation_event_id(
                                request.principal_id,
                                request.session_id,
                                observed_turn_id,
                                "run_cancelled",
                            ),
                        ),
                    )

    @staticmethod
    def _validate_decision_against_action_state(call: Any, action_state: Any) -> None:
        """Fail closed if a Controller result escapes the request-scoped action surface."""
        action = str(getattr(call, "action", "") or "").strip()

        if action == "tool_call":
            name = str(getattr(call, "tool", "") or "").strip()
            if name not in action_state.available_capabilities:
                raise ControllerOutputError(
                    f"controller selected unavailable tool '{name}'"
                )
            return

        name = str(getattr(call, "name", "") or "").strip()
        control_name = action if action in CONTROL_ACTION_NAMES else name
        if control_name in CONTROL_ACTION_NAMES:
            if control_name not in action_state.available_control_actions:
                raise ControllerOutputError(
                    f"controller selected unavailable control action '{control_name}'"
                )
            if control_name == "compose_answer":
                raw_arguments = getattr(call, "arguments", {}) or {}
                selected_ids = (
                    raw_arguments.get("selected_evidence_ids")
                    or []
                ) if isinstance(raw_arguments, Mapping) else []
                for evidence_id in selected_ids:
                    normalized_id = str(evidence_id).strip()
                    if normalized_id not in action_state.selectable_evidence_ids:
                        raise ControllerOutputError(
                            f"controller selected unavailable evidence '{normalized_id}'"
                        )
            return

        if name not in action_state.available_capabilities:
            raise ControllerOutputError(
                f"controller selected unavailable tool '{name}'"
            )

    async def _append_event(
        self,
        principal_id: str,
        session_events: list[AgentEvent],
        turn_events: list[AgentEvent],
        event: AgentEvent,
        event_listener: Callable[[AgentEvent], None] | None = None,
    ) -> AgentEvent:
        persisted_event = await self._persist_event(principal_id, event)
        session_events.append(persisted_event)
        turn_events.append(persisted_event)
        if event_listener is not None:
            event_listener(persisted_event)
        return persisted_event

    async def _save_snapshot_audited(
        self,
        *,
        snapshot: Any,
        session: AgentSession,
        request: AgentRunRequest,
        stage: str,
        session_events: list[AgentEvent] | None = None,
        turn_events: list[AgentEvent] | None = None,
        event_listener: Callable[[AgentEvent], None] | None = None,
    ) -> None:
        if not hasattr(self.session_store, "save_snapshot"):
            return
        try:
            await self.session_store.save_snapshot(snapshot.to_record(request.principal_id))
        except Exception as exc:
            logger.warning(
                "Context snapshot persist failed for %s (session=%s): %s",
                stage,
                session.session_id,
                exc,
            )
            if getattr(self, "strict_audit", False):
                raise
            session.audit_degraded = True
            fail_event = AgentEvent(
                event_type="context_snapshot_persist_failed",
                session_id=session.session_id,
                turn_id=session.active_turn_id if hasattr(session, "active_turn_id") and session.active_turn_id else (session.events[-1].turn_id if session.events else "current"),
                event_id=f"evt-{uuid4().hex[:12]}",
                payload={
                    "stage": stage,
                    "snapshot_id": getattr(snapshot, "snapshot_id", ""),
                    "error": str(exc),
                    "audit_degraded": True,
                },
            )
            if session_events is not None and turn_events is not None:
                await self._append_event(
                    principal_id=request.principal_id,
                    session_events=session_events,
                    turn_events=turn_events,
                    event=fail_event,
                    event_listener=event_listener,
                )
            else:
                await self._persist_event(request.principal_id, fail_event)

    async def _persist_event(
        self,
        principal_id: str,
        event: AgentEvent,
    ) -> AgentEvent:
        if hasattr(self.session_store, "append_event"):
            return await self.session_store.append_event(principal_id, event)
        return event

    async def _list_runtime_events(
        self,
        principal_id: str,
        session_id: str,
    ) -> list[AgentEvent]:
        if hasattr(self.session_store, "list_events"):
            return list(await self.session_store.list_events(principal_id, session_id))
        session = self.session_store.get(principal_id, session_id)
        return list(session.events) if session is not None else []

    async def _is_cancellation_requested(
        self,
        principal_id: str,
        session_id: str,
        turn_id: str,
    ) -> bool:
        events = await self._list_runtime_events(principal_id, session_id)
        requested_sequence = max(
            (
                event.sequence
                for event in events
                if event.turn_id == turn_id and event.event_type == "run_cancel_requested"
            ),
            default=0,
        )
        cancelled_sequence = max(
            (
                event.sequence
                for event in events
                if event.turn_id == turn_id and event.event_type == "run_cancelled"
            ),
            default=0,
        )
        return requested_sequence > cancelled_sequence

    @staticmethod
    def _cancellation_event_id(
        principal_id: str,
        session_id: str,
        turn_id: str,
        event_type: str,
    ) -> str:
        identity = "|".join((principal_id, session_id, turn_id, event_type))
        return uuid5(NAMESPACE_URL, identity).hex

    async def _persist_evidence_state(
        self,
        principal_id: str,
        session: AgentSession,
    ) -> None:
        if hasattr(self.session_store, "save_evidence_items"):
            await self.session_store.save_evidence_items(
                principal_id,
                session.session_id,
                session.evidence_ledger.export_items(),
            )
        if hasattr(self.session_store, "save_evidence_activations"):
            await self.session_store.save_evidence_activations(
                principal_id,
                session.session_id,
                session.evidence_ledger.export_working_by_turn(),
            )
