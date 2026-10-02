"""Session/pending-execution loading boundary for AgentRuntime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.agent.session import AgentSession, PendingBrowserExecution


@dataclass(frozen=True, slots=True)
class LoadedAgentSession:
    session: AgentSession
    pending_execution: PendingBrowserExecution | None


class SessionLoader:
    """Load one authoritative session and its durable pending execution.

    This component deliberately performs no semantic routing and no mutation.
    It only resolves the persistence boundary into the state AgentRuntime needs
    to begin a request.
    """

    def __init__(self, session_store: Any) -> None:
        self.session_store = session_store

    async def load(self, *, principal_id: str, session_id: str) -> LoadedAgentSession:
        if hasattr(self.session_store, "get_or_create_session"):
            session = await self.session_store.get_or_create_session(
                principal_id,
                session_id,
            )
        else:
            # Compatibility for the legacy synchronous test session store only.
            session = self.session_store.get_or_create(principal_id, session_id)

        pending = session.pending_browser_execution
        if pending is None and hasattr(self.session_store, "get_pending_execution"):
            pending = await self.session_store.get_pending_execution(
                principal_id,
                session_id,
            )
            if pending is not None:
                session.pending_browser_execution = pending

        return LoadedAgentSession(session=session, pending_execution=pending)


__all__ = ["LoadedAgentSession", "SessionLoader"]
