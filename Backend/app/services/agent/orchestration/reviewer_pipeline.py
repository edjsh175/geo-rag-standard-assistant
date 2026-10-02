"""Grounding review / constrained repair orchestration boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping
from uuid import uuid4

from app.services.agent.answer_generator import AnswerGenerationError, GeneratedAnswer
from app.services.agent.contracts import FrozenEvidenceSnapshot
from app.services.agent.events import AgentEvent
from app.services.agent.event_projection import safe_error
from app.services.agent.orchestration.compat import supported_kwargs
from app.services.agent.reviewer import (
    build_answer_repair_scope,
    validate_answer_repair_draft,
)
from app.services.agent.stage_policy import LLMStagePolicy


AppendEvent = Callable[[AgentEvent], Awaitable[None]]
SaveSnapshot = Callable[[Any, str], Awaitable[None]]
CancellationCheck = Callable[[], Awaitable[bool]]


@dataclass(frozen=True, slots=True)
class ReviewerPipelineOutcome:
    answer: GeneratedAnswer
    review: Any | None
    terminal_state: str | None = None
    message: str | None = None
    publication_payload: Mapping[str, Any] = field(default_factory=dict)


class ReviewerPipeline:
    """Review a grounded draft and perform at most one constrained repair."""

    def __init__(self, *, reviewer: Any, answer_generator: Any, context_engine: Any) -> None:
        self.reviewer = reviewer
        self.answer_generator = answer_generator
        self.context_engine = context_engine

    async def run(
        self,
        *,
        enabled: bool,
        question: str,
        answer: GeneratedAnswer,
        snapshot: FrozenEvidenceSnapshot,
        review_frame: Any,
        stage_policy: LLMStagePolicy,
        model_name: str | None,
        principal_id: str,
        session_id: str,
        turn_id: str,
        trace_id: str,
        append_event: AppendEvent,
        save_snapshot: SaveSnapshot,
        is_cancelled: CancellationCheck,
    ) -> ReviewerPipelineOutcome:
        if not enabled:
            return ReviewerPipelineOutcome(answer=answer, review=None)
        if self.reviewer is None:
            raise RuntimeError("reviewer_enabled but no reviewer is configured")

        reviewer_budget = self.context_engine.budget_manager.check_reviewer_input(
            question=question,
            draft_answer=answer.answer,
            items=snapshot.items,
        )
        if not reviewer_budget.allowed:
            return ReviewerPipelineOutcome(
                answer=answer,
                review=None,
                terminal_state="review_budget_exceeded",
                message="候选答案与冻结证据超过 Reviewer 上下文预算，答案未发布。",
                publication_payload=reviewer_budget.to_dict(),
            )

        _, snapshot_rev = self.context_engine.project_for_reviewer(
            review_frame,
            draft_answer=answer.answer,
        )
        await save_snapshot(snapshot_rev, "reviewer")

        reviewer_kwargs = {
            "question": question,
            "answer": answer,
            "snapshot": snapshot,
            "stage_policy": stage_policy,
            "audit_context": {
                "principal_id": principal_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "trace_id": trace_id,
                "context_snapshot_id": snapshot_rev.snapshot_id,
            },
        }
        if model_name is not None:
            reviewer_kwargs["model_name"] = model_name

        review_id = f"review-{uuid4().hex}"
        await append_event(
            AgentEvent(
                event_type="review_started",
                session_id=session_id,
                turn_id=turn_id,
                trace_id=trace_id,
                payload={"review_id": review_id, "attempt": 1},
            )
        )
        try:
            review = await self.reviewer.review(
                **supported_kwargs(self.reviewer.review, reviewer_kwargs)
            )
        except TimeoutError:
            await append_event(
                AgentEvent(
                    event_type="review_completed",
                    session_id=session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    payload={
                        "review_id": review_id,
                        "attempt": 1,
                        "error": safe_error("REVIEW_FAILED"),
                    },
                )
            )
            return ReviewerPipelineOutcome(
                answer=answer,
                review=None,
                terminal_state="resource_fuse",
                message="Agent 运行达到资源保护上限，未发布答案。",
            )
        except Exception as exc:
            await append_event(
                AgentEvent(
                    event_type="review_completed",
                    session_id=session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    payload={
                        "review_id": review_id,
                        "attempt": 1,
                        "error": safe_error("REVIEW_FAILED"),
                    },
                )
            )
            return ReviewerPipelineOutcome(
                answer=answer,
                review=None,
                terminal_state="review_failed",
                message="证据审查执行失败，答案未发布。",
                publication_payload={"error_type": type(exc).__name__},
            )

        await append_event(
            AgentEvent(
                event_type="review_completed",
                session_id=session_id,
                turn_id=turn_id,
                trace_id=trace_id,
                payload={
                    "review_id": review_id,
                    "attempt": 1,
                    "verdict": str(getattr(review, "verdict", "") or "UNKNOWN").upper(),
                    "finding_count": len(getattr(review, "findings", ()) or ()),
                },
            )
        )
        if await is_cancelled():
            return ReviewerPipelineOutcome(
                answer=answer,
                review=review,
                terminal_state="cancelled",
                message="Agent 运行已取消。",
            )

        verdict = str(getattr(review, "verdict", "")).strip().upper()
        if verdict in {"SUPPORTED", "PASS", "PASSED"}:
            return ReviewerPipelineOutcome(answer=answer, review=review)

        repair_scope = build_answer_repair_scope(answer, review, snapshot)
        await append_event(
            AgentEvent(
                event_type="answer_repair_scope_created",
                session_id=session_id,
                turn_id=turn_id,
                trace_id=trace_id,
                payload=repair_scope,
            )
        )

        repaired_ok = False
        repaired_answer = answer
        final_review = review
        repair_failure_code: str | None = None
        attempted_repair = bool(
            repair_scope.get("editable_units")
            and hasattr(self.answer_generator, "generate_repair")
        )
        if attempted_repair:
            try:
                repair_kwargs = {
                    "question": question,
                    "snapshot": snapshot,
                    "base_answer": answer,
                    "repair_scope": repair_scope,
                    "stage_policy": stage_policy,
                    "model_name": model_name,
                    "audit_context": {
                        "principal_id": principal_id,
                        "session_id": session_id,
                        "turn_id": turn_id,
                    },
                }
                answer_v2 = await self.answer_generator.generate_repair(
                    **supported_kwargs(
                        self.answer_generator.generate_repair,
                        repair_kwargs,
                    )
                )
            except AnswerGenerationError:
                repair_failure_code = "REPAIR_PROTOCOL_INVALID"
            except Exception:
                repair_failure_code = "REPAIR_MODEL_FAILED"

            if repair_failure_code is None:
                try:
                    validate_answer_repair_draft(answer, answer_v2, repair_scope)
                except Exception:
                    repair_failure_code = "REPAIR_CONTRACT_VIOLATION"

            if repair_failure_code is None:
                try:
                    _, snapshot_rev_2 = self.context_engine.project_for_reviewer(
                        review_frame,
                        draft_answer=answer_v2.answer,
                    )
                    await save_snapshot(snapshot_rev_2, "reviewer_repair")
                    reviewer_2_kwargs = {
                        "question": question,
                        "answer": answer_v2,
                        "snapshot": snapshot,
                        "stage_policy": stage_policy,
                        "model_name": model_name,
                        "audit_context": {
                            "principal_id": principal_id,
                            "session_id": session_id,
                            "turn_id": turn_id,
                            "trace_id": trace_id,
                            "context_snapshot_id": snapshot_rev_2.snapshot_id,
                        },
                    }
                    review_id_2 = f"review-{uuid4().hex}"
                    await append_event(
                        AgentEvent(
                            event_type="review_started",
                            session_id=session_id,
                            turn_id=turn_id,
                            trace_id=trace_id,
                            payload={"review_id": review_id_2, "attempt": 2},
                        )
                    )
                    try:
                        review_2 = await self.reviewer.review(
                            **supported_kwargs(self.reviewer.review, reviewer_2_kwargs)
                        )
                    except Exception:
                        await append_event(
                            AgentEvent(
                                event_type="review_completed",
                                session_id=session_id,
                                turn_id=turn_id,
                                trace_id=trace_id,
                                payload={
                                    "review_id": review_id_2,
                                    "attempt": 2,
                                    "error": safe_error("REVIEW2_FAILED"),
                                },
                            )
                        )
                        raise
                    await append_event(
                        AgentEvent(
                            event_type="review_completed",
                            session_id=session_id,
                            turn_id=turn_id,
                            trace_id=trace_id,
                            payload={
                                "review_id": review_id_2,
                                "attempt": 2,
                                "verdict": str(getattr(review_2, "verdict", "") or "UNKNOWN").upper(),
                                "finding_count": len(getattr(review_2, "findings", ()) or ()),
                            },
                        )
                    )
                    if await is_cancelled():
                        return ReviewerPipelineOutcome(
                            answer=answer,
                            review=review,
                            terminal_state="cancelled",
                            message="Agent 运行已取消。",
                        )
                    verdict_2 = str(getattr(review_2, "verdict", "")).strip().upper()
                    if verdict_2 in {"SUPPORTED", "PASS", "PASSED"}:
                        repaired_answer = answer_v2
                        final_review = review_2
                        repaired_ok = True
                    else:
                        repair_failure_code = "REVIEW2_REJECTED"
                except Exception:
                    if repair_failure_code is None:
                        repair_failure_code = "REVIEW2_FAILED"

            await append_event(
                AgentEvent(
                    event_type="answer_repair_completed",
                    session_id=session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    payload=(
                        {"outcome": "succeeded"}
                        if repaired_ok
                        else {
                            "outcome": "failed",
                            "error": safe_error(
                                repair_failure_code or "REPAIR_MODEL_FAILED"
                            ),
                        }
                    ),
                )
            )

        if repaired_ok:
            return ReviewerPipelineOutcome(
                answer=repaired_answer,
                review=final_review,
            )
        return ReviewerPipelineOutcome(
            answer=answer,
            review=review,
            terminal_state="review_rejected",
            message="答案未通过证据审查，未发布。",
            publication_payload={"verdict": verdict},
        )


__all__ = ["ReviewerPipeline", "ReviewerPipelineOutcome"]
