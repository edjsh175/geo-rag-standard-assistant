"""Role-specific context projections for Controller, Retrieval, AnswerGenerator, and Reviewer."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


def _empty_mapping() -> Mapping[str, Any]:
    return MappingProxyType({})


@dataclass(frozen=True)
class ControllerContextProjection:
    """Projection tailored strictly for Main Controller decisions."""

    user_question: str
    conversation_text: str
    working_evidence: tuple[Mapping[str, Any], ...] = ()
    evidence_catalog: tuple[Mapping[str, Any], ...] = ()
    runtime_facts: Mapping[str, Any] = field(default_factory=_empty_mapping)
    map_context: Mapping[str, Any] | None = None
    tool_contracts_text: str = ""
    tool_names: str = ""
    available_capabilities: tuple[str, ...] = ()
    available_control_actions: tuple[str, ...] = ()
    estimated_tokens: int = 0

    def sections(self) -> dict[str, Any]:
        return {
            "user_question": self.user_question,
            "conversation": self.conversation_text,
            "working_evidence": list(self.working_evidence),
            "evidence_catalog": list(self.evidence_catalog),
            "runtime_facts": dict(self.runtime_facts or {}),
            "map_context": dict(self.map_context or {}),
            "tool_contracts": self.tool_contracts_text,
            "tool_names": self.tool_names,
            "available_capabilities": list(self.available_capabilities),
            "available_control_actions": list(self.available_control_actions),
        }


@dataclass(frozen=True)
class RetrievalContextProjection:
    """Projection tailored strictly for Query Retrieval and Search Planning."""

    resolved_query: str
    user_question: str = ""
    search_focus: str = ""
    spatial_constraints: Mapping[str, Any] | None = None
    semantic_context: str = ""
    estimated_tokens: int = 0

    def sections(self) -> dict[str, Any]:
        return {
            "resolved_query": self.resolved_query,
            "user_question": self.user_question,
            "search_focus": self.search_focus,
            "spatial_constraints": dict(self.spatial_constraints or {}),
            "semantic_context": self.semantic_context,
        }


@dataclass(frozen=True)
class AnswerContextProjection:
    """Projection tailored strictly for AnswerGenerator synthesis."""

    user_question: str
    conversation_summary: str = ""
    citable_evidence: tuple[Mapping[str, Any], ...] = ()
    resolved_goal: str = ""
    answer_contract: Mapping[str, Any] | None = None
    map_context: Mapping[str, Any] | None = None
    estimated_tokens: int = 0

    def sections(self) -> dict[str, Any]:
        return {
            "user_question": self.user_question,
            "conversation_summary": self.conversation_summary,
            "citable_evidence": list(self.citable_evidence),
            "resolved_goal": self.resolved_goal,
            "answer_contract": dict(self.answer_contract or {}),
            "map_context": dict(self.map_context or {}),
        }


@dataclass(frozen=True)
class ReviewerContextProjection:
    """Projection tailored strictly for Reviewer verification."""

    user_question: str
    candidate_answer: str = ""
    draft_answer: str = ""  # compatibility alias for candidate_answer
    citable_evidence: tuple[Mapping[str, Any], ...] = ()
    claim_contract: Mapping[str, Any] | None = None
    estimated_tokens: int = 0

    def __post_init__(self):
        # Synchronize candidate_answer and draft_answer
        if not self.candidate_answer and self.draft_answer:
            object.__setattr__(self, "candidate_answer", self.draft_answer)
        elif not self.draft_answer and self.candidate_answer:
            object.__setattr__(self, "draft_answer", self.candidate_answer)

    def sections(self) -> dict[str, Any]:
        return {
            "user_question": self.user_question,
            "candidate_answer": self.candidate_answer or self.draft_answer,
            "citable_evidence": list(self.citable_evidence),
            "claim_contract": dict(self.claim_contract or {}),
        }
