"""Request-scoped execution context for a single Agent turn.

Encapsulates mutable turn state, resource fuse tracking, event dispatching,
and graph terminal finalization, decoupling the execution lifecycle from
monolithic closures in AgentRuntime.run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import TYPE_CHECKING, Any, Callable, Mapping
from uuid import uuid4

from app.services.agent.answer_generator import GeneratedAnswer
from app.services.agent.contracts import FrozenEvidenceSnapshot, MapAction
from app.services.agent.events import AgentEvent
from app.services.agent.orchestration.compat import supported_kwargs
from app.services.agent.publication import (
    BrowserToolExecutionRequired,
    ClarificationRequired,
    DirectAnswerResult,
    KnowledgeAnswerResult,
    NoSafeAnswer,
    SafeLimitation,
)
from app.services.agent.session import PendingBrowserExecution
from app.services.agent.tool_runtime import (
    ResourceFuse,
    ResourceFuseExceeded,
    RetrievalRequestConstraints,
    ToolObservation,
)

if TYPE_CHECKING:
    from app.services.agent.runtime import AgentRunRequest, AgentRunResult, AgentRuntime
    from app.services.agent.orchestration import ToolExecutionCoordinator
    from app.services.agent.stage_policy import LLMStagePolicy

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TurnExecutionContext:
    runtime: AgentRuntime
    request: AgentRunRequest
    session: Any
    turn_id: str
    trace_id: str
    question: str
    effective_request_context: Mapping[str, Any]
    reviewer_enabled: bool
    thinking: bool
    retrieval_constraints: RetrievalRequestConstraints
    max_steps: int
    max_elapsed_seconds: float
    initial_steps: int
    main_model_name: str | None
    fuse: ResourceFuse
    registry: Any
    tool_execution: ToolExecutionCoordinator
    stage_policy: LLMStagePolicy
    provider_health: Mapping[str, bool]
    turn_events: list[AgentEvent] = field(default_factory=list)
    observations: list[ToolObservation] = field(default_factory=list)
    event_listener: Callable[[AgentEvent], None] | None = None
    snapshot: FrozenEvidenceSnapshot | None = None

    async def persist_turn_event(self, event: AgentEvent) -> AgentEvent:
        persisted = await self.runtime._persist_event(self.request.principal_id, event)
        self.turn_events.append(persisted)
        if self.event_listener is not None:
            self.event_listener(persisted)
        return persisted

    async def persist_session_event(self, event: AgentEvent) -> AgentEvent:
        return await self.runtime._persist_event(self.request.principal_id, event)

    async def persist_lifecycle_evidence(self, lifecycle_session: Any) -> None:
        await self.runtime._persist_evidence_state(self.request.principal_id, lifecycle_session)

    async def append_event(self, event: AgentEvent) -> AgentEvent:
        return await self.runtime._append_event(
            self.request.principal_id,
            self.session.events,
            self.turn_events,
            event,
            self.event_listener,
        )

    async def save_snapshot_audited(self, snapshot: Any, stage: str) -> None:
        await self.runtime._save_snapshot_audited(
            snapshot=snapshot,
            session=self.session,
            request=self.request,
            stage=stage,
            session_events=self.session.events,
            turn_events=self.turn_events,
            event_listener=self.event_listener,
        )

    async def is_cancelled(self) -> bool:
        return await self.runtime._is_cancellation_requested(
            self.request.principal_id,
            self.session.session_id,
            self.turn_id,
        )

    async def build_resource_fuse_result(self) -> AgentRunResult:
        from app.services.agent.runtime import AgentRunResult

        limitation = "Agent 运行达到资源保护上限，未发布答案。"
        await self.runtime.publisher.publish(
            principal_id=self.request.principal_id,
            session=self.session,
            turn_events=self.turn_events,
            turn_id=self.turn_id,
            trace_id=self.trace_id,
            publication_state="resource_fuse",
            text=limitation,
            event_listener=self.event_listener,
        )
        return AgentRunResult(
            session_id=self.session.session_id,
            turn_id=self.turn_id,
            trace_id=self.trace_id,
            result=NoSafeAnswer(reason="resource_fuse", message=limitation),
            frozen_evidence=None,
            review=None,
            events=tuple(self.turn_events),
        )

    async def build_model_output_failure_result(
        self,
        *,
        failure_stage: str,
        error: str,
    ) -> AgentRunResult:
        from app.services.agent.runtime import AgentRunResult

        limitation = "模型输出未满足 Agent 结构化协议，未发布答案。"
        await self.runtime.publisher.publish(
            principal_id=self.request.principal_id,
            session=self.session,
            turn_events=self.turn_events,
            turn_id=self.turn_id,
            trace_id=self.trace_id,
            publication_state="model_output_invalid",
            text=limitation,
            payload={"failure_stage": failure_stage, "error": error},
            event_listener=self.event_listener,
        )
        return AgentRunResult(
            session_id=self.session.session_id,
            turn_id=self.turn_id,
            trace_id=self.trace_id,
            result=NoSafeAnswer(reason="model_output_invalid", message=limitation),
            frozen_evidence=None,
            review=None,
            events=tuple(self.turn_events),
        )

    async def build_retrieval_unavailable_result(self) -> AgentRunResult:
        from app.services.agent.runtime import AgentRunResult

        limitation = "知识检索服务当前不可用，未发布答案。"
        await self.runtime.publisher.publish(
            principal_id=self.request.principal_id,
            session=self.session,
            turn_events=self.turn_events,
            turn_id=self.turn_id,
            trace_id=self.trace_id,
            publication_state="retrieval_unavailable",
            text=limitation,
            event_listener=self.event_listener,
        )
        return AgentRunResult(
            session_id=self.session.session_id,
            turn_id=self.turn_id,
            trace_id=self.trace_id,
            result=NoSafeAnswer(reason="retrieval_unavailable", message=limitation),
            frozen_evidence=None,
            review=None,
            events=tuple(self.turn_events),
        )

    async def build_cancelled_result(self, reason: str = "cancel_requested") -> AgentRunResult:
        from app.services.agent.runtime import AgentRunResult

        limitation = "Agent 运行已取消。"
        event = AgentEvent(
            event_type="run_cancelled",
            session_id=self.session.session_id,
            turn_id=self.turn_id,
            trace_id=self.trace_id,
            payload={"reason": reason},
            event_id=self.runtime._cancellation_event_id(
                self.request.principal_id,
                self.session.session_id,
                self.turn_id,
                "run_cancelled",
            ),
        )
        await self.append_event(event)
        return AgentRunResult(
            session_id=self.session.session_id,
            turn_id=self.turn_id,
            trace_id=self.trace_id,
            result=NoSafeAnswer(reason="cancelled", message=limitation),
            frozen_evidence=None,
            review=None,
            events=tuple(self.turn_events),
        )

    async def project_context(self) -> Any:
        turn_projection = self.runtime.context_projector.project_controller(
            session=self.session,
            principal_id=self.request.principal_id,
            turn_id=self.turn_id,
            question=self.question,
            request_context=self.effective_request_context,
            registry=self.registry,
            provider_health=self.provider_health,
            reviewer_enabled=self.reviewer_enabled,
        )
        await self.save_snapshot_audited(
            snapshot=turn_projection.controller_snapshot,
            stage="controller",
        )
        return turn_projection

    async def decide(self, turn_projection: Any) -> Any:
        proj = turn_projection.controller_projection
        state = turn_projection.action_state
        controller_kwargs = dict(
            projection=proj,
            action_state=state,
            observations=tuple(self.observations),
            stage_policy=self.stage_policy,
            audit_context={
                "principal_id": self.request.principal_id,
                "session_id": self.session.session_id,
                "turn_id": self.turn_id,
                "trace_id": self.trace_id,
                "context_snapshot_id": turn_projection.controller_snapshot.snapshot_id,
            },
            question=proj.user_question,
            context_summary=proj.conversation_text,
            working_evidence=proj.working_evidence,
            available_tool_names=state.available_capabilities,
            available_control_actions=state.available_control_actions,
        )
        if self.main_model_name is not None:
            controller_kwargs["model_name"] = self.main_model_name
        decision = await self.runtime.controller.decide(
            **supported_kwargs(self.runtime.controller.decide, controller_kwargs)
        )
        self.runtime._validate_decision_against_action_state(decision, state)
        return decision

    async def execute_tool(self, decision: Any) -> Any:
        outcome = await self.tool_execution.execute(
            turn_id=self.turn_id,
            session_id=self.session.session_id,
            trace_id=self.trace_id,
            call=decision,
        )
        for tool_event in outcome.events:
            await self.append_event(tool_event)
        return outcome

    async def should_continue(self) -> str | None:
        try:
            self.fuse.ensure_within_limits()
        except ResourceFuseExceeded:
            return "resource_fuse"
        if await self.is_cancelled():
            return "cancelled"
        return None

    async def after_tool(self, outcome: Any) -> str | None:
        obs = outcome.observation
        if outcome.identity_resolution is not None:
            self.session.identity_resolution = outcome.identity_resolution
            if hasattr(self.runtime.session_store, "save_session"):
                await self.runtime.session_store.save_session(self.session)
        if obs is not None:
            self.observations.append(obs)
            if outcome.persist_evidence:
                await self.runtime._persist_evidence_state(self.request.principal_id, self.session)
        if await self.is_cancelled():
            return "cancelled"
        return None

    async def handle_control(self, decision: Any, projection: Any) -> str | None:
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
            budget_check = self.runtime.context_engine.budget_manager.check_evidence_selection(
                question=self.question,
                items=selected_items,
                reviewer_enabled=self.reviewer_enabled,
            )
            if not budget_check.allowed:
                try:
                    self.fuse.consume_step(tool_name="compose_answer:evidence_budget_rejected")
                except ResourceFuseExceeded:
                    return "resource_fuse"
                await self.append_event(
                    AgentEvent(
                        event_type="controller_decision",
                        session_id=self.session.session_id,
                        turn_id=self.turn_id,
                        trace_id=self.trace_id,
                        payload={
                            "action": "compose_answer",
                            "tool_name": "compose_answer",
                            "arguments": dict(raw_args),
                        },
                    )
                )
                rejection_payload = {
                    "reason": "evidence_budget_exceeded",
                    "selected_evidence_ids": selected_ids,
                    **budget_check.to_dict(),
                }
                self.observations.append(
                    ToolObservation(
                        tool_call_id=call.tool_call_id,
                        tool_name="compose_answer",
                        status="rejected_evidence_budget",
                        payload=rejection_payload,
                        is_terminal=False,
                    )
                )
                await self.append_event(
                    AgentEvent(
                        event_type="compose_answer_rejected",
                        session_id=self.session.session_id,
                        turn_id=self.turn_id,
                        trace_id=self.trace_id,
                        payload=rejection_payload,
                    )
                )
                return None

            # Freeze selected evidence from ledger
            self.snapshot = self.session.evidence_ledger.freeze(
                turn_id=self.turn_id,
                evidence_ids=selected_ids,
            )
            await self.runtime._persist_evidence_state(self.request.principal_id, self.session)
            await self.append_event(
                AgentEvent(
                    event_type="controller_decision",
                    session_id=self.session.session_id,
                    turn_id=self.turn_id,
                    trace_id=self.trace_id,
                    payload={
                        "action": "compose_answer",
                        "tool_name": "compose_answer",
                        "arguments": dict(raw_args),
                    },
                )
            )
            await self.append_event(
                AgentEvent(
                    event_type="evidence_frozen",
                    session_id=self.session.session_id,
                    turn_id=self.turn_id,
                    trace_id=self.trace_id,
                    payload={
                        "snapshot_id": self.snapshot.snapshot_id,
                        "evidence_ids": list(self.snapshot.evidence_ids),
                    },
                )
            )
            return "compose_answer"

        action = str(getattr(call, "action", "") or getattr(call, "name", "")).strip()
        if action in {"direct_answer", "clarify", "limitation"}:
            return action
        return None

    async def finalize_terminal(
        self,
        kind: str,
        decision: Any,
        projection: Any,
        tool_outcome: Any,
    ) -> AgentRunResult:
        from app.services.agent.runtime import AgentRunResult

        if kind == "resource_fuse":
            return await self.build_resource_fuse_result()
        if kind == "retrieval_unavailable":
            return await self.build_retrieval_unavailable_result()
        if kind == "cancelled":
            return await self.build_cancelled_result()
        if await self.is_cancelled():
            return await self.build_cancelled_result()

        call = decision
        if kind == "direct_answer":
            direct_text = getattr(call, "answer", None) or (
                call.arguments.get("answer")
                if hasattr(call, "arguments") and isinstance(call.arguments, Mapping)
                else ""
            ) or ""
            await self.append_event(
                AgentEvent(
                    event_type="controller_decision",
                    session_id=self.session.session_id,
                    turn_id=self.turn_id,
                    trace_id=self.trace_id,
                    payload={"action": "direct_answer", "tool_name": "direct_answer", "answer": direct_text},
                )
            )
            await self.runtime.publisher.publish(
                principal_id=self.request.principal_id,
                session=self.session,
                turn_events=self.turn_events,
                turn_id=self.turn_id,
                trace_id=self.trace_id,
                publication_state="published",
                text=direct_text,
                payload={"answer": direct_text, "source": "controller_direct"},
                event_listener=self.event_listener,
                persist_evidence=True,
            )
            return AgentRunResult(
                session_id=self.session.session_id,
                turn_id=self.turn_id,
                trace_id=self.trace_id,
                result=DirectAnswerResult(
                    answer=GeneratedAnswer(kind="direct_answer", answer=direct_text, citations=(), units=())
                ),
                frozen_evidence=None,
                review=None,
                events=tuple(self.turn_events),
            )

        if kind == "clarify":
            identity_resolution = self.session.identity_resolution
            if identity_resolution is None or not identity_resolution.requires_confirmation:
                raise ValueError("clarify requires authoritative ambiguous entity candidates")
            clarification_text = identity_resolution.clarification_text()
            await self.append_event(
                AgentEvent(
                    event_type="controller_decision",
                    session_id=self.session.session_id,
                    turn_id=self.turn_id,
                    trace_id=self.trace_id,
                    payload={"action": "clarify", "tool_name": "clarify", "question": clarification_text},
                )
            )
            await self.runtime.publisher.publish(
                principal_id=self.request.principal_id,
                session=self.session,
                turn_events=self.turn_events,
                turn_id=self.turn_id,
                trace_id=self.trace_id,
                publication_state="clarification_required",
                text=clarification_text,
                payload={"question": clarification_text},
                event_listener=self.event_listener,
                persist_evidence=True,
            )
            return AgentRunResult(
                session_id=self.session.session_id,
                turn_id=self.turn_id,
                trace_id=self.trace_id,
                result=ClarificationRequired(question=clarification_text),
                frozen_evidence=None,
                review=None,
                events=tuple(self.turn_events),
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
            await self.append_event(
                AgentEvent(
                    event_type="controller_decision",
                    session_id=self.session.session_id,
                    turn_id=self.turn_id,
                    trace_id=self.trace_id,
                    payload={"action": "limitation", "tool_name": "limitation", "message": limitation_text},
                )
            )
            await self.runtime.publisher.publish(
                principal_id=self.request.principal_id,
                session=self.session,
                turn_events=self.turn_events,
                turn_id=self.turn_id,
                trace_id=self.trace_id,
                publication_state="limitation",
                text=limitation_text,
                payload={"message": limitation_text},
                event_listener=self.event_listener,
                persist_evidence=True,
            )
            return AgentRunResult(
                session_id=self.session.session_id,
                turn_id=self.turn_id,
                trace_id=self.trace_id,
                result=SafeLimitation(message=limitation_text),
                frozen_evidence=None,
                review=None,
                events=tuple(self.turn_events),
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
            await self.append_event(
                AgentEvent(
                    event_type="browser_tool_requested",
                    session_id=self.session.session_id,
                    turn_id=self.turn_id,
                    trace_id=self.trace_id,
                    payload={
                        "tool_name": tool_name,
                        "tool_call_id": call.tool_call_id,
                        "arguments": dict(call.arguments),
                    },
                )
            )
            self.session.pending_browser_execution = PendingBrowserExecution(
                token=continuation_token,
                question=self.question,
                turn_id=self.turn_id,
                trace_id=self.trace_id,
                tool_call_id=call.tool_call_id,
                tool_name=tool_name,
                observations=tuple(self.observations[:-1]),
                request_context=dict(self.effective_request_context),
                reviewer_enabled=self.reviewer_enabled,
                thinking=self.thinking,
                max_steps=self.max_steps,
                steps_used=self.fuse.steps,
                max_elapsed_seconds=max(self.fuse.remaining_seconds, 0.001),
                retrieval_constraints=self.retrieval_constraints,
                main_model_name=self.main_model_name,
                session_id=self.session.session_id,
            )
            if hasattr(self.runtime.session_store, "save_session"):
                await self.runtime.session_store.save_session(self.session)
            return AgentRunResult(
                session_id=self.session.session_id,
                turn_id=self.turn_id,
                trace_id=self.trace_id,
                result=BrowserToolExecutionRequired(
                    tool_call_id=call.tool_call_id,
                    tool_name=tool_name,
                    continuation_token=continuation_token,
                    map_action=map_action,
                ),
                frozen_evidence=None,
                review=None,
                events=tuple(self.turn_events),
                remaining_steps=self.fuse.remaining_steps,
                remaining_seconds=round(max(self.fuse.remaining_seconds, 0.0), 3),
            )

        if kind != "compose_answer":
            raise RuntimeError(f"unhandled LangGraph terminal kind: {kind!r}")
        if self.snapshot is None or not self.snapshot.items:
            raise ValueError("knowledge publication requires Frozen Evidence")

        answer_frame = projection.frame
        conv_summary = projection.controller_projection.conversation_text
        try:
            publication_outcome = await self.runtime.answer_publication_pipeline.run(
                question=self.question,
                snapshot=self.snapshot,
                frame=answer_frame,
                conversation_summary=conv_summary,
                stage_policy=self.stage_policy,
                model_name=self.main_model_name,
                reviewer_enabled=self.reviewer_enabled,
                principal_id=self.request.principal_id,
                session_id=self.session.session_id,
                turn_id=self.turn_id,
                trace_id=self.trace_id,
                append_event=self.append_event,
                save_snapshot=self.save_snapshot_audited,
                is_cancelled=self.is_cancelled,
            )
        except Exception as exc:
            logger.exception(
                "Answer publication failed after evidence freeze: session_id=%s turn_id=%s",
                self.session.session_id,
                self.turn_id,
            )
            await self.runtime.publisher.publish(
                principal_id=self.request.principal_id,
                session=self.session,
                turn_events=self.turn_events,
                turn_id=self.turn_id,
                trace_id=self.trace_id,
                publication_state="runtime_error",
                text="查询处理失败，请稍后重试。",
                payload={
                    "failure_stage": "answer_publication",
                    "error_type": type(exc).__name__,
                },
                event_listener=self.event_listener,
            )
            raise

        if publication_outcome.terminal_state == "cancelled":
            return await self.build_cancelled_result()
        if publication_outcome.terminal_state == "resource_fuse":
            return await self.build_resource_fuse_result()
        if publication_outcome.terminal_state == "model_output_invalid":
            return await self.build_model_output_failure_result(
                failure_stage=publication_outcome.failure_stage or "answer_generation",
                error=publication_outcome.error or "invalid structured answer output",
            )
        if publication_outcome.terminal_state is not None:
            limitation = str(publication_outcome.message or "答案未发布。")
            await self.runtime.publisher.publish(
                principal_id=self.request.principal_id,
                session=self.session,
                turn_events=self.turn_events,
                turn_id=self.turn_id,
                trace_id=self.trace_id,
                publication_state=publication_outcome.terminal_state,
                text=limitation,
                payload=publication_outcome.publication_payload,
                event_listener=self.event_listener,
            )
            return AgentRunResult(
                session_id=self.session.session_id,
                turn_id=self.turn_id,
                trace_id=self.trace_id,
                result=NoSafeAnswer(
                    reason=publication_outcome.terminal_state,
                    message=limitation,
                ),
                frozen_evidence=self.snapshot,
                review=publication_outcome.review,
                events=tuple(self.turn_events),
            )

        answer = publication_outcome.answer
        if answer is None:
            raise RuntimeError("answer publication pipeline returned no answer")
        if await self.is_cancelled():
            return await self.build_cancelled_result()

        await self.runtime.publisher.publish(
            principal_id=self.request.principal_id,
            session=self.session,
            turn_events=self.turn_events,
            turn_id=self.turn_id,
            trace_id=self.trace_id,
            publication_state="published",
            text=answer.answer,
            payload={"citations": list(answer.citations)},
            event_listener=self.event_listener,
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
            session_id=self.session.session_id,
            turn_id=self.turn_id,
            trace_id=self.trace_id,
            result=publication_result,
            frozen_evidence=self.snapshot,
            review=publication_outcome.review,
            events=tuple(self.turn_events),
            remaining_steps=self.fuse.remaining_steps,
            remaining_seconds=round(max(self.fuse.remaining_seconds, 0.0), 3),
        )
