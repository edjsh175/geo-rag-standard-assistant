"""Runtime-authoritative entity identity resolution facts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EntityCandidateRef:
    entity_ref: str
    display_name: str

    def __post_init__(self) -> None:
        if not self.entity_ref.strip():
            raise ValueError("entity_ref must not be empty")
        if not self.display_name.strip():
            raise ValueError("display_name must not be empty")


@dataclass(frozen=True, slots=True)
class IdentityResolution:
    """Server-owned entity resolution state for the active session."""

    status: str
    candidate_refs: tuple[EntityCandidateRef, ...] = ()
    clarification_snapshot_id: str | None = None
    confirmed_entity_ref: str | None = None

    @property
    def requires_confirmation(self) -> bool:
        return self.status == "ambiguous" and len(self.candidate_refs) >= 2

    def clarification_text(self) -> str:
        if not self.requires_confirmation:
            raise ValueError("identity resolution does not require confirmation")
        labels = "、".join(candidate.display_name for candidate in self.candidate_refs)
        return f"请确认您指的是：{labels}。"
