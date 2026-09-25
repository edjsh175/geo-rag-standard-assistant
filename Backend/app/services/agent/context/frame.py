"""Structured immutable ContextFrame for GeoAI Agent runtime.

ContextFrame holds the canonical semantic state for one agent decision or generation cycle,
including conversation, spatial map state, evidence, observations, and tool capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(_freeze(v) for v in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_thaw(v) for v in value]
    return value


from app.services.agent.context.projection import (
    AnswerContextProjection,
    ControllerContextProjection,
    RetrievalContextProjection,
    ReviewerContextProjection,
)


def _empty_mapping() -> Mapping[str, Any]:
    return MappingProxyType({})


@dataclass(frozen=True)
class ContextFrame:
    """Canonical frozen context frame for GeoAI Agent decisions and generation.

    This object is internal to the runtime. Model callers must only see role-specific
    projections (Controller, Answer, Reviewer).
    """

    session: Mapping[str, Any] = field(default_factory=_empty_mapping)
    user_question: str = ""
    spatial: Mapping[str, Any] = field(default_factory=_empty_mapping)
    conversation: tuple[Mapping[str, Any], ...] = ()
    evidence_memory: tuple[Mapping[str, Any], ...] = ()
    working_evidence: tuple[Mapping[str, Any], ...] = ()
    evidence_catalog: tuple[Mapping[str, Any], ...] = ()
    runtime_facts: Mapping[str, Any] = field(default_factory=_empty_mapping)
    observations: tuple[Mapping[str, Any], ...] = ()
    runtime_capabilities: Mapping[str, Any] = field(default_factory=_empty_mapping)
    source_event_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=_empty_mapping)

    @classmethod
    def create(
        cls,
        *,
        session: Mapping[str, Any] | None = None,
        user_question: str = "",
        spatial: Mapping[str, Any] | None = None,
        conversation: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] | None = None,
        evidence_memory: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] | None = None,
        working_evidence: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] | None = None,
        evidence_catalog: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] | None = None,
        runtime_facts: Mapping[str, Any] | None = None,
        observations: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] | None = None,
        runtime_capabilities: Mapping[str, Any] | None = None,
        source_event_ids: list[str] | tuple[str, ...] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "ContextFrame":
        clean_event_ids = tuple(
            dict.fromkeys(str(v).strip() for v in (source_event_ids or ()) if str(v).strip())
        )
        return cls(
            session=_freeze(session or {}),
            user_question=str(user_question or "").strip(),
            spatial=_freeze(spatial or {}),
            conversation=tuple(_freeze(v) for v in (conversation or ())),
            evidence_memory=tuple(_freeze(v) for v in (evidence_memory or ())),
            working_evidence=tuple(_freeze(v) for v in (working_evidence or ())),
            evidence_catalog=tuple(_freeze(v) for v in (evidence_catalog or ())),
            runtime_facts=_freeze(runtime_facts or {}),
            observations=tuple(_freeze(v) for v in (observations or ())),
            runtime_capabilities=_freeze(runtime_capabilities or {}),
            source_event_ids=clean_event_ids,
            metadata=_freeze(metadata or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session": _thaw(self.session),
            "user_question": self.user_question,
            "spatial": _thaw(self.spatial),
            "conversation": [_thaw(v) for v in self.conversation],
            "evidence_memory": [_thaw(v) for v in self.evidence_memory],
            "working_evidence": [_thaw(v) for v in self.working_evidence],
            "evidence_catalog": [_thaw(v) for v in self.evidence_catalog],
            "runtime_facts": _thaw(self.runtime_facts),
            "observations": [_thaw(v) for v in self.observations],
            "runtime_capabilities": _thaw(self.runtime_capabilities),
            "source_event_ids": list(self.source_event_ids),
            "metadata": _thaw(self.metadata),
        }

    def for_controller(
        self,
        *,
        tool_contracts_text: str = "",
        tool_names: str = "",
        available_capabilities: tuple[str, ...] = (),
        available_control_actions: tuple[str, ...] = (),
    ) -> ControllerContextProjection:
        """Produce role projection for Main Controller."""
        conv_text = "\n".join(
            f"{msg.get('role', 'user')}: {msg.get('text', '')}"
            for msg in self.conversation
            if msg.get("text")
        )
        return ControllerContextProjection(
            user_question=self.user_question,
            conversation_text=conv_text,
            working_evidence=self.working_evidence,
            evidence_catalog=self.evidence_catalog or self.working_evidence,
            runtime_facts=self.runtime_facts,
            map_context=self.spatial if self.spatial else None,
            tool_contracts_text=tool_contracts_text,
            tool_names=tool_names,
            available_capabilities=available_capabilities,
            available_control_actions=available_control_actions,
        )

    def for_retrieval(
        self,
        *,
        resolved_query: str = "",
        search_focus: str = "",
    ) -> RetrievalContextProjection:
        """Produce role projection for Retrieval and Search Planning."""
        return RetrievalContextProjection(
            resolved_query=resolved_query or self.user_question,
            user_question=self.user_question,
            search_focus=search_focus,
            spatial_constraints=self.spatial if self.spatial else None,
            semantic_context=str(self.runtime_facts.get("dialogue_focus") or ""),
        )

    def for_answer(
        self,
        *,
        resolved_goal: str = "",
        answer_contract: Mapping[str, Any] | None = None,
    ) -> AnswerContextProjection:
        """Produce role projection for AnswerGenerator."""
        conv_text = "\n".join(
            f"{msg.get('role', 'user')}: {msg.get('text', '')}"
            for msg in self.conversation
            if msg.get("text")
        )
        return AnswerContextProjection(
            user_question=self.user_question,
            conversation_summary=conv_text,
            citable_evidence=self.working_evidence,
            resolved_goal=resolved_goal or self.user_question,
            answer_contract=answer_contract,
            map_context=self.spatial if self.spatial else None,
        )

    def for_reviewer(
        self,
        *,
        candidate_answer: str = "",
        claim_contract: Mapping[str, Any] | None = None,
    ) -> ReviewerContextProjection:
        """Produce role projection for Grounding Reviewer."""
        return ReviewerContextProjection(
            user_question=self.user_question,
            candidate_answer=candidate_answer,
            citable_evidence=self.working_evidence,
            claim_contract=claim_contract,
        )
