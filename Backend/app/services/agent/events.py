"""Observable Agent runtime events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class AgentEvent:
    event_type: str
    session_id: str
    turn_id: str
    trace_id: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)
    event_id: str = ""
    sequence: int = 0
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self) -> None:
        if not self.event_id:
            from uuid import uuid4
            object.__setattr__(self, "event_id", uuid4().hex)

