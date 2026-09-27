"""Server-authoritative Agent Session Service (Phase P: P-06).

Provides session listing, full turn/message reconstruction, and lifecycle management
anchored directly on the durable AgentStore.
"""
from __future__ import annotations

from typing import Any, Mapping
from app.services.agent.events import AgentEvent
from app.services.agent.store import AgentStore, PostgresAgentStore


class AgentSessionService:
    """Manages durable sessions and reconstructs authoritative conversation histories."""

    def __init__(self, session_store: AgentStore | None = None) -> None:
        self.session_store = session_store or PostgresAgentStore()

    async def list_sessions(
        self,
        *,
        principal_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List active sessions owned by the principal."""
        return await self.session_store.list_sessions(principal_id, limit=limit)

    async def get_session_detail(
        self,
        *,
        principal_id: str,
        session_id: str,
    ) -> dict[str, Any] | None:
        """Reconstruct authoritative conversation messages and turns from durable events."""
        session = await self.session_store.get_session(principal_id, session_id)
        if session is None:
            return None

        events: list[AgentEvent] = await self.session_store.list_events(principal_id, session_id)

        # Group events by turn_id
        events_by_turn: dict[str, list[AgentEvent]] = {}
        for ev in events:
            t_id = ev.turn_id or "turn-0"
            events_by_turn.setdefault(t_id, []).append(ev)

        messages: list[dict[str, Any]] = []
        turns: list[dict[str, Any]] = []
        evidence_items = (
            await self.session_store.list_evidence_items(principal_id, session_id, active_only=False)
            if hasattr(self.session_store, "list_evidence_items") else []
        )

        for turn_id, turn_evs in events_by_turn.items():
            user_ev = next((e for e in turn_evs if e.event_type == "user_message"), None)
            if user_ev:
                messages.append({
                    "id": f"msg-{user_ev.event_id}",
                    "role": "user",
                    "content": str(user_ev.payload.get("text") or ""),
                    "timestamp": user_ev.created_at.isoformat(),
                    "turn_id": turn_id,
                    "metadata": {"trace_id": user_ev.trace_id},
                })

            pub_ev = next((e for e in reversed(turn_evs) if e.event_type == "publication_completed"), None)
            asst_ev = next((e for e in reversed(turn_evs) if e.event_type == "assistant_message"), None)
            cancelled_ev = next((e for e in reversed(turn_evs) if e.event_type == "run_cancelled"), None)
            publication_state = (
                str(pub_ev.payload.get("state") or pub_ev.payload.get("publication_state") or "unknown")
                if pub_ev else ("cancelled" if cancelled_ev else "processing")
            )

            if pub_ev:
                payload = dict(pub_ev.payload)
                # Runtime's assistant_message is the authoritative persisted user text;
                # publication events can intentionally contain state only.
                answer_text = str(
                    (asst_ev.payload.get("text") if asst_ev else None)
                    or payload.get("generated_answer")
                    or payload.get("answer")
                    or ""
                )
                frozen_ev = next((e for e in reversed(turn_evs) if e.event_type == "evidence_frozen"), None)
                selected_ids = set((frozen_ev.payload.get("evidence_ids") or frozen_ev.payload.get("selected_evidence_ids") or []) if frozen_ev else [])
                answer_ev = next((e for e in reversed(turn_evs) if e.event_type == "answer_generated"), None)
                cited_ids = set(answer_ev.payload.get("citations") or []) if answer_ev else set()
                chosen_items = [
                    item for item in evidence_items
                    if item.document_id
                    and item.source not in {"browser_gis", "postgis"}
                    and ((item.citation_id in cited_ids) if cited_ids else (item.evidence_id in selected_ids))
                ]
                references = [
                    {
                        "id": item.document_id,
                        "citation_id": item.citation_id,
                        "title": item.title,
                        "document_id": item.document_id,
                        "source": item.source,
                    }
                    for item in chosen_items
                ]
                if not answer_ev and not frozen_ev:
                    legacy_results = payload.get("results")
                    references = legacy_results if isinstance(legacy_results, list) else []
                messages.append({
                    "id": f"msg-{pub_ev.event_id}",
                    "role": "assistant",
                    "content": answer_text,
                    "timestamp": pub_ev.created_at.isoformat(),
                    "turn_id": turn_id,
                    "references": references or payload.get("results") or payload.get("citations") or [],
                    "map_action": payload.get("map_action"),
                    "metadata": {
                        "publication_state": publication_state,
                        "trace_id": pub_ev.trace_id,
                        "session_id": session_id,
                    },
                })
            elif cancelled_ev:
                messages.append({
                    "id": f"msg-{cancelled_ev.event_id}",
                    "role": "assistant",
                    "content": "生成已停止。",
                    "timestamp": cancelled_ev.created_at.isoformat(),
                    "turn_id": turn_id,
                    "metadata": {"publication_state": "cancelled", "trace_id": cancelled_ev.trace_id},
                })
            elif asst_ev:
                messages.append({
                    "id": f"msg-{asst_ev.event_id}",
                    "role": "assistant",
                    "content": str(asst_ev.payload.get("text") or ""),
                    "timestamp": asst_ev.created_at.isoformat(),
                    "turn_id": turn_id,
                    "metadata": {"trace_id": asst_ev.trace_id},
                })

            # Structured turn summary for frontend AgentProcess
            turns.append({
                "turn_id": turn_id,
                "trace_id": turn_evs[0].trace_id if turn_evs else "",
                "status": publication_state,
                "event_count": len(turn_evs),
                "events": [
                    {
                        "event_id": e.event_id,
                        "event_type": e.event_type,
                        "sequence": e.sequence,
                        "payload": dict(e.payload),
                        "created_at": e.created_at.isoformat(),
                    }
                    for e in turn_evs
                ],
            })

        pending = await self.session_store.get_pending_execution(principal_id, session_id)
        pending_info = None
        if pending is not None:
            pending_info = {
                "token": pending.token,
                "turn_id": pending.turn_id,
                "tool_name": pending.tool_name,
                "tool_call_id": pending.tool_call_id,
                "status": "awaiting_browser",
            }

        return {
            "session_id": session_id,
            "principal_id": principal_id,
            "next_turn_number": session.next_turn_number,
            "messages": messages,
            "turns": turns,
            "pending_execution": pending_info,
        }

    async def delete_session(
        self,
        *,
        principal_id: str,
        session_id: str,
    ) -> bool:
        """Delete session and cancel pending browser executions."""
        return await self.session_store.delete_session(principal_id, session_id)
