"""Value objects shared by the GeoRAG Agent application core."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


def freeze_json(value: Any) -> Any:
    """Recursively freeze JSON-like values without changing their information."""
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    evidence_id: str
    citation_id: str
    session_id: str
    first_turn_id: str
    chunk_id: str
    document_id: str | None
    text: str
    title: str
    score: float
    metadata: Mapping[str, Any]
    source: str
    match_type: str
    content_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", freeze_json(self.metadata))


@dataclass(frozen=True, slots=True)
class FrozenEvidenceSnapshot:
    snapshot_id: str
    session_id: str
    turn_id: str
    items: tuple[EvidenceItem, ...]

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(item.evidence_id for item in self.items)
