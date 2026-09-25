"""Compatibility context projection used by the current AgentRuntime.

The context package is the canonical import boundary.  This builder preserves
the existing Runtime contract while the richer ContextEngine is adopted by
callers stage by stage.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.services.agent.events import AgentEvent


@dataclass(frozen=True, slots=True)
class AgentContext:
    current_question: str
    summary: str
    working_evidence: tuple[Mapping[str, Any], ...]


class AgentContextBuilder:
    """Project conversation facts under a size budget, independent of turn count."""

    def __init__(self, *, max_characters: int = 6000) -> None:
        if max_characters <= 0:
            raise ValueError("max_characters must be positive")
        self.max_characters = max_characters

    def build(
        self,
        *,
        question: str,
        prior_events: Sequence[AgentEvent],
        working_evidence: Sequence[Mapping[str, Any]],
    ) -> AgentContext:
        lines: list[str] = []
        for event in prior_events:
            if event.event_type not in {"user_message", "assistant_message"}:
                continue
            text = event.payload.get("text")
            if isinstance(text, str) and text.strip():
                role = "user" if event.event_type == "user_message" else "assistant"
                lines.append(f"{role}: {text.strip()}")

        summary = self._take_recent_within_budget(lines)
        return AgentContext(
            current_question=question,
            summary=summary,
            working_evidence=tuple(working_evidence),
        )

    def _take_recent_within_budget(self, lines: Sequence[str]) -> str:
        selected: list[str] = []
        used = 0
        for line in reversed(lines):
            extra = len(line) + (1 if selected else 0)
            if selected and used + extra > self.max_characters:
                break
            if not selected and len(line) > self.max_characters:
                selected.append(line[-self.max_characters :])
                break
            selected.append(line)
            used += extra
        return "\n".join(reversed(selected))
