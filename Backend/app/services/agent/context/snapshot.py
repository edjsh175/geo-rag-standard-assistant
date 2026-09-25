"""Auditable ContextSnapshot for GeoAI Agent decisions and generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping
import uuid

from app.models.agent_context import ContextSnapshotRecord


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ContextSnapshotSection:
    name: str
    content_hash: str


@dataclass(frozen=True)
class ContextSnapshot:
    """Immutable audit snapshot of context projection seen by an LLM stage."""

    snapshot_id: str
    stage: str
    session_id: str
    turn_id: str
    sections: tuple[ContextSnapshotSection, ...]
    source_event_ids: tuple[str, ...]
    frame_hash: str
    projection_hash: str
    token_usage_estimate: int
    created_at: str

    @classmethod
    def create(
        cls,
        *,
        stage: str,
        session_id: str,
        turn_id: str,
        frame_payload: Mapping[str, Any],
        projection_sections: Mapping[str, Any],
        source_event_ids: tuple[str, ...] | list[str] = (),
        token_usage_estimate: int = 0,
    ) -> "ContextSnapshot":
        section_rows = tuple(
            ContextSnapshotSection(name=str(name), content_hash=_sha256(content))
            for name, content in projection_sections.items()
        )
        frame_hash = _sha256(dict(frame_payload))
        projection_hash = _sha256(dict(projection_sections))
        now_iso = datetime.now(timezone.utc).isoformat()
        snapshot_id = f"snap-{uuid.uuid4().hex[:16]}"

        return cls(
            snapshot_id=snapshot_id,
            stage=stage,
            session_id=session_id,
            turn_id=turn_id,
            sections=section_rows,
            source_event_ids=tuple(source_event_ids),
            frame_hash=frame_hash,
            projection_hash=projection_hash,
            token_usage_estimate=max(0, int(token_usage_estimate)),
            created_at=now_iso,
        )

    def to_record(self, principal_id: str) -> ContextSnapshotRecord:
        return ContextSnapshotRecord(
            snapshot_id=self.snapshot_id,
            principal_id=principal_id,
            session_id=self.session_id,
            turn_id=self.turn_id,
            stage=self.stage,
            projection_hash=self.projection_hash,
            snapshot_payload={
                "sections": [{"name": s.name, "hash": s.content_hash} for s in self.sections],
                "frame_hash": self.frame_hash,
            },
            token_usage_estimate=self.token_usage_estimate,
            source_event_ids=self.source_event_ids,
            created_at=datetime.fromisoformat(self.created_at),
        )
