"""Grounded answer generation + optional review orchestration boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping

from app.services.agent.answer_generator import AnswerGenerationError, GeneratedAnswer
from app.services.agent.contracts import FrozenEvidenceSnapshot
from app.services.agent.events import AgentEvent
from app.services.agent.orchestration.compat import supported_kwargs
from app.services.agent.orchestration.reviewer_pipeline import ReviewerPipeline
from app.services.agent.stage_policy import LLMStagePolicy


AppendEvent = Callable[[AgentEvent], Awaitable[None]]
SaveSnapshot = Callable[[Any, str], Awaitable[None]]
CancellationCheck = Callable[[], Awaitable[bool]]


@dataclass(frozen=True, slots=True)
class AnswerPublicationOutcome:
    answer: GeneratedAnswer | None
    review: Any | None
    terminal_state: str | None = None
    message: str | None = None
    publication_payload: Mapping[str, Any] = field(default_factory=dict)
    failure_stage: str | None = None
    error: str | None = None


class AnswerPublicationPipeline:
    """Generate a grounded draft and pass it through the Reviewer pipeline.

    The pipeline does not publish user-visible messages itself.  Publication
    remains a separate boundary so answer generation/review can be tested and
    reused by Agent and Linear flows without acquiring persistence authority.
    """

    def __init__(
        self,
        *,
        answer_generator: Any,
        reviewer_pipeline: ReviewerPipeline,
        context_engine: Any,
    ) -> None:
        self.answer_generator = answer_generator
        self.reviewer_pipeline = reviewer_pipeline
        self.context_engine = context_engine

    async def run(
        self,
        *,
        question: str,
        snapshot: FrozenEvidenceSnapshot,
        frame: Any,
        conversation_summary: str,
        stage_policy: LLMStagePolicy,
        model_name: str | None,
        reviewer_enabled: bool,
        principal_id: str,
        session_id: str,
        turn_id: str,
        trace_id: str,
        append_event: AppendEvent,
        save_snapshot: SaveSnapshot,
        is_cancelled: CancellationCheck,
    ) -> AnswerPublicationOutcome:
        _, answer_snapshot = self.context_engine.project_for_answer(
            frame,
            conversation_summary=conversation_summary,
        )
        await save_snapshot(answer_snapshot, "answer")

        answer_kwargs = {
            "question": question,
            "snapshot": snapshot,
            "stage_policy": stage_policy,
            "audit_context": {
                "principal_id": principal_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "trace_id": trace_id,
                "context_snapshot_id": answer_snapshot.snapshot_id,
            },
        }
        if model_name is not None:
            answer_kwargs["model_name"] = model_name
        try:
            answer = await self.answer_generator.generate(
                **supported_kwargs(self.answer_generator.generate, answer_kwargs)
            )
        except TimeoutError:
            return AnswerPublicationOutcome(
                answer=None,
                review=None,
                terminal_state="resource_fuse",
                message="Agent 运行达到资源保护上限，未发布答案。",
            )
        except AnswerGenerationError as exc:
            return AnswerPublicationOutcome(
                answer=None,
                review=None,
                terminal_state="model_output_invalid",
                message="模型输出未满足 Agent 结构化协议，未发布答案。",
                failure_stage="answer_generation",
                error=str(exc),
            )

        if await is_cancelled():
            return AnswerPublicationOutcome(
                answer=answer,
                review=None,
                terminal_state="cancelled",
                message="Agent 运行已取消。",
            )
        await append_event(
            AgentEvent(
                event_type="answer_generated",
                session_id=session_id,
                turn_id=turn_id,
                trace_id=trace_id,
                payload={"kind": answer.kind, "citations": list(answer.citations)},
            )
        )

        review_outcome = await self.reviewer_pipeline.run(
            enabled=reviewer_enabled,
            question=question,
            answer=answer,
            snapshot=snapshot,
            review_frame=frame,
            stage_policy=stage_policy,
            model_name=model_name,
            principal_id=principal_id,
            session_id=session_id,
            turn_id=turn_id,
            trace_id=trace_id,
            append_event=append_event,
            save_snapshot=save_snapshot,
            is_cancelled=is_cancelled,
        )
        return AnswerPublicationOutcome(
            answer=review_outcome.answer,
            review=review_outcome.review,
            terminal_state=review_outcome.terminal_state,
            message=review_outcome.message,
            publication_payload=review_outcome.publication_payload,
        )


__all__ = ["AnswerPublicationOutcome", "AnswerPublicationPipeline"]
