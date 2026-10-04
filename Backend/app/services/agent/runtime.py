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
    ) -> None:
        self.retrieval_port = retrieval_port
        self.controller = controller
        self.answer_generator = answer_generator
        self.reviewer = reviewer
        self.session_store = session_store
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
        session = prepared.session
        question = prepared.question
        turn_id = prepared.turn_id
        trace_id = prepared.trace_id
        effective_request_context = prepared.request_context
        reviewer_enabled = prepared.reviewer_enabled
        thinking = prepared.thinking
        retrieval_constraints = prepared.retrieval_constraints
        max_steps = prepared.max_steps
        max_elapsed_seconds = prepared.max_elapsed_seconds
        initial_steps = prepared.initial_steps
        main_model_name = prepared.main_model_name
        observations = list(prepared.observations)

        async def resource_fuse_result() -> AgentRunResult:
            limitation = "Agent 运行达到资源保护上限，未发布答案。"
            await self.publisher.publish(
                principal_id=request.principal_id,
                session=session,
                turn_events=turn_events,
                turn_id=turn_id,
                trace_id=trace_id,
                publication_state="resource_fuse",
                text=limitation,
                event_listener=event_listener,
            )
            return AgentRunResult(
                session_id=session.session_id,
                turn_id=turn_id,
                trace_id=trace_id,
                result=NoSafeAnswer(reason="resource_fuse", message=limitation),
                frozen_evidence=None,
                review=None,
                events=tuple(turn_events),
            )

        async def model_output_failure_result(
            *,
            failure_stage: str,
            error: str,
        ) -> AgentRunResult:
            limitation = "模型输出未满足 Agent 结构化协议，未发布答案。"
            await self.publisher.publish(
                principal_id=request.principal_id,
                session=session,
                turn_events=turn_events,
                turn_id=turn_id,
                trace_id=trace_id,
                publication_state="model_output_invalid",
                text=limitation,
                payload={"failure_stage": failure_stage, "error": error},
                event_listener=event_listener,
            )
            return AgentRunResult(
                session_id=session.session_id,
                turn_id=turn_id,
                trace_id=trace_id,
                result=NoSafeAnswer(reason="model_output_invalid", message=limitation),
                frozen_evidence=None,
                review=None,
                events=tuple(turn_events),
            )

        async def retrieval_unavailable_result() -> AgentRunResult:
            limitation = "知识检索服务当前不可用，未发布答案。"
            await self.publisher.publish(
                principal_id=request.principal_id,
                session=session,
                turn_events=turn_events,
                turn_id=turn_id,
                trace_id=trace_id,
                publication_state="retrieval_unavailable",
                text=limitation,
                event_listener=event_listener,
            )
            return AgentRunResult(
                session_id=session.session_id,
                turn_id=turn_id,
                trace_id=trace_id,
                result=NoSafeAnswer(reason="retrieval_unavailable", message=limitation),
                frozen_evidence=None,
                review=None,
                events=tuple(turn_events),
            )

        async def cancelled_result(reason: str = "cancel_requested") -> AgentRunResult:
            limitation = "Agent 运行已取消。"
            event = AgentEvent(
                event_type="run_cancelled",
                session_id=session.session_id,
                turn_id=turn_id,
                trace_id=trace_id,
                payload={"reason": reason},
                event_id=self._cancellation_event_id(
                    request.principal_id,
                    session.session_id,
                    turn_id,
                    "run_cancelled",
                ),
            )
            await self._append_event(
                request.principal_id,
                session.events,
                turn_events,
                event,
                event_listener,
            )
            return AgentRunResult(
                session_id=session.session_id,
                turn_id=turn_id,
                trace_id=trace_id,
                result=NoSafeAnswer(reason="cancelled", message=limitation),
                frozen_evidence=None,
                review=None,
                events=tuple(turn_events),
            )

        provider_health: Mapping[str, bool] = {}
        if self.provider_health_provider is not None:
            try:
                provider_health_snapshot = await self.provider_health_provider.snapshot()
                provider_health = dict(provider_health_snapshot.provider_health)
            except Exception:
                provider_health = dict(FAIL_CLOSED_PROVIDER_HEALTH)

        fuse = ResourceFuse(
            max_steps=max_steps,
            max_elapsed_seconds=max_elapsed_seconds,
            initial_steps=initial_steps,
        )
        registry = getattr(self.controller, "tool_registry", None) or build_default_tool_registry()
        tool_runtime = ToolRuntime(
            retrieval_port=self.retrieval_port,
            evidence_ledger=session.evidence_ledger,
            registry=registry,
            resource_fuse=fuse,
            retrieval_constraints=retrieval_constraints,
            standard_scope=RegionScopeProjector.from_request_context(effective_request_context),
            spatial_service=self.spatial_service,
        )
        tool_execution = ToolExecutionCoordinator(tool_runtime)
        stage_policy = LLMStagePolicy(
            user_thinking=thinking,
            endpoint_supports_reasoning=self.endpoint_supports_reasoning,
            runtime_deadline_at=fuse.deadline_at,
        )
        planning_graph = build_planning_graph()

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
                await self._append_event(
                    request.principal_id,
                    session.events,
                    turn_events,
                    AgentEvent(
                        event_type="conversation_memory_invalidated",
                        session_id=session.session_id,
                        turn_id=turn_id,
                        trace_id=trace_id,
                        payload={
                            "memory_id": invalid_memory.memory_id,
                            "summary_version": invalid_memory.summary_version,
                            "reason": "source_mismatch",
                        },
                    ),
                    event_listener,
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
                current_turn_id=turn_id,
                previous=session.conversation_memory,
            )
            if plan.should_summarize:
                authoritative_facts = extract_authoritative_memory_facts(
                    plan.all_source_events
                )
                memory_budget_seconds = min(
                    5.0,
                    max(0.25, max_elapsed_seconds * 0.10),
                )
                memory_stage_policy = LLMStagePolicy(
                    user_thinking=False,
                    endpoint_supports_reasoning=self.endpoint_supports_reasoning,
                    runtime_deadline_at=min(
                        fuse.deadline_at,
                        monotonic() + memory_budget_seconds,
                    ),
                )
                try:
                    memory_record = await self.conversation_memory_summarizer.summarize(
                        principal_id=request.principal_id,
                        session_id=session.session_id,
                        turn_id=turn_id,
                        events_to_summarize=plan.events_to_summarize,
                        all_source_events=plan.all_source_events,
                        previous=session.conversation_memory,
                        authoritative_facts=authoritative_facts,
                        stage_policy=memory_stage_policy,
                        model_name=main_model_name,
                    )
                except Exception as exc:
                    await self._append_event(
                        request.principal_id,
                        session.events,
                        turn_events,
                        AgentEvent(
                            event_type="conversation_memory_failed",
                            session_id=session.session_id,
                            turn_id=turn_id,
                            trace_id=trace_id,
                            payload={
                                "phase": "generate",
                                "error_type": type(exc).__name__,
                            },
                        ),
                        event_listener,
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
                        await self._append_event(
                            request.principal_id,
                            session.events,
                            turn_events,
                            AgentEvent(
                                event_type="conversation_memory_failed",
                                session_id=session.session_id,
                                turn_id=turn_id,
                                trace_id=trace_id,
                                payload={
                                    "phase": "persist",
                                    "error_type": type(exc).__name__,
                                },
                            ),
                            event_listener,
                        )
                    else:
                        session.conversation_memory = memory_record
                        await self._append_event(
                            request.principal_id,
                            session.events,
                            turn_events,
                            AgentEvent(
                                event_type="conversation_memory_updated",
                                session_id=session.session_id,
                                turn_id=turn_id,
                                trace_id=trace_id,
                                payload={
                                    "memory_id": memory_record.memory_id,
                                    "summary_version": memory_record.summary_version,
                                    "covered_from_sequence": memory_record.covered_from_sequence,
                                    "covered_to_sequence": memory_record.covered_to_sequence,
                                    "source_hash": memory_record.source_hash,
                                },
                            ),
                            event_listener,
                        )

        async def planning_project_context():
            turn_projection = self.context_projector.project_controller(
                session=session,
                principal_id=request.principal_id,
                turn_id=turn_id,
                question=question,
                request_context=effective_request_context,
                registry=registry,
                provider_health=provider_health,
                reviewer_enabled=reviewer_enabled,
            )
            await self._save_snapshot_audited(
                snapshot=turn_projection.controller_snapshot,
                session=session,
                request=request,
                stage="controller",
                session_events=session.events,
                turn_events=turn_events,
                event_listener=event_listener,
            )
            return turn_projection

        async def planning_decide(turn_projection):
                proj = turn_projection.controller_projection
                state = turn_projection.action_state
                controller_kwargs = dict(
                    projection=proj,
                    action_state=state,
                    observations=tuple(observations),
                    stage_policy=stage_policy,
                    audit_context={
                        "principal_id": request.principal_id,
                        "session_id": session.session_id,
                        "turn_id": turn_id,
                        "trace_id": trace_id,
                        "context_snapshot_id": turn_projection.controller_snapshot.snapshot_id,
                    },
                    question=proj.user_question,
                    context_summary=proj.conversation_text,
                    working_evidence=proj.working_evidence,
                    available_tool_names=state.available_capabilities,
                    available_control_actions=state.available_control_actions,
                )
                if main_model_name is not None:
                    controller_kwargs["model_name"] = main_model_name
                decision = await self.controller.decide(
                    **supported_kwargs(self.controller.decide, controller_kwargs)
                )
                self._validate_decision_against_action_state(decision, state)
                return decision

        async def planning_execute_tool(decision):
            outcome = await tool_execution.execute(
                turn_id=turn_id, session_id=session.session_id, trace_id=trace_id, call=decision
            )
            for tool_event in outcome.events:
                await self._append_event(
                    request.principal_id, session.events, turn_events, tool_event, event_listener
                )
            return outcome

        async def planning_should_continue() -> str | None:
            try:
                fuse.ensure_within_limits()
            except ResourceFuseExceeded:
                return "resource_fuse"
            if await self._is_cancellation_requested(
                request.principal_id, session.session_id, turn_id
            ):
                return "cancelled"
            return None

        async def planning_after_tool(outcome) -> str | None:
            obs = outcome.observation
            if outcome.identity_resolution is not None:
                session.identity_resolution = outcome.identity_resolution
                if hasattr(self.session_store, "save_session"):
                    await self.session_store.save_session(session)
            if obs is not None:
                observations.append(obs)
                if outcome.persist_evidence:
                    await self._persist_evidence_state(request.principal_id, session)
            if await self._is_cancellation_requested(
                request.principal_id, session.session_id, turn_id
            ):
                return "cancelled"
            return None

        snapshot = None

        async def planning_handle_control(decision, projection):
            nonlocal snapshot
            call = decision
            all_ledger_items = projection.all_ledger_items
            if getattr(call, "action", None) == "compose_answer" or getattr(call, "name", None) == "compose_answer":
                raw_args = getattr(call, "arguments", {}) or {}
                if isinstance(raw_args, Mapping):
                    raw_selected_ids = raw_args.get("selected_evidence_ids") or []
                else:
                    raw_selected_ids = []

                selected_ids = [str(i).strip() for i in raw_selected_ids if str(i).strip()]
                items_by_id = {item.evidence_id: item for item in all_ledger_items}
                selected_items = [items_by_id[evidence_id] for evidence_id in selected_ids]
                budget_check = self.context_engine.budget_manager.check_evidence_selection(
                    question=question,
                    items=selected_items,
                    reviewer_enabled=reviewer_enabled,
                )
                if not budget_check.allowed:
                    try:
                        fuse.consume_step(tool_name="compose_answer:evidence_budget_rejected")
                    except ResourceFuseExceeded:
                        return await resource_fuse_result()
                    await self._append_event(
                        request.principal_id,
                        session.events,
                        turn_events,
                        AgentEvent(
                            event_type="controller_decision",
                            session_id=session.session_id,
                            turn_id=turn_id,
                            trace_id=trace_id,
                            payload={
                                "action": "compose_answer",
                                "tool_name": "compose_answer",
                                "arguments": dict(raw_args),
                            },
                        ),
                        event_listener,
                    )
                    rejection_payload = {
                        "reason": "evidence_budget_exceeded",
                        "selected_evidence_ids": selected_ids,
                        **budget_check.to_dict(),
                    }
                    observations.append(
                        ToolObservation(
                            tool_call_id=call.tool_call_id,
                            tool_name="compose_answer",
                            status="rejected_evidence_budget",
                            payload=rejection_payload,
                            is_terminal=False,
                        )
                    )
                    await self._append_event(
                        request.principal_id,
                        session.events,
                        turn_events,
                        AgentEvent(
                            event_type="compose_answer_rejected",
                            session_id=session.session_id,
                            turn_id=turn_id,
                            trace_id=trace_id,
                            payload=rejection_payload,
                        ),
                        event_listener,
                    )
                    return None
                # Freeze selected evidence from ledger
                snapshot = session.evidence_ledger.freeze(
                    turn_id=turn_id,
                    evidence_ids=selected_ids,
                )
                await self._persist_evidence_state(request.principal_id, session)
                await self._append_event(
                    request.principal_id,
                    session.events,
                    turn_events,
                    AgentEvent(
                        event_type="controller_decision",
                        session_id=session.session_id,
                        turn_id=turn_id,
                        trace_id=trace_id,
                        payload={"action": "compose_answer", "tool_name": "compose_answer", "arguments": dict(raw_args)},
                    ),
                    event_listener,
                )
                await self._append_event(
                    request.principal_id,
                    session.events,
                    turn_events,
                    AgentEvent(
                        event_type="evidence_frozen",
                        session_id=session.session_id,
                        turn_id=turn_id,
                        trace_id=trace_id,
                        payload={
                            "snapshot_id": snapshot.snapshot_id,
                            "evidence_ids": list(snapshot.evidence_ids),
                        },
                    ),
                    event_listener,
                )
                return "compose_answer"

            action = str(getattr(call, "action", "") or getattr(call, "name", "")).strip()
            if action in {"direct_answer", "clarify", "limitation"}:
                return action
            return None

        async def append_publication_event(event: AgentEvent) -> None:
            await self._append_event(
                request.principal_id,
                session.events,
                turn_events,
                event,
                event_listener,
            )

        async def save_publication_snapshot(publication_snapshot: Any, stage: str) -> None:
            await self._save_snapshot_audited(
                snapshot=publication_snapshot,
                session=session,
                request=request,
                stage=stage,
                session_events=session.events,
                turn_events=turn_events,
                event_listener=event_listener,
            )

        async def publication_is_cancelled() -> bool:
            return await self._is_cancellation_requested(
                request.principal_id,
                session.session_id,
                turn_id,
            )

        async def planning_finalize_terminal(kind, decision, projection, tool_outcome):
            if kind == "resource_fuse":
                return await resource_fuse_result()
            if kind == "retrieval_unavailable":
                return await retrieval_unavailable_result()
            if kind == "cancelled":
                return await cancelled_result()
            if await self._is_cancellation_requested(
                request.principal_id,
                session.session_id,
                turn_id,
            ):
                return await cancelled_result()

            call = decision
            if kind == "direct_answer":
                direct_text = getattr(call, "answer", None) or (
                    call.arguments.get("answer")
                    if hasattr(call, "arguments") and isinstance(call.arguments, Mapping)
                    else ""
                ) or ""
                await self._append_event(
                    request.principal_id,
                    session.events,
                    turn_events,
                    AgentEvent(
                        event_type="controller_decision",
                        session_id=session.session_id,
                        turn_id=turn_id,
                        trace_id=trace_id,
                        payload={"action": "direct_answer", "tool_name": "direct_answer", "answer": direct_text},
                    ),
                    event_listener,
                )
                await self.publisher.publish(
                    principal_id=request.principal_id,
                    session=session,
                    turn_events=turn_events,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    publication_state="published",
                    text=direct_text,
                    payload={"answer": direct_text, "source": "controller_direct"},
                    event_listener=event_listener,
                    persist_evidence=True,
                )
                return AgentRunResult(
                    session_id=session.session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    result=DirectAnswerResult(
                        answer=GeneratedAnswer(kind="direct_answer", answer=direct_text, citations=(), units=())
                    ),
                    frozen_evidence=None,
                    review=None,
                    events=tuple(turn_events),
                )

            if kind == "clarify":
                identity_resolution = session.identity_resolution
                if identity_resolution is None or not identity_resolution.requires_confirmation:
                    raise ValueError("clarify requires authoritative ambiguous entity candidates")
                clarification_text = identity_resolution.clarification_text()
                await self._append_event(
                    request.principal_id,
                    session.events,
                    turn_events,
                    AgentEvent(
                        event_type="controller_decision",
                        session_id=session.session_id,
                        turn_id=turn_id,
                        trace_id=trace_id,
                        payload={"action": "clarify", "tool_name": "clarify", "question": clarification_text},
                    ),
                    event_listener,
                )
                await self.publisher.publish(
                    principal_id=request.principal_id,
                    session=session,
                    turn_events=turn_events,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    publication_state="clarification_required",
                    text=clarification_text,
                    payload={"question": clarification_text},
                    event_listener=event_listener,
                    persist_evidence=True,
                )
                return AgentRunResult(
                    session_id=session.session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    result=ClarificationRequired(question=clarification_text),
                    frozen_evidence=None,
                    review=None,
                    events=tuple(turn_events),
                )

            if kind == "limitation":
                raw_msg = (
                    call.arguments.get("message")
                    if hasattr(call, "arguments") and isinstance(call.arguments, Mapping)
                    else None
                )
                limitation_text = (
                    str(raw_msg).strip()
                    if raw_msg
                    else "知识库中未检索到相关确定性依据，系统无法在无证据支持的情况下回答该问题。"
                )
                await self._append_event(
                    request.principal_id,
                    session.events,
                    turn_events,
                    AgentEvent(
                        event_type="controller_decision",
                        session_id=session.session_id,
                        turn_id=turn_id,
                        trace_id=trace_id,
                        payload={"action": "limitation", "tool_name": "limitation", "message": limitation_text},
                    ),
                    event_listener,
                )
                await self.publisher.publish(
                    principal_id=request.principal_id,
                    session=session,
                    turn_events=turn_events,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    publication_state="limitation",
                    text=limitation_text,
                    payload={"message": limitation_text},
                    event_listener=event_listener,
                    persist_evidence=True,
                )
                return AgentRunResult(
                    session_id=session.session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    result=SafeLimitation(message=limitation_text),
                    frozen_evidence=None,
                    review=None,
                    events=tuple(turn_events),
                )

            if kind == "browser_execution_required":
                observation = tool_outcome.observation if tool_outcome is not None else None
                if observation is None:
                    raise RuntimeError("browser execution terminal requires tool observation")
                action_payload = observation.payload["map_action"]
                tool_name = str(getattr(call, "tool", None) or getattr(call, "name", None) or "")
                continuation_token = str(uuid4())
                map_action = MapAction(
                    type=str(action_payload["type"]),
                    target=str(action_payload["target"]),
                    timeout_seconds=(
                        float(action_payload["timeout_seconds"])
                        if action_payload.get("timeout_seconds") is not None
                        else None
                    ),
                    payload=action_payload.get("payload"),
                )
                await self._append_event(
                    request.principal_id,
                    session.events,
                    turn_events,
                    AgentEvent(
                        event_type="browser_tool_requested",
                        session_id=session.session_id,
                        turn_id=turn_id,
                        trace_id=trace_id,
                        payload={
                            "tool_name": tool_name,
                            "tool_call_id": call.tool_call_id,
                            "arguments": dict(call.arguments),
                        },
                    ),
                    event_listener,
                )
                session.pending_browser_execution = PendingBrowserExecution(
                    token=continuation_token,
                    question=question,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    tool_call_id=call.tool_call_id,
                    tool_name=tool_name,
                    observations=tuple(observations[:-1]),
                    request_context=dict(effective_request_context),
                    reviewer_enabled=reviewer_enabled,
                    thinking=thinking,
                    max_steps=max_steps,
                    steps_used=fuse.steps,
                    max_elapsed_seconds=max(fuse.remaining_seconds, 0.001),
                    retrieval_constraints=retrieval_constraints,
                    main_model_name=main_model_name,
                    session_id=session.session_id,
                )
                if hasattr(self.session_store, "save_session"):
                    await self.session_store.save_session(session)
                return AgentRunResult(
                    session_id=session.session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    result=BrowserToolExecutionRequired(
                        tool_call_id=call.tool_call_id,
                        tool_name=tool_name,
                        continuation_token=continuation_token,
                        map_action=map_action,
                    ),
                    frozen_evidence=None,
                    review=None,
                    events=tuple(turn_events),
                    remaining_steps=fuse.remaining_steps,
                    remaining_seconds=round(max(fuse.remaining_seconds, 0.0), 3),
                )

            if kind != "compose_answer":
                raise RuntimeError(f"unhandled LangGraph terminal kind: {kind!r}")
            if snapshot is None or not snapshot.items:
                raise ValueError("knowledge publication requires Frozen Evidence")

            answer_frame = projection.frame
            conv_summary = projection.controller_projection.conversation_text
            try:
                publication_outcome = await self.answer_publication_pipeline.run(
                    question=question,
                    snapshot=snapshot,
                    frame=answer_frame,
                    conversation_summary=conv_summary,
                    stage_policy=stage_policy,
                    model_name=main_model_name,
                    reviewer_enabled=reviewer_enabled,
                    principal_id=request.principal_id,
                    session_id=session.session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    append_event=append_publication_event,
                    save_snapshot=save_publication_snapshot,
                    is_cancelled=publication_is_cancelled,
                )
            except Exception as exc:
                # The stream boundary will still surface the original exception,
                # but the durable turn must not remain indefinitely "running".
                # Persist only failure classification here; semantic recovery and
                # provider retry remain owned by their existing stages.
                logger.exception(
                    "Answer publication failed after evidence freeze: session_id=%s turn_id=%s",
                    session.session_id,
                    turn_id,
                )
                await self.publisher.publish(
                    principal_id=request.principal_id,
                    session=session,
                    turn_events=turn_events,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    publication_state="runtime_error",
                    text="查询处理失败，请稍后重试。",
                    payload={
                        "failure_stage": "answer_publication",
                        "error_type": type(exc).__name__,
                    },
                    event_listener=event_listener,
                )
                raise
            if publication_outcome.terminal_state == "cancelled":
                return await cancelled_result()
            if publication_outcome.terminal_state == "resource_fuse":
                return await resource_fuse_result()
            if publication_outcome.terminal_state == "model_output_invalid":
                return await model_output_failure_result(
                    failure_stage=publication_outcome.failure_stage or "answer_generation",
                    error=publication_outcome.error or "invalid structured answer output",
                )
            if publication_outcome.terminal_state is not None:
                limitation = str(publication_outcome.message or "答案未发布。")
                await self.publisher.publish(
                    principal_id=request.principal_id,
                    session=session,
                    turn_events=turn_events,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    publication_state=publication_outcome.terminal_state,
                    text=limitation,
                    payload=publication_outcome.publication_payload,
                    event_listener=event_listener,
                )
                return AgentRunResult(
                    session_id=session.session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    result=NoSafeAnswer(
                        reason=publication_outcome.terminal_state,
                        message=limitation,
                    ),
                    frozen_evidence=snapshot,
                    review=publication_outcome.review,
                    events=tuple(turn_events),
                )

            answer = publication_outcome.answer
            if answer is None:
                raise RuntimeError("answer publication pipeline returned no answer")
            if await publication_is_cancelled():
                return await cancelled_result()

            await self.publisher.publish(
                principal_id=request.principal_id,
                session=session,
                turn_events=turn_events,
                turn_id=turn_id,
                trace_id=trace_id,
                publication_state="published",
                text=answer.answer,
                payload={"citations": list(answer.citations)},
                event_listener=event_listener,
                persist_evidence=True,
            )
            if answer.kind in {"direct", "direct_answer"}:
                publication_result = DirectAnswerResult(
                    answer=answer if answer.kind == "direct_answer" else GeneratedAnswer(
                        kind="direct_answer",
                        answer=answer.answer,
                        citations=(),
                        units=(),
                    )
                )
            else:
                publication_result = KnowledgeAnswerResult(answer=answer)
            return AgentRunResult(
                session_id=session.session_id,
                turn_id=turn_id,
                trace_id=trace_id,
                result=publication_result,
                frozen_evidence=snapshot,
                review=publication_outcome.review,
                events=tuple(turn_events),
                remaining_steps=fuse.remaining_steps,
                remaining_seconds=round(max(fuse.remaining_seconds, 0.0), 3),
            )


        planning_context = PlanningGraphContext(
            project_context=planning_project_context,
            decide=planning_decide,
            execute_tool=planning_execute_tool,
            should_continue=planning_should_continue,
            after_tool=planning_after_tool,
            handle_control=planning_handle_control,
            finalize_terminal=planning_finalize_terminal,
        )
        try:
            planning_state = await planning_graph.ainvoke(
                {
                    "principal_id": request.principal_id,
                    "session_id": session.session_id,
                    "turn_id": turn_id,
                    "trace_id": trace_id,
                    "question": question,
                },
                context=planning_context,
            )
        except TimeoutError:
            return await resource_fuse_result()
        except ControllerOutputError as exc:
            return await model_output_failure_result(failure_stage="controller", error=str(exc))

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
