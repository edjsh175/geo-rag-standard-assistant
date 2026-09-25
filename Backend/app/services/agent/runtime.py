"""Main Controller → Tool → Observation loop for GeoRAG Agent mode."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
from typing import Any, AsyncIterator, Callable, Mapping
from uuid import uuid4

from app.services.agent.answer_generator import AnswerGenerationError, GeneratedAnswer
from app.services.agent.controller import ControllerOutputError
from app.services.agent.context import AgentContextBuilder
from app.services.agent.contracts import FrozenEvidenceSnapshot, MapAction
from app.services.agent.events import AgentEvent
from app.services.agent.publication import PublishedResult
from app.services.agent.session import InMemoryAgentSessionStore, PendingBrowserExecution
from app.services.agent.stage_policy import LLMStagePolicy
from app.services.agent.tool_runtime import (
    RetrievalRequestConstraints,
    RetrievalUnavailableError,
    ResourceFuse,
    ResourceFuseExceeded,
    ToolExecutionError,
    ToolObservation,
    ToolRuntime,
)
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


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    session_id: str
    turn_id: str
    trace_id: str
    publication_state: str
    answer: GeneratedAnswer | None
    clarification: str | None
    limitation: str | None
    frozen_evidence: FrozenEvidenceSnapshot | None
    review: Any | None
    events: tuple[AgentEvent, ...]
    pending_tool_call_id: str | None = None
    continuation_token: str | None = None

    @property
    def published_result(self) -> PublishedResult:
        if self.publication_state == "tool_execution_required" and self.answer is not None:
            return PublishedResult.publish(
                text=self.answer.answer,
                publication_state="tool_execution_required",
                map_action=self.answer.map_action,
            )
        if self.publication_state == "published" and self.answer is not None:
            return PublishedResult.publish(
                text=self.answer.answer,
                publication_state="published",
                map_action=self.answer.map_action,
            )
        if self.publication_state == "clarification" and self.clarification:
            return PublishedResult.publish(
                text=self.clarification,
                publication_state="clarification",
                map_action=None,
            )
        if self.publication_state == "limitation" and self.limitation:
            return PublishedResult.publish(
                text=self.limitation,
                publication_state="limitation",
                map_action=None,
            )
        return PublishedResult.safe_fallback(
            publication_state=self.publication_state,
            fallback_text=self.limitation or "答案未通过发布契约，未发布。",
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
        session_store: InMemoryAgentSessionStore,
        reviewer=None,
        context_builder: AgentContextBuilder | None = None,
        spatial_service=None,
    ) -> None:
        self.retrieval_port = retrieval_port
        self.controller = controller
        self.answer_generator = answer_generator
        self.reviewer = reviewer
        self.session_store = session_store
        self.context_builder = context_builder or AgentContextBuilder()
        self.spatial_service = spatial_service
        model_client = getattr(controller, "model_client", None)
        self.endpoint_supports_reasoning = bool(
            getattr(model_client, "supports_reasoning", False)
        )

    async def run(
        self,
        request: AgentRunRequest,
        *,
        event_listener: Callable[[AgentEvent], None] | None = None,
    ) -> AgentRunResult:
        question = request.question.strip()
        if not question:
            raise ValueError("question must not be empty")

        session = self.session_store.get_or_create(
            request.principal_id,
            request.session_id,
        )
        turn_events: list[AgentEvent] = []

        pending = session.pending_browser_execution
        is_continuation = request.continuation_token is not None
        if is_continuation:
            if pending is None or request.continuation_token != pending.token:
                raise ValueError("invalid or expired browser continuation token")
            receipt = request.browser_tool_receipt
            if receipt is None:
                raise ValueError("browser_tool_receipt is required for continuation")
            if (
                str(receipt.get("tool_call_id", "")) != pending.tool_call_id
                or str(receipt.get("tool_name", "")) != pending.tool_name
            ):
                raise ValueError("browser tool receipt does not match pending tool call")
            receipt_status = str(receipt.get("status", ""))
            if receipt_status not in {"succeeded", "failed"}:
                raise ValueError("browser tool receipt has invalid status")

            question = pending.question
            turn_id = pending.turn_id
            trace_id = pending.trace_id
            effective_request_context = dict(pending.request_context)
            effective_request_context["map_context"] = receipt.get("map_context")
            reviewer_enabled = pending.reviewer_enabled
            thinking = pending.thinking
            retrieval_constraints = pending.retrieval_constraints
            max_steps = pending.max_steps
            max_elapsed_seconds = pending.max_elapsed_seconds
            initial_steps = pending.steps_used
            main_model_name = pending.main_model_name
            observations: list[ToolObservation] = list(pending.observations)
            observations.append(
                ToolObservation(
                    tool_call_id=pending.tool_call_id,
                    tool_name=pending.tool_name,
                    status=f"browser_{receipt_status}",
                    payload={
                        "output": receipt.get("output"),
                        "error": receipt.get("error"),
                        "effect": receipt.get("effect") or {},
                        "map_context": receipt.get("map_context") or {},
                    },
                    is_terminal=False,
                )
            )
            receipt_evidence = session.evidence_ledger.add_observation(
                turn_id=turn_id,
                source="browser_gis",
                observation_key=pending.tool_call_id,
                title=f"Browser GIS {pending.tool_name} receipt",
                payload={
                    "status": receipt_status,
                    "output": receipt.get("output"),
                    "error": receipt.get("error"),
                    "effect": receipt.get("effect") or {},
                    "map_context": receipt.get("map_context") or {},
                },
            )
            observations[-1] = ToolObservation(
                tool_call_id=observations[-1].tool_call_id,
                tool_name=observations[-1].tool_name,
                status=observations[-1].status,
                payload={**dict(observations[-1].payload), "evidence_id": receipt_evidence.evidence_id},
                is_terminal=False,
            )
            session.pending_browser_execution = None
            self._append_event(
                session.events,
                turn_events,
                AgentEvent(
                    event_type="browser_tool_completed",
                    session_id=session.session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    payload={
                        "tool_name": pending.tool_name,
                        "tool_call_id": pending.tool_call_id,
                        "status": receipt_status,
                        "effect": receipt.get("effect") or {},
                    },
                ),
                event_listener,
            )
        else:
            if request.browser_tool_receipt is not None:
                raise ValueError("browser_tool_receipt requires continuation_token")
            if pending is not None:
                self._append_event(
                    session.events,
                    turn_events,
                    AgentEvent(
                        event_type="browser_tool_cancelled",
                        session_id=session.session_id,
                        turn_id=pending.turn_id,
                        trace_id=pending.trace_id,
                        payload={
                            "tool_name": pending.tool_name,
                            "tool_call_id": pending.tool_call_id,
                            "reason": "superseded_by_user_request",
                        },
                    ),
                    event_listener,
                )
                session.pending_browser_execution = None
            if not session.events and request.legacy_history:
                self._seed_legacy_history(session.events, request.legacy_history, session.session_id)
            turn_id = session.new_turn_id()
            trace_id = str(uuid4())
            effective_request_context = request.request_context
            reviewer_enabled = request.reviewer_enabled
            thinking = request.thinking
            retrieval_constraints = request.retrieval_constraints
            max_steps = request.max_steps
            max_elapsed_seconds = request.max_elapsed_seconds
            initial_steps = 0
            observations = []

            self._append_event(
                session.events,
                turn_events,
                AgentEvent(
                    event_type="user_message",
                    session_id=session.session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    payload={"text": question},
                ),
                event_listener,
            )

            model_client = getattr(self.controller, "model_client", None)
            resolve_main_model = getattr(model_client, "resolve_main_model", None)
            main_model_name = (
                resolve_main_model(thinking=thinking)
                if callable(resolve_main_model)
                else None
            )

        def resource_fuse_result() -> AgentRunResult:
            limitation = "Agent 运行达到资源保护上限，未发布答案。"
            self._append_event(
                session.events,
                turn_events,
                AgentEvent(
                    event_type="publication_completed",
                    session_id=session.session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    payload={"state": "resource_fuse"},
                ),
                event_listener,
            )
            self._append_assistant_message(
                session.events,
                session_id=session.session_id,
                turn_id=turn_id,
                trace_id=trace_id,
                text=limitation,
            )
            return AgentRunResult(
                session_id=session.session_id,
                turn_id=turn_id,
                trace_id=trace_id,
                publication_state="resource_fuse",
                answer=None,
                clarification=None,
                limitation=limitation,
                frozen_evidence=None,
                review=None,
                events=tuple(turn_events),
            )

        def model_output_failure_result() -> AgentRunResult:
            limitation = "模型输出未满足 Agent 结构化协议，未发布答案。"
            self._append_event(
                session.events,
                turn_events,
                AgentEvent(
                    event_type="publication_completed",
                    session_id=session.session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    payload={"state": "model_output_invalid"},
                ),
                event_listener,
            )
            self._append_assistant_message(
                session.events,
                session_id=session.session_id,
                turn_id=turn_id,
                trace_id=trace_id,
                text=limitation,
            )
            return AgentRunResult(
                session_id=session.session_id,
                turn_id=turn_id,
                trace_id=trace_id,
                publication_state="model_output_invalid",
                answer=None,
                clarification=None,
                limitation=limitation,
                frozen_evidence=None,
                review=None,
                events=tuple(turn_events),
            )

        def retrieval_unavailable_result() -> AgentRunResult:
            limitation = "知识检索服务当前不可用，未发布答案。"
            self._append_event(
                session.events,
                turn_events,
                AgentEvent(
                    event_type="publication_completed",
                    session_id=session.session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    payload={"state": "retrieval_unavailable"},
                ),
                event_listener,
            )
            self._append_assistant_message(
                session.events,
                session_id=session.session_id,
                turn_id=turn_id,
                trace_id=trace_id,
                text=limitation,
            )
            return AgentRunResult(
                session_id=session.session_id,
                turn_id=turn_id,
                trace_id=trace_id,
                publication_state="retrieval_unavailable",
                answer=None,
                clarification=None,
                limitation=limitation,
                frozen_evidence=None,
                review=None,
                events=tuple(turn_events),
            )

        fuse = ResourceFuse(
            max_steps=max_steps,
            max_elapsed_seconds=max_elapsed_seconds,
            initial_steps=initial_steps,
        )
        tool_runtime = ToolRuntime(
            retrieval_port=self.retrieval_port,
            evidence_ledger=session.evidence_ledger,
            resource_fuse=fuse,
            retrieval_constraints=retrieval_constraints,
            spatial_service=self.spatial_service,
        )
        stage_policy = LLMStagePolicy(
            user_thinking=thinking,
            endpoint_supports_reasoning=self.endpoint_supports_reasoning,
            runtime_deadline_at=fuse.deadline_at,
        )

        while True:
            try:
                fuse.ensure_within_limits()
            except ResourceFuseExceeded:
                return resource_fuse_result()
            context = self.context_builder.build(
                question=question,
                prior_events=session.events[:-1],
                working_evidence=tuple(
                    {
                        "evidence_id": item.evidence_id,
                        "citation_id": item.citation_id,
                        "title": item.title,
                        "excerpt": item.text[:800],
                    }
                    for item in session.evidence_ledger.working_evidence(
                        turn_id=turn_id
                    )
                ),
            )
            try:
                controller_kwargs = dict(
                    question=context.current_question,
                    context_summary=self._merge_request_context(
                        context.summary,
                        effective_request_context,
                    ),
                    working_evidence=context.working_evidence,
                    observations=tuple(observations),
                    stage_policy=stage_policy,
                )
                if main_model_name is not None:
                    controller_kwargs["model_name"] = main_model_name
                call = await self.controller.decide(**controller_kwargs)
            except TimeoutError:
                return resource_fuse_result()
            except ControllerOutputError:
                return model_output_failure_result()
            self._append_event(
                session.events,
                turn_events,
                AgentEvent(
                    event_type="controller_decision",
                    session_id=session.session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    payload={"tool_name": call.name, "tool_call_id": call.tool_call_id},
                ),
                event_listener,
            )
            self._append_event(
                session.events,
                turn_events,
                AgentEvent(
                    event_type="tool_started",
                    session_id=session.session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    payload={"tool_name": call.name, "tool_call_id": call.tool_call_id},
                ),
                event_listener,
            )

            try:
                observation = await tool_runtime.execute(turn_id=turn_id, call=call)
            except ResourceFuseExceeded:
                return resource_fuse_result()
            except RetrievalUnavailableError:
                return retrieval_unavailable_result()
            except ToolExecutionError:
                return model_output_failure_result()
            if call.name == "compose_answer":
                snapshot = observation.payload["snapshot"]
                self._append_event(
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

            observations.append(observation)
            self._append_event(
                session.events,
                turn_events,
                AgentEvent(
                    event_type="tool_completed",
                    session_id=session.session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    payload={
                        "tool_name": observation.tool_name,
                        "tool_call_id": observation.tool_call_id,
                        "status": observation.status,
                    },
                ),
                event_listener,
            )

            if not observation.is_terminal:
                continue

            if call.name == "clarify":
                clarification = str(observation.payload["question"])
                self._append_event(
                    session.events,
                    turn_events,
                    AgentEvent(
                        event_type="publication_completed",
                        session_id=session.session_id,
                        turn_id=turn_id,
                        trace_id=trace_id,
                        payload={"state": "clarification"},
                    ),
                    event_listener,
                )
                self._append_assistant_message(
                    session.events,
                    session_id=session.session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    text=clarification,
                )
                return AgentRunResult(
                    session_id=session.session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    publication_state="clarification",
                    answer=None,
                    clarification=clarification,
                    limitation=None,
                    frozen_evidence=None,
                    review=None,
                    events=tuple(turn_events),
                )

            if call.name == "limitation":
                limitation = str(observation.payload["message"])
                self._append_event(
                    session.events,
                    turn_events,
                    AgentEvent(
                        event_type="publication_completed",
                        session_id=session.session_id,
                        turn_id=turn_id,
                        trace_id=trace_id,
                        payload={"state": "limitation"},
                    ),
                    event_listener,
                )
                self._append_assistant_message(
                    session.events,
                    session_id=session.session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    text=limitation,
                )
                return AgentRunResult(
                    session_id=session.session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    publication_state="limitation",
                    answer=None,
                    clarification=None,
                    limitation=limitation,
                    frozen_evidence=None,
                    review=None,
                    events=tuple(turn_events),
                )

            if observation.status == "browser_execution_required":
                action_payload = observation.payload["map_action"]
                continuation_token = str(uuid4())
                map_action = GeneratedAnswer(
                    kind="browser_tool_request",
                    answer="",
                    citations=(),
                    map_action=MapAction(
                        type=str(action_payload["type"]),
                        target=str(action_payload["target"]),
                        payload=action_payload.get("payload"),
                    ),
                    units=(),
                )
                self._append_event(
                    session.events,
                    turn_events,
                    AgentEvent(
                        event_type="browser_tool_requested",
                        session_id=session.session_id,
                        turn_id=turn_id,
                        trace_id=trace_id,
                        payload={
                            "tool_name": call.name,
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
                    tool_name=call.name,
                    observations=tuple(observations[:-1]),
                    request_context=dict(effective_request_context),
                    reviewer_enabled=reviewer_enabled,
                    thinking=thinking,
                    max_steps=max_steps,
                    steps_used=fuse.steps,
                    max_elapsed_seconds=max(fuse.remaining_seconds, 0.001),
                    retrieval_constraints=retrieval_constraints,
                    main_model_name=main_model_name,
                )
                return AgentRunResult(
                    session_id=session.session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    publication_state="tool_execution_required",
                    answer=map_action,
                    clarification=None,
                    limitation=None,
                    frozen_evidence=None,
                    review=None,
                    events=tuple(turn_events),
                    pending_tool_call_id=call.tool_call_id,
                    continuation_token=continuation_token,
                )

            snapshot = observation.payload["snapshot"]
            if not snapshot.items:
                raise ValueError("knowledge publication requires Frozen Evidence")
            try:
                answer_kwargs = dict(
                    question=question,
                    snapshot=snapshot,
                    stage_policy=stage_policy,
                )
                if main_model_name is not None:
                    answer_kwargs["model_name"] = main_model_name
                answer = await self.answer_generator.generate(**answer_kwargs)
            except TimeoutError:
                return resource_fuse_result()
            except AnswerGenerationError:
                return model_output_failure_result()
            self._append_event(
                session.events,
                turn_events,
                AgentEvent(
                    event_type="answer_generated",
                    session_id=session.session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    payload={"kind": answer.kind, "citations": list(answer.citations)},
                ),
                event_listener,
            )

            review = None
            if reviewer_enabled:
                if self.reviewer is None:
                    raise RuntimeError("reviewer_enabled but no reviewer is configured")
                try:
                    reviewer_kwargs = dict(
                        question=question,
                        answer=answer,
                        snapshot=snapshot,
                        stage_policy=stage_policy,
                    )
                    if main_model_name is not None:
                        reviewer_kwargs["model_name"] = main_model_name
                    review = await self.reviewer.review(**reviewer_kwargs)
                except TimeoutError:
                    return resource_fuse_result()
                except Exception as exc:
                    limitation = "证据审查执行失败，答案未发布。"
                    self._append_event(
                        session.events,
                        turn_events,
                        AgentEvent(
                            event_type="publication_completed",
                            session_id=session.session_id,
                            turn_id=turn_id,
                            trace_id=trace_id,
                            payload={
                                "state": "review_failed",
                                "error_type": type(exc).__name__,
                            },
                        ),
                        event_listener,
                    )
                    self._append_assistant_message(
                        session.events,
                        session_id=session.session_id,
                        turn_id=turn_id,
                        trace_id=trace_id,
                        text=limitation,
                    )
                    return AgentRunResult(
                        session_id=session.session_id,
                        turn_id=turn_id,
                        trace_id=trace_id,
                        publication_state="review_failed",
                        answer=None,
                        clarification=None,
                        limitation=limitation,
                        frozen_evidence=snapshot,
                        review=None,
                        events=tuple(turn_events),
                    )
                verdict = str(getattr(review, "verdict", "")).strip().upper()
                if verdict not in {"SUPPORTED", "PASS", "PASSED"}:
                    limitation = "答案未通过证据审查，未发布。"
                    self._append_event(
                        session.events,
                        turn_events,
                        AgentEvent(
                            event_type="publication_completed",
                            session_id=session.session_id,
                            turn_id=turn_id,
                            trace_id=trace_id,
                            payload={"state": "review_rejected", "verdict": verdict},
                        ),
                        event_listener,
                    )
                    self._append_assistant_message(
                        session.events,
                        session_id=session.session_id,
                        turn_id=turn_id,
                        trace_id=trace_id,
                        text=limitation,
                    )
                    return AgentRunResult(
                        session_id=session.session_id,
                        turn_id=turn_id,
                        trace_id=trace_id,
                        publication_state="review_rejected",
                        answer=None,
                        clarification=None,
                        limitation=limitation,
                        frozen_evidence=snapshot,
                        review=review,
                        events=tuple(turn_events),
                    )

            self._append_event(
                session.events,
                turn_events,
                AgentEvent(
                    event_type="publication_completed",
                    session_id=session.session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    payload={"state": "published"},
                ),
                event_listener,
            )
            self._append_assistant_message(
                session.events,
                session_id=session.session_id,
                turn_id=turn_id,
                trace_id=trace_id,
                text=answer.answer,
            )
            return AgentRunResult(
                session_id=session.session_id,
                turn_id=turn_id,
                trace_id=trace_id,
                publication_state="published",
                answer=answer,
                clarification=None,
                limitation=None,
                frozen_evidence=snapshot,
                review=review,
                events=tuple(turn_events),
            )

    async def stream(self, request: AgentRunRequest) -> AsyncIterator[AgentStreamFrame]:
        """Project observable events from the exact same ``run`` execution path."""

        queue: asyncio.Queue[AgentEvent | object] = asyncio.Queue()
        sentinel = object()
        result_holder: list[AgentRunResult] = []

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
        while True:
            item = await queue.get()
            if item is sentinel:
                break
            yield AgentStreamFrame(event=item)  # type: ignore[arg-type]

        await task
        yield AgentStreamFrame(result=result_holder[0])

    @staticmethod
    def _append_event(
        session_events: list[AgentEvent],
        turn_events: list[AgentEvent],
        event: AgentEvent,
        event_listener: Callable[[AgentEvent], None] | None = None,
    ) -> None:
        session_events.append(event)
        turn_events.append(event)
        if event_listener is not None:
            event_listener(event)

    @staticmethod
    def _append_assistant_message(
        session_events: list[AgentEvent],
        *,
        session_id: str,
        turn_id: str,
        trace_id: str,
        text: str,
    ) -> None:
        if not text.strip():
            return
        session_events.append(
            AgentEvent(
                event_type="assistant_message",
                session_id=session_id,
                turn_id=turn_id,
                trace_id=trace_id,
                payload={"text": text.strip()},
            )
        )

    @staticmethod
    def _merge_request_context(
        summary: str,
        request_context: Mapping[str, Any],
    ) -> str:
        if not request_context:
            return summary
        factual_context = json.dumps(
            dict(request_context),
            ensure_ascii=False,
            default=str,
            sort_keys=True,
        )
        if not summary:
            return f"request_context: {factual_context}"
        return f"{summary}\nrequest_context: {factual_context}"

    @staticmethod
    def _seed_legacy_history(
        session_events: list[AgentEvent],
        history: tuple[Mapping[str, str], ...],
        session_id: str,
    ) -> None:
        for index, message in enumerate(history, start=1):
            role = message.get("role")
            content = message.get("content")
            if role not in {"user", "assistant"} or not isinstance(content, str) or not content.strip():
                continue
            session_events.append(
                AgentEvent(
                    event_type="user_message" if role == "user" else "assistant_message",
                    session_id=session_id,
                    turn_id=f"legacy-{index}",
                    trace_id="legacy-seed",
                    payload={"text": content.strip()},
                )
            )
