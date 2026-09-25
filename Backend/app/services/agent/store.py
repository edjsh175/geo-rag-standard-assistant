"""Agent context, event sourcing, and session persistence store.

Provides abstract AgentStore, InMemoryAgentStore for unit testing, and
PostgresAgentStore for production PostgreSQL storage.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Any, Mapping, Sequence

from sqlalchemy import text

from app.core.database import db_manager
from app.models.agent_context import ContextSnapshotRecord
from app.services.agent.contracts import EvidenceItem
from app.services.agent.events import AgentEvent
from app.services.agent.evidence import EvidenceLedger
from app.services.agent.session import AgentSession, PendingBrowserExecution

logger = logging.getLogger(__name__)


def _json_dumps(val: Any) -> str:
    return json.dumps(val, ensure_ascii=False, default=str, sort_keys=True)


def _json_loads(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return val


class AgentStore(ABC):
    """Abstract persistence contract for Agent sessions, events, evidence, and snapshots."""

    @abstractmethod
    async def get_or_create_session(
        self,
        principal_id: str,
        session_id: str,
        workspace_id: str = "default",
    ) -> AgentSession:
        raise NotImplementedError

    @abstractmethod
    async def get_session(
        self,
        principal_id: str,
        session_id: str,
    ) -> AgentSession | None:
        raise NotImplementedError

    @abstractmethod
    async def save_session(self, session: AgentSession) -> None:
        raise NotImplementedError

    @abstractmethod
    async def append_event(
        self,
        principal_id: str,
        event: AgentEvent,
    ) -> AgentEvent:
        raise NotImplementedError

    @abstractmethod
    async def list_events(
        self,
        principal_id: str,
        session_id: str,
        from_sequence: int = 0,
    ) -> list[AgentEvent]:
        raise NotImplementedError

    @abstractmethod
    async def save_evidence_items(
        self,
        principal_id: str,
        session_id: str,
        items: Sequence[EvidenceItem],
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    async def list_evidence_items(
        self,
        principal_id: str,
        session_id: str,
        active_only: bool = True,
    ) -> list[EvidenceItem]:
        raise NotImplementedError

    @abstractmethod
    async def save_snapshot(self, record: ContextSnapshotRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_latest_snapshot(
        self,
        principal_id: str,
        session_id: str,
        stage: str | None = None,
    ) -> ContextSnapshotRecord | None:
        raise NotImplementedError

    @abstractmethod
    async def save_pending_execution(
        self,
        principal_id: str,
        pending: PendingBrowserExecution,
        ttl_seconds: float = 3600.0,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_pending_execution(
        self,
        principal_id: str,
        session_id: str,
    ) -> PendingBrowserExecution | None:
        raise NotImplementedError

    @abstractmethod
    async def clear_pending_execution(
        self,
        principal_id: str,
        session_id: str,
    ) -> None:
        raise NotImplementedError


class InMemoryAgentStore(AgentStore):
    """In-memory agent store implementation for testing and development."""

    def __init__(self, *, max_sessions: int = 1000) -> None:
        if max_sessions <= 0:
            raise ValueError("max_sessions must be positive")
        self.max_sessions = max_sessions
        self._lock = asyncio.Lock()
        self._sessions: dict[tuple[str, str], AgentSession] = {}
        self._events: dict[tuple[str, str], list[AgentEvent]] = {}
        self._evidence: dict[tuple[str, str], dict[str, EvidenceItem]] = {}
        self._snapshots: dict[tuple[str, str], list[ContextSnapshotRecord]] = {}
        self._pending: dict[tuple[str, str], tuple[PendingBrowserExecution, datetime]] = {}

    async def get_or_create_session(
        self,
        principal_id: str,
        session_id: str,
        workspace_id: str = "default",
    ) -> AgentSession:
        async with self._lock:
            key = (principal_id.strip(), session_id.strip())
            session = self._sessions.get(key)
            if session is None:
                if len(self._sessions) >= self.max_sessions:
                    oldest_key = next(iter(self._sessions))
                    self._sessions.pop(oldest_key, None)
                    self._events.pop(oldest_key, None)
                    self._evidence.pop(oldest_key, None)
                    self._snapshots.pop(oldest_key, None)
                    self._pending.pop(oldest_key, None)
                ledger = EvidenceLedger(session_id=key[1])
                session = AgentSession(
                    principal_id=key[0],
                    session_id=key[1],
                    evidence_ledger=ledger,
                )
                self._sessions[key] = session
                self._events[key] = []
                self._evidence[key] = {}
                self._snapshots[key] = []
            return session

    async def get_session(
        self,
        principal_id: str,
        session_id: str,
    ) -> AgentSession | None:
        async with self._lock:
            return self._sessions.get((principal_id.strip(), session_id.strip()))

    async def save_session(self, session: AgentSession) -> None:
        async with self._lock:
            key = (session.principal_id.strip(), session.session_id.strip())
            self._sessions[key] = session
            if session.events:
                event_list = self._events.setdefault(key, [])
                for ev in session.events:
                    if ev not in event_list:
                        seq = len(event_list) + 1
                        if ev.sequence != seq:
                            ev = AgentEvent(
                                event_type=ev.event_type,
                                session_id=ev.session_id,
                                turn_id=ev.turn_id,
                                trace_id=ev.trace_id,
                                payload=ev.payload,
                                event_id=ev.event_id,
                                sequence=seq,
                                created_at=ev.created_at,
                            )
                        event_list.append(ev)
            items = session.evidence_ledger.export_items()
            if items:
                ev_dict = self._evidence.setdefault(key, {})
                for it in items:
                    ev_dict[it.evidence_id] = it
            if session.pending_browser_execution:
                expires_at = datetime.now(timezone.utc) + timedelta(seconds=3600)
                self._pending[key] = (session.pending_browser_execution, expires_at)
            else:
                self._pending.pop(key, None)


    async def append_event(
        self,
        principal_id: str,
        event: AgentEvent,
    ) -> AgentEvent:
        async with self._lock:
            key = (principal_id.strip(), event.session_id.strip())
            event_list = self._events.setdefault(key, [])
            sequence = len(event_list) + 1
            if event.sequence != sequence:
                persisted_event = AgentEvent(
                    event_type=event.event_type,
                    session_id=event.session_id,
                    turn_id=event.turn_id,
                    trace_id=event.trace_id,
                    payload=event.payload,
                    event_id=event.event_id,
                    sequence=sequence,
                    created_at=event.created_at,
                )
            else:
                persisted_event = event
            event_list.append(persisted_event)
            return persisted_event

    async def list_events(
        self,
        principal_id: str,
        session_id: str,
        from_sequence: int = 0,
    ) -> list[AgentEvent]:
        async with self._lock:
            key = (principal_id.strip(), session_id.strip())
            events = self._events.get(key, [])
            return [ev for ev in events if ev.sequence >= from_sequence]

    async def save_evidence_items(
        self,
        principal_id: str,
        session_id: str,
        items: Sequence[EvidenceItem],
    ) -> None:
        async with self._lock:
            key = (principal_id.strip(), session_id.strip())
            ev_dict = self._evidence.setdefault(key, {})
            for item in items:
                ev_dict[item.evidence_id] = item

    async def list_evidence_items(
        self,
        principal_id: str,
        session_id: str,
        active_only: bool = True,
    ) -> list[EvidenceItem]:
        async with self._lock:
            key = (principal_id.strip(), session_id.strip())
            ev_dict = self._evidence.get(key, {})
            return list(ev_dict.values())

    async def save_snapshot(self, record: ContextSnapshotRecord) -> None:
        async with self._lock:
            key = (record.principal_id.strip(), record.session_id.strip())
            self._snapshots.setdefault(key, []).append(record)

    async def get_latest_snapshot(
        self,
        principal_id: str,
        session_id: str,
        stage: str | None = None,
    ) -> ContextSnapshotRecord | None:
        async with self._lock:
            key = (principal_id.strip(), session_id.strip())
            snapshots = self._snapshots.get(key, [])
            for sn in reversed(snapshots):
                if stage is None or sn.stage == stage:
                    return sn
            return None

    async def save_pending_execution(
        self,
        principal_id: str,
        pending: PendingBrowserExecution,
        ttl_seconds: float = 3600.0,
    ) -> None:
        async with self._lock:
            key = (principal_id.strip(), pending.turn_id.split("-")[0] if hasattr(pending, "session_id") else principal_id)
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
            # Find key by token or principal
            for sess_key, sess in self._sessions.items():
                if sess_key[0] == principal_id and sess.pending_browser_execution and sess.pending_browser_execution.token == pending.token:
                    self._pending[sess_key] = (pending, expires_at)
                    return
            # fallback
            self._pending[(principal_id.strip(), pending.token)] = (pending, expires_at)

    async def get_pending_execution(
        self,
        principal_id: str,
        session_id: str,
    ) -> PendingBrowserExecution | None:
        async with self._lock:
            key = (principal_id.strip(), session_id.strip())
            val = self._pending.get(key)
            if not val:
                return None
            pending, expires_at = val
            if datetime.now(timezone.utc) > expires_at:
                self._pending.pop(key, None)
                return None
            return pending

    async def clear_pending_execution(
        self,
        principal_id: str,
        session_id: str,
    ) -> None:
        async with self._lock:
            key = (principal_id.strip(), session_id.strip())
            self._pending.pop(key, None)


class PostgresAgentStore(AgentStore):
    """PostgreSQL-backed production agent store with full event sourcing and snapshot audit."""

    def __init__(self, manager=None, fallback: AgentStore | None = None) -> None:
        self._manager = manager or db_manager
        self._fallback = fallback or InMemoryAgentStore()

    @property
    def _is_postgres_available(self) -> bool:
        return bool(self._manager and getattr(self._manager, "postgres_sessionmaker", None))

    async def get_or_create_session(
        self,
        principal_id: str,
        session_id: str,
        workspace_id: str = "default",
    ) -> AgentSession:
        if not self._is_postgres_available:
            return await self._fallback.get_or_create_session(principal_id, session_id, workspace_id)

        principal = principal_id.strip()
        normalized_sess = session_id.strip()
        record_id = f"{principal}:{normalized_sess}"

        async with self._manager.get_postgres_session() as session:
            select_sql = text(
                """
                SELECT id, principal_id, session_id, workspace_id, status, next_turn_number, metadata
                FROM geoai_agent_sessions
                WHERE principal_id = :principal_id AND session_id = :session_id
                LIMIT 1
                """
            )
            res = await session.execute(
                select_sql,
                {"principal_id": principal, "session_id": normalized_sess},
            )
            row = res.mappings().first()

            if not row:
                insert_sql = text(
                    """
                    INSERT INTO geoai_agent_sessions (
                        id, principal_id, session_id, workspace_id, status, next_turn_number, metadata
                    )
                    VALUES (:id, :principal_id, :session_id, :workspace_id, 'active', 1, '{}'::jsonb)
                    ON CONFLICT (principal_id, session_id) DO UPDATE SET updated_at = NOW()
                    RETURNING id, principal_id, session_id, workspace_id, status, next_turn_number, metadata
                    """
                )
                res = await session.execute(
                    insert_sql,
                    {
                        "id": record_id,
                        "principal_id": principal,
                        "session_id": normalized_sess,
                        "workspace_id": workspace_id,
                    },
                )
                row = res.mappings().first()

        next_turn = int(row.get("next_turn_number") or 1)
        ledger = EvidenceLedger(session_id=normalized_sess)

        # Restore evidence and events
        events = await self.list_events(principal, normalized_sess)
        ev_items = await self.list_evidence_items(principal, normalized_sess, active_only=True)
        if ev_items:
            ledger.restore_items(ev_items)

        pending = await self.get_pending_execution(principal, normalized_sess)

        return AgentSession(
            principal_id=principal,
            session_id=normalized_sess,
            evidence_ledger=ledger,
            events=events,
            next_turn_number=next_turn,
            pending_browser_execution=pending,
        )

    async def get_session(
        self,
        principal_id: str,
        session_id: str,
    ) -> AgentSession | None:
        if not self._is_postgres_available:
            return await self._fallback.get_session(principal_id, session_id)

        principal = principal_id.strip()
        normalized_sess = session_id.strip()

        async with self._manager.get_postgres_session() as session:
            select_sql = text(
                """
                SELECT id, principal_id, session_id, workspace_id, status, next_turn_number, metadata
                FROM geoai_agent_sessions
                WHERE principal_id = :principal_id AND session_id = :session_id
                LIMIT 1
                """
            )
            res = await session.execute(
                select_sql,
                {"principal_id": principal, "session_id": normalized_sess},
            )
            row = res.mappings().first()

        if not row:
            return None

        next_turn = int(row.get("next_turn_number") or 1)
        ledger = EvidenceLedger(session_id=normalized_sess)
        events = await self.list_events(principal, normalized_sess)
        ev_items = await self.list_evidence_items(principal, normalized_sess, active_only=True)
        if ev_items:
            ledger.restore_items(ev_items)
        pending = await self.get_pending_execution(principal, normalized_sess)

        return AgentSession(
            principal_id=principal,
            session_id=normalized_sess,
            evidence_ledger=ledger,
            events=events,
            next_turn_number=next_turn,
            pending_browser_execution=pending,
        )

    async def save_session(self, session: AgentSession) -> None:
        if not self._is_postgres_available:
            return await self._fallback.save_session(session)

        principal = session.principal_id.strip()
        normalized_sess = session.session_id.strip()
        record_id = f"{principal}:{normalized_sess}"

        async with self._manager.get_postgres_session() as db_session:
            upsert_sql = text(
                """
                INSERT INTO geoai_agent_sessions (
                    id, principal_id, session_id, next_turn_number, updated_at
                )
                VALUES (:id, :principal_id, :session_id, :next_turn_number, NOW())
                ON CONFLICT (principal_id, session_id) DO UPDATE SET
                    next_turn_number = EXCLUDED.next_turn_number,
                    updated_at = NOW()
                """
            )
            await db_session.execute(
                upsert_sql,
                {
                    "id": record_id,
                    "principal_id": principal,
                    "session_id": normalized_sess,
                    "next_turn_number": session.next_turn_number,
                },
            )

        if session.events:
            for ev in session.events:
                if ev.sequence == 0:
                    await self.append_event(principal, ev)
        items = session.evidence_ledger.export_items()
        if items:
            await self.save_evidence_items(principal, normalized_sess, items)

        if session.pending_browser_execution:
            await self.save_pending_execution(principal, session.pending_browser_execution)
        else:
            await self.clear_pending_execution(principal, normalized_sess)


    async def append_event(
        self,
        principal_id: str,
        event: AgentEvent,
    ) -> AgentEvent:
        if not self._is_postgres_available:
            return await self._fallback.append_event(principal_id, event)

        principal = principal_id.strip()
        session_id = event.session_id.strip()

        async with self._manager.get_postgres_session() as db_session:
            # Query max sequence
            seq_sql = text(
                """
                SELECT COALESCE(MAX(sequence), 0) + 1 AS next_seq
                FROM geoai_agent_events
                WHERE principal_id = :principal_id AND session_id = :session_id
                """
            )
            res = await db_session.execute(
                seq_sql,
                {"principal_id": principal, "session_id": session_id},
            )
            row = res.mappings().first()
            seq = int(row.get("next_seq") or 1)

            insert_sql = text(
                """
                INSERT INTO geoai_agent_events (
                    event_id, principal_id, session_id, turn_id, trace_id, sequence, event_type, payload, created_at
                )
                VALUES (
                    :event_id, :principal_id, :session_id, :turn_id, :trace_id, :sequence, :event_type, :payload::jsonb, :created_at
                )
                """
            )
            payload_json = _json_dumps(dict(event.payload))
            await db_session.execute(
                insert_sql,
                {
                    "event_id": event.event_id,
                    "principal_id": principal,
                    "session_id": session_id,
                    "turn_id": event.turn_id,
                    "trace_id": event.trace_id,
                    "sequence": seq,
                    "event_type": event.event_type,
                    "payload": payload_json,
                    "created_at": event.created_at,
                },
            )

        return AgentEvent(
            event_type=event.event_type,
            session_id=session_id,
            turn_id=event.turn_id,
            trace_id=event.trace_id,
            payload=event.payload,
            event_id=event.event_id,
            sequence=seq,
            created_at=event.created_at,
        )

    async def list_events(
        self,
        principal_id: str,
        session_id: str,
        from_sequence: int = 0,
    ) -> list[AgentEvent]:
        if not self._is_postgres_available:
            return await self._fallback.list_events(principal_id, session_id, from_sequence)

        async with self._manager.get_postgres_session() as db_session:
            sql = text(
                """
                SELECT event_id, session_id, turn_id, trace_id, sequence, event_type, payload, created_at
                FROM geoai_agent_events
                WHERE principal_id = :principal_id AND session_id = :session_id AND sequence >= :from_sequence
                ORDER BY sequence ASC
                """
            )
            res = await db_session.execute(
                sql,
                {
                    "principal_id": principal_id.strip(),
                    "session_id": session_id.strip(),
                    "from_sequence": from_sequence,
                },
            )
            rows = res.mappings().fetchall()

        events: list[AgentEvent] = []
        for r in rows:
            events.append(
                AgentEvent(
                    event_type=r["event_type"],
                    session_id=r["session_id"],
                    turn_id=r["turn_id"],
                    trace_id=r.get("trace_id") or "",
                    payload=_json_loads(r["payload"]) or {},
                    event_id=r["event_id"],
                    sequence=int(r["sequence"]),
                    created_at=r["created_at"],
                )
            )
        return events

    async def save_evidence_items(
        self,
        principal_id: str,
        session_id: str,
        items: Sequence[EvidenceItem],
    ) -> None:
        if not self._is_postgres_available:
            return await self._fallback.save_evidence_items(principal_id, session_id, items)

        if not items:
            return

        principal = principal_id.strip()
        normalized_sess = session_id.strip()

        async with self._manager.get_postgres_session() as db_session:
            upsert_sql = text(
                """
                INSERT INTO geoai_agent_evidence (
                    id, principal_id, session_id, evidence_id, citation_id, first_turn_id,
                    chunk_id, document_id, text, title, score, metadata, source, match_type, content_hash, is_active
                )
                VALUES (
                    :id, :principal_id, :session_id, :evidence_id, :citation_id, :first_turn_id,
                    :chunk_id, :document_id, :text, :title, :score, :metadata::jsonb, :source, :match_type, :content_hash, TRUE
                )
                ON CONFLICT (principal_id, session_id, evidence_id) DO UPDATE SET
                    citation_id = EXCLUDED.citation_id,
                    score = EXCLUDED.score,
                    is_active = TRUE
                """
            )
            for it in items:
                rec_id = f"{principal}:{normalized_sess}:{it.evidence_id}"
                await db_session.execute(
                    upsert_sql,
                    {
                        "id": rec_id,
                        "principal_id": principal,
                        "session_id": normalized_sess,
                        "evidence_id": it.evidence_id,
                        "citation_id": it.citation_id,
                        "first_turn_id": it.first_turn_id,
                        "chunk_id": it.chunk_id,
                        "document_id": it.document_id,
                        "text": it.text,
                        "title": it.title,
                        "score": it.score,
                        "metadata": _json_dumps(dict(it.metadata)),
                        "source": it.source,
                        "match_type": it.match_type,
                        "content_hash": it.content_hash,
                    },
                )

    async def list_evidence_items(
        self,
        principal_id: str,
        session_id: str,
        active_only: bool = True,
    ) -> list[EvidenceItem]:
        if not self._is_postgres_available:
            return await self._fallback.list_evidence_items(principal_id, session_id, active_only)

        condition = "AND is_active = TRUE" if active_only else ""
        async with self._manager.get_postgres_session() as db_session:
            sql = text(
                f"""
                SELECT evidence_id, citation_id, session_id, first_turn_id, chunk_id,
                       document_id, text, title, score, metadata, source, match_type, content_hash
                FROM geoai_agent_evidence
                WHERE principal_id = :principal_id AND session_id = :session_id {condition}
                ORDER BY created_at ASC
                """
            )
            res = await db_session.execute(
                sql,
                {"principal_id": principal_id.strip(), "session_id": session_id.strip()},
            )
            rows = res.mappings().fetchall()

        items: list[EvidenceItem] = []
        for r in rows:
            items.append(
                EvidenceItem(
                    evidence_id=r["evidence_id"],
                    citation_id=r["citation_id"],
                    session_id=r["session_id"],
                    first_turn_id=r["first_turn_id"],
                    chunk_id=r["chunk_id"],
                    document_id=r["document_id"],
                    text=r["text"],
                    title=r["title"],
                    score=float(r["score"]),
                    metadata=_json_loads(r["metadata"]) or {},
                    source=r["source"],
                    match_type=r["match_type"],
                    content_hash=r["content_hash"],
                )
            )
        return items

    async def save_snapshot(self, record: ContextSnapshotRecord) -> None:
        if not self._is_postgres_available:
            return await self._fallback.save_snapshot(record)

        async with self._manager.get_postgres_session() as db_session:
            sql = text(
                """
                INSERT INTO geoai_context_snapshots (
                    snapshot_id, principal_id, session_id, turn_id, stage,
                    projection_hash, snapshot_payload, token_usage_estimate, source_event_ids, created_at
                )
                VALUES (
                    :snapshot_id, :principal_id, :session_id, :turn_id, :stage,
                    :projection_hash, :snapshot_payload::jsonb, :token_usage_estimate, :source_event_ids::jsonb, :created_at
                )
                ON CONFLICT (snapshot_id) DO NOTHING
                """
            )
            await db_session.execute(
                sql,
                {
                    "snapshot_id": record.snapshot_id,
                    "principal_id": record.principal_id,
                    "session_id": record.session_id,
                    "turn_id": record.turn_id,
                    "stage": record.stage,
                    "projection_hash": record.projection_hash,
                    "snapshot_payload": _json_dumps(dict(record.snapshot_payload)),
                    "token_usage_estimate": record.token_usage_estimate,
                    "source_event_ids": _json_dumps(list(record.source_event_ids)),
                    "created_at": record.created_at,
                },
            )

    async def get_latest_snapshot(
        self,
        principal_id: str,
        session_id: str,
        stage: str | None = None,
    ) -> ContextSnapshotRecord | None:
        if not self._is_postgres_available:
            return await self._fallback.get_latest_snapshot(principal_id, session_id, stage)

        condition = "AND stage = :stage" if stage else ""
        params: dict[str, Any] = {
            "principal_id": principal_id.strip(),
            "session_id": session_id.strip(),
        }
        if stage:
            params["stage"] = stage

        async with self._manager.get_postgres_session() as db_session:
            sql = text(
                f"""
                SELECT snapshot_id, principal_id, session_id, turn_id, stage,
                       projection_hash, snapshot_payload, token_usage_estimate, source_event_ids, created_at
                FROM geoai_context_snapshots
                WHERE principal_id = :principal_id AND session_id = :session_id {condition}
                ORDER BY created_at DESC
                LIMIT 1
                """
            )
            res = await db_session.execute(sql, params)
            row = res.mappings().first()

        if not row:
            return None

        return ContextSnapshotRecord(
            snapshot_id=row["snapshot_id"],
            principal_id=row["principal_id"],
            session_id=row["session_id"],
            turn_id=row["turn_id"],
            stage=row["stage"],
            projection_hash=row["projection_hash"],
            snapshot_payload=_json_loads(row["snapshot_payload"]) or {},
            token_usage_estimate=int(row["token_usage_estimate"] or 0),
            source_event_ids=tuple(_json_loads(row["source_event_ids"]) or ()),
            created_at=row["created_at"],
        )

    async def save_pending_execution(
        self,
        principal_id: str,
        pending: PendingBrowserExecution,
        ttl_seconds: float = 3600.0,
    ) -> None:
        if not self._is_postgres_available:
            return await self._fallback.save_pending_execution(principal_id, pending, ttl_seconds)

        principal = principal_id.strip()
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)

        async with self._manager.get_postgres_session() as db_session:
            upsert_sql = text(
                """
                INSERT INTO geoai_pending_browser_executions (
                    token, principal_id, session_id, question, turn_id, trace_id, tool_call_id, tool_name,
                    observations, request_context, reviewer_enabled, thinking, max_steps, steps_used,
                    max_elapsed_seconds, retrieval_constraints, main_model_name, status, expires_at
                )
                VALUES (
                    :token, :principal_id, :session_id, :question, :turn_id, :trace_id, :tool_call_id, :tool_name,
                    :observations::jsonb, :request_context::jsonb, :reviewer_enabled, :thinking, :max_steps, :steps_used,
                    :max_elapsed_seconds, :retrieval_constraints::jsonb, :main_model_name, 'awaiting_browser', :expires_at
                )
                ON CONFLICT (token) DO UPDATE SET
                    status = 'awaiting_browser',
                    expires_at = EXCLUDED.expires_at
                """
            )
            # Find session_id from turn_id if not directly present
            session_id = getattr(pending, "session_id", "")
            await db_session.execute(
                upsert_sql,
                {
                    "token": pending.token,
                    "principal_id": principal,
                    "session_id": session_id,
                    "question": pending.question,
                    "turn_id": pending.turn_id,
                    "trace_id": pending.trace_id,
                    "tool_call_id": pending.tool_call_id,
                    "tool_name": pending.tool_name,
                    "observations": _json_dumps(list(pending.observations)),
                    "request_context": _json_dumps(dict(pending.request_context)),
                    "reviewer_enabled": pending.reviewer_enabled,
                    "thinking": pending.thinking,
                    "max_steps": pending.max_steps,
                    "steps_used": pending.steps_used,
                    "max_elapsed_seconds": pending.max_elapsed_seconds,
                    "retrieval_constraints": _json_dumps(pending.retrieval_constraints) if pending.retrieval_constraints else None,
                    "main_model_name": pending.main_model_name,
                    "expires_at": expires_at,
                },
            )

    async def get_pending_execution(
        self,
        principal_id: str,
        session_id: str,
    ) -> PendingBrowserExecution | None:
        if not self._is_postgres_available:
            return await self._fallback.get_pending_execution(principal_id, session_id)

        async with self._manager.get_postgres_session() as db_session:
            sql = text(
                """
                SELECT token, question, turn_id, trace_id, tool_call_id, tool_name,
                       observations, request_context, reviewer_enabled, thinking, max_steps,
                       steps_used, max_elapsed_seconds, retrieval_constraints, main_model_name, expires_at
                FROM geoai_pending_browser_executions
                WHERE principal_id = :principal_id AND (session_id = :session_id OR session_id = '') AND status = 'awaiting_browser'
                ORDER BY created_at DESC
                LIMIT 1
                """
            )
            res = await db_session.execute(
                sql,
                {"principal_id": principal_id.strip(), "session_id": session_id.strip()},
            )
            row = res.mappings().first()

        if not row:
            return None

        # Check expiry
        expires_at = row["expires_at"]
        if expires_at and datetime.now(timezone.utc) > expires_at:
            return None

        return PendingBrowserExecution(
            token=row["token"],
            question=row["question"],
            turn_id=row["turn_id"],
            trace_id=row["trace_id"],
            tool_call_id=row["tool_call_id"],
            tool_name=row["tool_name"],
            observations=tuple(_json_loads(row["observations"]) or ()),
            request_context=_json_loads(row["request_context"]) or {},
            reviewer_enabled=bool(row["reviewer_enabled"]),
            thinking=bool(row["thinking"]),
            max_steps=int(row["max_steps"]),
            steps_used=int(row["steps_used"]),
            max_elapsed_seconds=float(row["max_elapsed_seconds"]),
            retrieval_constraints=_json_loads(row["retrieval_constraints"]),
            main_model_name=row["main_model_name"],
        )

    async def clear_pending_execution(
        self,
        principal_id: str,
        session_id: str,
    ) -> None:
        if not self._is_postgres_available:
            return await self._fallback.clear_pending_execution(principal_id, session_id)

        async with self._manager.get_postgres_session() as db_session:
            sql = text(
                """
                UPDATE geoai_pending_browser_executions
                SET status = 'resumed'
                WHERE principal_id = :principal_id AND (session_id = :session_id OR session_id = '') AND status = 'awaiting_browser'
                """
            )
            await db_session.execute(
                sql,
                {"principal_id": principal_id.strip(), "session_id": session_id.strip()},
            )

