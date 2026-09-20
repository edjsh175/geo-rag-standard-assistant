"""Session ownership for conversation events and Evidence Memory."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.agent.evidence import EvidenceLedger
from app.services.agent.events import AgentEvent


@dataclass(slots=True)
class AgentSession:
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

    def __init__(self) -> None:
        self._sessions: dict[str, AgentSession] = {}

    def get_or_create(self, session_id: str) -> AgentSession:
        normalized = session_id.strip()
        if not normalized:
            raise ValueError("session_id must not be empty")
        session = self._sessions.get(normalized)
        if session is None:
            session = AgentSession(
                session_id=normalized,
                evidence_ledger=EvidenceLedger(session_id=normalized),
            )
            self._sessions[normalized] = session
        return session

    def get(self, session_id: str) -> AgentSession | None:
        return self._sessions.get(session_id)
