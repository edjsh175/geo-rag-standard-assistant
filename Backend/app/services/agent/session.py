"""Session ownership for conversation events and Evidence Memory."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.agent.evidence import EvidenceLedger
from app.services.agent.events import AgentEvent


@dataclass(slots=True)
class AgentSession:
    principal_id: str
    session_id: str
    evidence_ledger: EvidenceLedger
    events: list[AgentEvent] = field(default_factory=list)
    next_turn_number: int = 1

    def new_turn_id(self) -> str:
        turn_id = f"turn-{self.next_turn_number}"
        self.next_turn_number += 1
        return turn_id


class InMemoryAgentSessionStore:
    """Process-local session store; persistence is intentionally a later concern."""

    def __init__(self, *, max_sessions: int = 1000) -> None:
        if max_sessions <= 0:
            raise ValueError("max_sessions must be positive")
        self.max_sessions = max_sessions
        self._sessions: dict[tuple[str, str], AgentSession] = {}

    def get_or_create(self, principal_id: str, session_id: str) -> AgentSession:
        principal = principal_id.strip()
        if not principal:
            raise ValueError("principal_id must not be empty")
        normalized = session_id.strip()
        if not normalized:
            raise ValueError("session_id must not be empty")
        key = (principal, normalized)
        session = self._sessions.get(key)
        if session is None:
            if len(self._sessions) >= self.max_sessions:
                oldest_key = next(iter(self._sessions))
                self._sessions.pop(oldest_key, None)
            session = AgentSession(
                principal_id=principal,
                session_id=normalized,
                evidence_ledger=EvidenceLedger(session_id=normalized),
            )
            self._sessions[key] = session
        return session

    def get(self, principal_id: str, session_id: str) -> AgentSession | None:
        return self._sessions.get((principal_id, session_id))
