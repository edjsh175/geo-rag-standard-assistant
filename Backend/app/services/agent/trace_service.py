"""Trace observability and historical audit service for Agent turns."""

from __future__ import annotations

from typing import Any, Mapping
from app.services.agent.events import AgentEvent
from app.services.agent.store import AgentStore, PostgresAgentStore


class AgentTraceService:
    """Provides structured, admin-audited read access to execution traces."""

    def __init__(self, session_store: AgentStore | None = None) -> None:
        self.session_store = session_store or PostgresAgentStore()

    async def get_turn_trace(
        self,
        *,
        principal_id: str,
        session_id: str,
        turn_id: str,
    ) -> dict[str, Any] | None:
        """Aggregate all trace facts, events, model audits, snapshots, and verdicts for a specific turn."""
        if not hasattr(self.session_store, "list_events"):
            return None

        # Fetch session events
        all_events = await self.session_store.list_events(
            principal_id=principal_id,
            session_id=session_id,
        )
        turn_events = [e for e in all_events if e.turn_id == turn_id]
        if not turn_events:
            return None

        trace_id = ""
        for e in turn_events:
            if getattr(e, "trace_id", ""):
                trace_id = e.trace_id
                break

        # Ordered events
        ordered_events = [
            {
                "event_id": e.event_id,
                "event_type": e.event_type,
                "sequence": e.sequence,
                "turn_id": e.turn_id,
                "trace_id": getattr(e, "trace_id", ""),
                "created_at": e.created_at.isoformat(),
                "payload": dict(e.payload),
            }
            for e in turn_events
        ]

        # Model call audits from events
        model_call_audits = [
            e.payload
            for e in turn_events
            if e.event_type == "model_call_audited"
        ]

        # Context snapshot IDs
        context_snapshot_ids = []
        for e in turn_events:
            snap_id = e.payload.get("snapshot_id") or e.payload.get("context_snapshot_id")
            if snap_id and snap_id not in context_snapshot_ids:
                context_snapshot_ids.append(snap_id)

        # Selected / frozen evidence IDs
        selected_evidence_ids = []
        for e in turn_events:
            ids = e.payload.get("evidence_ids") or e.payload.get("selected_evidence_ids") or []
            if isinstance(ids, (list, tuple)):
                for eid in ids:
                    if eid not in selected_evidence_ids:
                        selected_evidence_ids.append(eid)

        # Tool calls & receipts
        tool_calls = [
            {
                "event_type": e.event_type,
                "tool_name": e.payload.get("tool_name"),
                "tool_call_id": e.payload.get("tool_call_id"),
                "arguments": e.payload.get("arguments"),
                "status": e.payload.get("status"),
                "payload": e.payload,
            }
            for e in turn_events
            if e.event_type in {"browser_tool_requested", "tool_executed", "tool_requested"}
        ]

        # Publication result
        publication_event = next(
            (e for e in reversed(turn_events) if e.event_type == "publication_completed"),
            None,
        )
        publication_result = dict(publication_event.payload) if publication_event else None

        # Reviewer verdict
        review_event = next(
            (e for e in reversed(turn_events) if e.event_type == "review_completed"),
            None,
        )
        reviewer_verdict = dict(review_event.payload) if review_event else None

        # Model input audit records if available
        model_input_audits = []
        if hasattr(self.session_store, "list_model_input_audits"):
            try:
                records = await self.session_store.list_model_input_audits(
                    principal_id=principal_id,
                    session_id=session_id,
                    turn_id=turn_id,
                )
                model_input_audits = [
                    {
                        "audit_id": r.audit_id,
                        "stage": r.stage,
                        "call_id": r.call_id,
                        "model_name": r.model_name,
                        "messages_hash": r.messages_hash,
                        "context_snapshot_id": r.context_snapshot_id,
                        "action_surface_hash": r.action_surface_hash,
                        "created_at": r.created_at.isoformat(),
                    }
                    for r in records
                ]
            except Exception:
                model_input_audits = []

        return {
            "session_id": session_id,
            "turn_id": turn_id,
            "trace_id": trace_id,
            "ordered_events": ordered_events,
            "model_call_audits": model_call_audits,
            "model_input_audits": model_input_audits,
            "context_snapshot_ids": context_snapshot_ids,
            "selected_evidence_ids": selected_evidence_ids,
            "tool_calls": tool_calls,
            "publication_result": publication_result,
            "reviewer_verdict": reviewer_verdict,
            "total_events": len(turn_events),
        }

    async def get_trace_by_id(
        self,
        *,
        principal_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        """Find a trace by trace_id and return its aggregated turn trace."""
        # Query store or active sessions for an event with matching trace_id
        if hasattr(self.session_store, "_events"):
            # InMemoryAgentStore fast path
            for key, events in self.session_store._events.items():
                for e in events:
                    if getattr(e, "trace_id", "") == trace_id:
                        return await self.get_turn_trace(
                            principal_id=key[0],
                            session_id=key[1],
                            turn_id=e.turn_id,
                        )
        elif hasattr(self.session_store, "list_events"):
            # Postgres store: try finding by trace_id directly via database query
            if hasattr(self.session_store, "_execute_read"):
                from sqlalchemy import text
                query = text(
                    "SELECT session_id, turn_id, principal_id FROM geoai_agent_events "
                    "WHERE trace_id = :trace_id LIMIT 1"
                )
                row = await self.session_store._execute_read(query, {"trace_id": trace_id})
                if row:
                    return await self.get_turn_trace(
                        principal_id=row["principal_id"],
                        session_id=row["session_id"],
                        turn_id=row["turn_id"],
                    )
        return None
