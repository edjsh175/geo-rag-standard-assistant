"""Single publication authority for user-visible Agent answers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.services.agent.contracts import MapAction


class PublicationDecision(str, Enum):
    PUBLISH = "PUBLISH"
    SAFE_FALLBACK = "SAFE_FALLBACK"


class PublicationStateError(ValueError):
    pass


_PUBLISHABLE_STATES = {"published", "clarification", "limitation"}
_BLOCKED_STATES = {
    "resource_fuse",
    "model_output_invalid",
    "retrieval_unavailable",
    "review_failed",
    "review_rejected",
    "insufficient_evidence",
}


@dataclass(frozen=True, slots=True)
class PublishedResult:
    publication_state: str
    decision: PublicationDecision
    answer: str | None
    fallback_text: str | None = None
    map_action: MapAction | None = None

    @property
    def visible_text(self) -> str:
        text = self.answer if self.decision is PublicationDecision.PUBLISH else self.fallback_text
        return str(text or "")

    @classmethod
    def publish(
        cls,
        *,
        text: str,
        publication_state: str,
        map_action: MapAction | None,
    ) -> "PublishedResult":
        state = str(publication_state).strip()
        if state not in _PUBLISHABLE_STATES:
            raise PublicationStateError(f"state is not publishable: {state}")
        if not text.strip():
            raise PublicationStateError("published text must not be empty")
        return cls(
            publication_state=state,
            decision=PublicationDecision.PUBLISH,
            answer=text.strip(),
            map_action=map_action,
        )

    @classmethod
    def safe_fallback(
        cls,
        *,
        publication_state: str,
        fallback_text: str,
    ) -> "PublishedResult":
        state = str(publication_state).strip()
        if state not in _BLOCKED_STATES:
            raise PublicationStateError(f"state is not a safe-fallback state: {state}")
        if not fallback_text.strip():
            raise PublicationStateError("fallback text must not be empty")
        return cls(
            publication_state=state,
            decision=PublicationDecision.SAFE_FALLBACK,
            answer=None,
            fallback_text=fallback_text.strip(),
            map_action=None,
        )
