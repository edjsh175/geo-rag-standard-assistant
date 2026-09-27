"""Single publication authority for user-visible Agent answers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from app.services.agent.answer_generator import GeneratedAnswer
from app.services.agent.contracts import MapAction


class PublicationDecision(str, Enum):
    PUBLISH = "PUBLISH"
    SAFE_FALLBACK = "SAFE_FALLBACK"
    CONTINUE = "CONTINUE"


class PublicationStateError(ValueError):
    pass


_PUBLISHABLE_STATES = {"published", "clarification", "clarification_required", "limitation"}
_CONTINUATION_STATES = {"tool_execution_required"}
_BLOCKED_STATES = {
    "resource_fuse",
    "model_output_invalid",
    "retrieval_unavailable",
    "review_failed",
    "review_rejected",
    "insufficient_evidence",
    "review_budget_exceeded",
    "cancelled",
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

    @classmethod
    def continuation(
        cls,
        *,
        publication_state: str = "tool_execution_required",
        map_action: MapAction | None = None,
        pending_tool_call_id: str | None = None,
        continuation_token: str | None = None,
    ) -> "PublishedResult":
        state = str(publication_state).strip()
        if state not in _CONTINUATION_STATES:
            raise PublicationStateError(f"state is not a continuation state: {state}")
        return cls(
            publication_state=state,
            decision=PublicationDecision.CONTINUE,
            answer=None,
            fallback_text=None,
            map_action=map_action,
        )


@dataclass(frozen=True, slots=True)
class DirectAnswerResult:
    answer: GeneratedAnswer
    user_visible: bool = True
    logical_turn_completed: bool = True

    def __post_init__(self) -> None:
        if self.answer.kind != "direct_answer" or not self.answer.answer.strip():
            raise PublicationStateError("DirectAnswerResult requires a direct_answer draft")

    @property
    def text(self) -> str:
        return self.answer.answer


@dataclass(frozen=True, slots=True)
class KnowledgeAnswerResult:
    answer: GeneratedAnswer
    user_visible: bool = True
    logical_turn_completed: bool = True

    def __post_init__(self) -> None:
        if self.answer.kind != "knowledge_answer" or not self.answer.answer.strip():
            raise PublicationStateError("KnowledgeAnswerResult requires a knowledge_answer draft")

    @property
    def text(self) -> str:
        return self.answer.answer

    @property
    def citations(self) -> tuple[str, ...]:
        return self.answer.citations


@dataclass(frozen=True, slots=True)
class ClarificationRequired:
    question: str
    user_visible: bool = True
    logical_turn_completed: bool = False


@dataclass(frozen=True, slots=True)
class BrowserToolExecutionRequired:
    tool_call_id: str
    tool_name: str
    continuation_token: str
    map_action: MapAction
    user_visible: bool = False
    logical_turn_completed: bool = False


@dataclass(frozen=True, slots=True)
class SafeLimitation:
    message: str
    user_visible: bool = True
    logical_turn_completed: bool = True


@dataclass(frozen=True, slots=True)
class NoSafeAnswer:
    reason: str
    message: str
    user_visible: bool = True
    logical_turn_completed: bool = True


AgentPublicationResult: TypeAlias = (
    DirectAnswerResult
    | KnowledgeAnswerResult
    | ClarificationRequired
    | BrowserToolExecutionRequired
    | SafeLimitation
    | NoSafeAnswer
)

