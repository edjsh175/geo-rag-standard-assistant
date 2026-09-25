"""Data models for GeoAI Agent context, event sourcing, evidence, and persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


@dataclass(slots=True)
class AgentSessionRecord:
    id: str
    principal_id: str
    session_id: str
    workspace_id: str = "default"
    status: str = "active"
    next_turn_number: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True, slots=True)
class AgentEventRecord:
    event_id: str
    principal_id: str
    session_id: str
    turn_id: str
    sequence: int
    event_type: str
    trace_id: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True, slots=True)
class AgentEvidenceRecord:
    id: str
    principal_id: str
    session_id: str
    evidence_id: str
    citation_id: str
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
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True, slots=True)
class ContextSnapshotRecord:
    snapshot_id: str
    principal_id: str
    session_id: str
    turn_id: str
    stage: str
    projection_hash: str
    snapshot_payload: Mapping[str, Any]
    token_usage_estimate: int = 0
    source_event_ids: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class PendingBrowserExecutionRecord:
    token: str
    principal_id: str
    session_id: str
    question: str
    turn_id: str
    trace_id: str
    tool_call_id: str
    tool_name: str
    observations: tuple[Any, ...] = ()
    request_context: Mapping[str, Any] = field(default_factory=dict)
    reviewer_enabled: bool = False
    thinking: bool = False
    max_steps: int = 6
    steps_used: int = 0
    max_elapsed_seconds: float = 60.0
    retrieval_constraints: Any = None
    main_model_name: str | None = None
    status: str = "awaiting_browser"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
