"""Browser GIS interrupt/resume boundary for Agent orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.services.agent.event_projection import browser_receipt_summary, safe_error
from app.services.agent.events import AgentEvent
from app.services.agent.session import AgentSession, PendingBrowserExecution
from app.services.agent.tool_runtime import ToolObservation


@dataclass(frozen=True, slots=True)
class BrowserResumeState:
    pending: PendingBrowserExecution
    question: str
    turn_id: str
    trace_id: str
    request_context: Mapping[str, Any]
    reviewer_enabled: bool
    thinking: bool
    retrieval_constraints: Any
    max_steps: int
    max_elapsed_seconds: float
    initial_steps: int
    main_model_name: str | None
    observations: tuple[ToolObservation, ...]
    completion_event: AgentEvent


class BrowserContinuationHandler:
    """Validate and consume one server-owned browser continuation.

    The handler owns continuation protocol semantics but not event publication
    or evidence persistence.  Runtime remains responsible for persisting the
    returned event and the mutated EvidenceLedger exactly once.
    """

    def __init__(self, session_store: Any) -> None:
        self.session_store = session_store

    async def resume(
        self,
        *,
        session: AgentSession,
        principal_id: str,
        session_id: str,
        pending: PendingBrowserExecution | None,
        continuation_token: str | None,
        receipt: Mapping[str, Any] | None,
    ) -> BrowserResumeState:
        if pending is None or not continuation_token or continuation_token != pending.token:
            raise ValueError("invalid or expired browser continuation token")
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

        if hasattr(self.session_store, "claim_pending_execution"):
            claimed_pending = await self.session_store.claim_pending_execution(
                principal_id,
                session_id,
                continuation_token,
            )
            if claimed_pending is None:
                raise ValueError("invalid or expired browser continuation token")
            pending = claimed_pending

        request_context = dict(pending.request_context)
        request_context["browser_observations"] = {
            "map_context": receipt.get("map_context") or {}
        }
        observations = list(pending.observations)
        receipt_payload = {
            "output": receipt.get("output"),
            "error": receipt.get("error"),
            "effect": receipt.get("effect") or {},
            "map_context": receipt.get("map_context") or {},
        }
        receipt_evidence = session.evidence_ledger.add_observation(
            turn_id=pending.turn_id,
            source="browser_gis",
            observation_key=pending.tool_call_id,
            title=f"Browser GIS {pending.tool_name} receipt",
            payload={"status": receipt_status, **receipt_payload},
        )
        observations.append(
            ToolObservation(
                tool_call_id=pending.tool_call_id,
                tool_name=pending.tool_name,
                status=f"browser_{receipt_status}",
                payload={**receipt_payload, "evidence_id": receipt_evidence.evidence_id},
                is_terminal=False,
            )
        )
        session.pending_browser_execution = None

        completion_event = AgentEvent(
            event_type="browser_tool_completed",
            session_id=session.session_id,
            turn_id=pending.turn_id,
            trace_id=pending.trace_id,
            payload={
                "tool_name": pending.tool_name,
                "tool_call_id": pending.tool_call_id,
                "status": receipt_status,
                "receipt": browser_receipt_summary(receipt),
                **({"error": safe_error("TOOL_FAILED")} if receipt_status == "failed" else {}),
            },
        )
        return BrowserResumeState(
            pending=pending,
            question=pending.question,
            turn_id=pending.turn_id,
            trace_id=pending.trace_id,
            request_context=request_context,
            reviewer_enabled=pending.reviewer_enabled,
            thinking=pending.thinking,
            retrieval_constraints=pending.retrieval_constraints,
            max_steps=pending.max_steps,
            max_elapsed_seconds=pending.max_elapsed_seconds,
            initial_steps=pending.steps_used,
            main_model_name=pending.main_model_name,
            observations=tuple(observations),
            completion_event=completion_event,
        )

    async def supersede_pending(
        self,
        *,
        session: AgentSession,
        principal_id: str,
        session_id: str,
        pending: PendingBrowserExecution | None,
    ) -> AgentEvent | None:
        if pending is None:
            return None
        session.pending_browser_execution = None
        if hasattr(self.session_store, "clear_pending_execution"):
            await self.session_store.clear_pending_execution(principal_id, session_id)
        return AgentEvent(
            event_type="browser_tool_cancelled",
            session_id=session.session_id,
            turn_id=pending.turn_id,
            trace_id=pending.trace_id,
            payload={
                "tool_name": pending.tool_name,
                "tool_call_id": pending.tool_call_id,
                "reason": "superseded_by_user_request",
            },
        )


__all__ = ["BrowserContinuationHandler", "BrowserResumeState"]
