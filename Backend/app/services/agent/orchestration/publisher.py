"""Single persistence boundary for terminal user-visible Agent publications."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from app.services.agent.events import AgentEvent
from app.services.agent.session import AgentSession


EventListener = Callable[[AgentEvent], None]


class Publisher:
    """Persist one terminal publication without owning semantic decisions.

    The caller decides *what* may be published.  This boundary only makes the
    publication durable and keeps the historical event semantics stable:

    - ``publication_completed`` belongs to both session and turn projections;
    - ``assistant_message`` belongs to durable session history, but is not
      duplicated into the current turn event tuple;
    - session/evidence persistence happens after the user-visible publication.
    """

    def __init__(self, session_store: Any) -> None:
        self.session_store = session_store

    async def publish(
        self,
        *,
        principal_id: str,
        session: AgentSession,
        turn_events: list[AgentEvent],
        turn_id: str,
        trace_id: str,
        publication_state: str,
        text: str,
        payload: Mapping[str, Any] | None = None,
        event_listener: EventListener | None = None,
        persist_evidence: bool = False,
    ) -> None:
        visible_text = str(text or "").strip()
        if not visible_text:
            raise ValueError("terminal publication text must not be empty")

        publication_event = AgentEvent(
            event_type="publication_completed",
            session_id=session.session_id,
            turn_id=turn_id,
            trace_id=trace_id,
            payload={"state": publication_state, **dict(payload or {})},
        )
        persisted_publication = await self._persist_event(
            principal_id,
            publication_event,
        )
        session.events.append(persisted_publication)
        turn_events.append(persisted_publication)
        if event_listener is not None:
            event_listener(persisted_publication)

        assistant_event = AgentEvent(
            event_type="assistant_message",
            session_id=session.session_id,
            turn_id=turn_id,
            trace_id=trace_id,
            payload={"text": visible_text},
        )
        persisted_assistant = await self._persist_event(
            principal_id,
            assistant_event,
        )
        session.events.append(persisted_assistant)

        if hasattr(self.session_store, "save_session"):
            await self.session_store.save_session(session)
        if persist_evidence and hasattr(self.session_store, "save_evidence_items"):
            await self.session_store.save_evidence_items(
                principal_id,
                session.session_id,
                session.evidence_ledger.export_items(),
            )

    async def _persist_event(
        self,
        principal_id: str,
        event: AgentEvent,
    ) -> AgentEvent:
        if hasattr(self.session_store, "append_event"):
            return await self.session_store.append_event(principal_id, event)
        return event


__all__ = ["Publisher"]
