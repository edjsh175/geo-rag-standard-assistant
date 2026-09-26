"""Unit tests for GeoAI AgentStore and persistence contracts."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import re
import pytest

from app.models.agent_context import (
    ContextSnapshotRecord,
    ConversationMemoryStateRecord,
    ModelInputAuditRecord,
)
from app.services.agent.contracts import EvidenceItem
from app.services.agent.events import AgentEvent
from app.services.agent.session import PendingBrowserExecution
from app.services.agent.store import InMemoryAgentStore, PostgresAgentStore


class _FakeMappings:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row

    def fetchall(self):
        if self._row is None:
            return []
        if isinstance(self._row, list):
            return self._row
        return [self._row]


class _FakeResult:
    def __init__(self, row=None):
        self._row = row

    def mappings(self):
        return _FakeMappings(self._row)


class _LockingContractSession:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.next_turn_number = 1
        self.events: list[dict] = []

    async def execute(self, sql, params):
        statement = str(sql)
        self.statements.append(statement)
        if "SELECT next_turn_number" in statement and "FOR UPDATE" in statement:
            return _FakeResult({"next_turn_number": self.next_turn_number})
        if "UPDATE geoai_agent_sessions" in statement and "next_turn_number = :next_turn_number" in statement:
            self.next_turn_number = int(params["next_turn_number"])
            return _FakeResult()
        if "SELECT id" in statement and "FOR UPDATE" in statement:
            return _FakeResult({"id": "locked"})
        if "FROM geoai_agent_events" in statement and "WHERE event_id = :event_id" in statement:
            return _FakeResult()
        if "COALESCE(MAX(sequence), 0) + 1" in statement:
            return _FakeResult({"next_seq": len(self.events) + 1})
        if "INSERT INTO geoai_agent_events" in statement:
            self.events.append(dict(params))
            return _FakeResult()
        return _FakeResult()


class _LockingContractManager:
    def __init__(self) -> None:
        self.postgres_sessionmaker = object()
        self.session = _LockingContractSession()

    @asynccontextmanager
    async def get_postgres_session(self):
        yield self.session


class _SessionInsertContractSession:
    def __init__(self) -> None:
        self.seen_insert = False

    async def execute(self, sql, params):
        statement = str(sql)
        if "SELECT id, principal_id, session_id, status, next_turn_number, metadata" in statement:
            return _FakeResult()
        if "INSERT INTO geoai_agent_sessions" in statement and "RETURNING id" in statement:
            self.seen_insert = True
            match = re.search(
                r"INSERT INTO geoai_agent_sessions\s*\((.*?)\)\s*VALUES\s*\((.*?)\)",
                statement,
                re.IGNORECASE | re.DOTALL,
            )
            assert match is not None
            columns = [item.strip() for item in match.group(1).split(",")]
            values = [item.strip() for item in match.group(2).split(",")]
            assert len(values) == len(columns), (
                f"geoai_agent_sessions INSERT has {len(columns)} columns but {len(values)} values"
            )
            return _FakeResult(
                {
                    "id": params["id"],
                    "principal_id": params["principal_id"],
                    "session_id": params["session_id"],
                    "status": "active",
                    "next_turn_number": 1,
                    "metadata": {},
                }
            )
        return _FakeResult()


class _SessionInsertContractManager:
    def __init__(self) -> None:
        self.postgres_sessionmaker = object()
        self.session = _SessionInsertContractSession()

    @asynccontextmanager
    async def get_postgres_session(self):
        yield self.session


class _ModelAuditContractSession:
    def __init__(self) -> None:
        self.row = None

    async def execute(self, sql, params):
        statement = str(sql)
        if "INSERT INTO geoai_model_input_audits" in statement:
            self.row = dict(params)
            return _FakeResult({"audit_id": params["audit_id"]})
        if "FROM geoai_model_input_audits" in statement and "WHERE principal_id" in statement:
            return _FakeResult([dict(self.row)] if self.row is not None else [])
        if "FROM geoai_model_input_audits" in statement and "WHERE audit_id" in statement:
            return _FakeResult(dict(self.row) if self.row is not None else None)
        return _FakeResult()


class _ModelAuditContractManager:
    def __init__(self) -> None:
        self.postgres_sessionmaker = object()
        self.session = _ModelAuditContractSession()

    @asynccontextmanager
    async def get_postgres_session(self):
        yield self.session


class _ConversationMemoryContractSession:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def execute(self, sql, params):
        statement = str(sql)
        if "INSERT INTO geoai_conversation_memory_states" in statement:
            row = dict(params)
            self.rows.append(row)
            return _FakeResult({"memory_id": params["memory_id"]})
        if "FROM geoai_conversation_memory_states" in statement:
            matching = [
                row
                for row in self.rows
                if row["principal_id"] == params["principal_id"]
                and row["session_id"] == params["session_id"]
            ]
            if "summary_version = :summary_version" in statement:
                matching = [
                    row
                    for row in matching
                    if row["summary_version"] == params["summary_version"]
                ]
            matching.sort(key=lambda row: row["summary_version"], reverse=True)
            return _FakeResult(dict(matching[0]) if matching else None)
        return _FakeResult()


class _ConversationMemoryContractManager:
    def __init__(self) -> None:
        self.postgres_sessionmaker = object()
        self.session = _ConversationMemoryContractSession()

    @asynccontextmanager
    async def get_postgres_session(self):
        yield self.session


@pytest.mark.asyncio
async def test_in_memory_agent_store_session_lifecycle():
    store = InMemoryAgentStore(max_sessions=10)
    session = await store.get_or_create_session(
        principal_id="user-1",
        session_id="sess-100",
    )
    assert session.principal_id == "user-1"
    assert session.session_id == "sess-100"
    assert session.next_turn_number == 1
    assert session.evidence_ledger.session_id == "sess-100"

    retrieved = await store.get_session("user-1", "sess-100")
    assert retrieved is session

    not_found = await store.get_session("user-1", "non-existent")
    assert not_found is None


@pytest.mark.asyncio
async def test_in_memory_agent_store_allocates_unique_turn_ids_concurrently():
    store = InMemoryAgentStore(max_sessions=10)
    await store.get_or_create_session("user-1", "sess-turns")

    turn_ids = await asyncio.gather(
        *(store.allocate_turn_id("user-1", "sess-turns") for _ in range(50))
    )

    turn_numbers = sorted(int(turn_id.removeprefix("turn-")) for turn_id in turn_ids)
    assert turn_numbers == list(range(1, 51))
    session = await store.get_session("user-1", "sess-turns")
    assert session is not None
    assert session.next_turn_number == 51


@pytest.mark.asyncio
async def test_in_memory_agent_store_event_sourcing():
    store = InMemoryAgentStore()
    ev1 = await store.append_event(
        principal_id="user-1",
        event=AgentEvent(
            event_type="user_message",
            session_id="sess-1",
            turn_id="turn-1",
            trace_id="tr-1",
            payload={"text": "hello"},
        ),
    )
    assert ev1.sequence == 1
    assert ev1.event_id != ""

    ev2 = await store.append_event(
        principal_id="user-1",
        event=AgentEvent(
            event_type="assistant_message",
            session_id="sess-1",
            turn_id="turn-1",
            trace_id="tr-1",
            payload={"text": "hi there"},
        ),
    )
    assert ev2.sequence == 2

    events = await store.list_events("user-1", "sess-1")
    assert len(events) == 2
    assert events[0].event_type == "user_message"
    assert events[1].event_type == "assistant_message"

    partial = await store.list_events("user-1", "sess-1", from_sequence=2)
    assert len(partial) == 1
    assert partial[0].sequence == 2


@pytest.mark.asyncio
async def test_in_memory_agent_store_event_append_is_idempotent_by_event_id():
    store = InMemoryAgentStore()
    event = AgentEvent(
        event_type="user_message",
        session_id="sess-idempotent",
        turn_id="turn-1",
        trace_id="trace-1",
        payload={"text": "hello"},
    )

    first = await store.append_event("user-1", event)
    second = await store.append_event("user-1", event)

    assert first.event_id == second.event_id
    assert first.sequence == second.sequence == 1
    assert len(await store.list_events("user-1", "sess-idempotent")) == 1


@pytest.mark.asyncio
async def test_in_memory_agent_store_evidence_persistence():
    store = InMemoryAgentStore()
    item = EvidenceItem(
        evidence_id="ev-123",
        citation_id="E1",
        session_id="sess-1",
        first_turn_id="turn-1",
        chunk_id="chunk-456",
        document_id="doc-1",
        text="Sample urban planning text",
        title="Planning Guide",
        score=0.95,
        metadata={"category": "zoning"},
        source="doc_store",
        match_type="hybrid",
        content_hash="hash-123",
    )

    await store.save_evidence_items("user-1", "sess-1", [item])
    items = await store.list_evidence_items("user-1", "sess-1")
    assert len(items) == 1
    assert items[0].evidence_id == "ev-123"
    assert items[0].text == "Sample urban planning text"


@pytest.mark.asyncio
async def test_in_memory_agent_store_snapshots():
    store = InMemoryAgentStore()
    snap = ContextSnapshotRecord(
        snapshot_id="snap-1",
        principal_id="user-1",
        session_id="sess-1",
        turn_id="turn-1",
        stage="controller",
        projection_hash="hash-abc",
        snapshot_payload={"tool_names": "search_spatial"},
        token_usage_estimate=450,
        source_event_ids=("ev-1", "ev-2"),
    )

    await store.save_snapshot(snap)
    latest_ctrl = await store.get_latest_snapshot("user-1", "sess-1", stage="controller")
    assert latest_ctrl is not None
    assert latest_ctrl.snapshot_id == "snap-1"
    assert latest_ctrl.token_usage_estimate == 450

    latest_ans = await store.get_latest_snapshot("user-1", "sess-1", stage="answer")
    assert latest_ans is None


@pytest.mark.asyncio
async def test_in_memory_model_input_audit_is_idempotent_and_conflict_safe():
    store = InMemoryAgentStore()
    created_at = datetime.now(timezone.utc)
    record = ModelInputAuditRecord(
        audit_id="call-1:1",
        principal_id="user-1",
        session_id="sess-1",
        turn_id="turn-1",
        stage="controller",
        call_id="call-1",
        attempt=1,
        model_name="main-model",
        request_reasoning=True,
        temperature=0.2,
        timeout_seconds=10.0,
        response_schema_hash="schema-hash",
        messages_hash="messages-hash",
        messages_section_hashes=("system-hash", "user-hash"),
        context_snapshot_id="snap-1",
        action_surface_hash="action-hash",
        tool_contract_hash="tool-hash",
        created_at=created_at,
    )

    await store.save_model_input_audit(record)
    await store.save_model_input_audit(record)
    rows = await store.list_model_input_audits("user-1", "sess-1", "turn-1")
    assert rows == [record]

    conflicting = replace(record, messages_hash="different-hash")
    with pytest.raises(RuntimeError, match="model input audit conflict"):
        await store.save_model_input_audit(conflicting)


@pytest.mark.asyncio
async def test_in_memory_agent_store_pending_browser_execution():
    store = InMemoryAgentStore()
    pending = PendingBrowserExecution(
        token="tok-999",
        question="Show zoning map",
        turn_id="turn-1",
        trace_id="tr-1",
        tool_call_id="call-1",
        tool_name="browser_render_map",
        observations=(),
        request_context={"zoom": 12},
        reviewer_enabled=True,
        thinking=False,
        max_steps=5,
        steps_used=1,
        max_elapsed_seconds=30.0,
        retrieval_constraints=None,
        main_model_name="deepseek-chat",
    )

    # Attach to session
    sess = await store.get_or_create_session("user-1", "sess-1")
    sess.pending_browser_execution = pending
    await store.save_session(sess)

    loaded = await store.get_pending_execution("user-1", "sess-1")
    assert loaded is not None
    assert loaded.token == "tok-999"
    assert loaded.tool_name == "browser_render_map"

    await store.clear_pending_execution("user-1", "sess-1")
    cleared = await store.get_pending_execution("user-1", "sess-1")
    assert cleared is None


@pytest.mark.asyncio
async def test_in_memory_pending_execution_can_only_be_claimed_once():
    store = InMemoryAgentStore()
    pending = PendingBrowserExecution(
        token="tok-once",
        question="继续地图操作",
        turn_id="turn-1",
        trace_id="trace-1",
        tool_call_id="call-1",
        tool_name="locate_map",
        observations=(),
        request_context={},
        reviewer_enabled=False,
        thinking=False,
        max_steps=4,
        steps_used=1,
        max_elapsed_seconds=30,
        retrieval_constraints=None,
        main_model_name=None,
        session_id="sess-claim",
    )
    session = await store.get_or_create_session("user-1", "sess-claim")
    session.pending_browser_execution = pending
    await store.save_session(session)

    claimed = await asyncio.gather(
        store.claim_pending_execution("user-1", "sess-claim", "tok-once"),
        store.claim_pending_execution("user-1", "sess-claim", "tok-once"),
    )

    assert sum(item is not None for item in claimed) == 1
    assert await store.get_pending_execution("user-1", "sess-claim") is None


@pytest.mark.asyncio
async def test_postgres_turn_allocation_locks_session_row_before_increment():
    manager = _LockingContractManager()
    store = PostgresAgentStore(manager=manager)

    first = await store.allocate_turn_id("user-1", "sess-lock")
    second = await store.allocate_turn_id("user-1", "sess-lock")

    assert (first, second) == ("turn-1", "turn-2")
    lock_positions = [
        index
        for index, statement in enumerate(manager.session.statements)
        if "SELECT next_turn_number" in statement and "FOR UPDATE" in statement
    ]
    update_positions = [
        index
        for index, statement in enumerate(manager.session.statements)
        if "UPDATE geoai_agent_sessions" in statement and "next_turn_number = :next_turn_number" in statement
    ]
    assert len(lock_positions) == len(update_positions) == 2
    assert all(lock < update for lock, update in zip(lock_positions, update_positions))


@pytest.mark.asyncio
async def test_postgres_get_or_create_session_insert_has_matching_column_value_arity():
    manager = _SessionInsertContractManager()
    store = PostgresAgentStore(manager=manager)

    session = await store.get_or_create_session("user-1", "sess-create")

    assert manager.session.seen_insert is True
    assert session.principal_id == "user-1"
    assert session.session_id == "sess-create"


@pytest.mark.asyncio
async def test_postgres_model_input_audit_roundtrip_contract():
    manager = _ModelAuditContractManager()
    store = PostgresAgentStore(manager=manager)
    record = ModelInputAuditRecord(
        audit_id="call-pg:1",
        principal_id="user-1",
        session_id="sess-audit",
        turn_id="turn-1",
        stage="controller",
        call_id="call-pg",
        attempt=1,
        model_name="main-model",
        request_reasoning=False,
        temperature=0.2,
        timeout_seconds=5.0,
        response_schema_hash="schema-hash",
        messages_hash="messages-hash",
        messages_section_hashes=("system-hash", "user-hash"),
        context_snapshot_id="snap-1",
        frozen_evidence_snapshot_id=None,
        action_surface_hash="action-hash",
        tool_contract_hash="tool-hash",
        created_at=datetime.now(timezone.utc),
    )

    await store.save_model_input_audit(record)
    rows = await store.list_model_input_audits("user-1", "sess-audit", "turn-1")

    assert rows == [record]


@pytest.mark.asyncio
async def test_postgres_conversation_memory_roundtrip_contract():
    manager = _ConversationMemoryContractManager()
    store = PostgresAgentStore(manager=manager)
    record = ConversationMemoryStateRecord(
        memory_id="memory-1",
        principal_id="user-1",
        session_id="sess-memory",
        summary_version=1,
        covered_from_sequence=1,
        covered_to_sequence=12,
        rolling_summary="用户正在做规划核查。",
        active_goal="完成规划核查",
        user_constraints=("只使用已选文档",),
        explicit_ui_selections={"document": {"document_id": "doc-1"}},
        authoritative_runtime_facts={
            "last_browser_effect": {"effect": {"state_revision": 4}}
        },
        source_event_ids=("ev-1", "ev-2"),
        source_hash="source-hash-1",
        created_at=datetime.now(timezone.utc),
    )

    await store.save_conversation_memory(record)
    loaded = await store.get_latest_conversation_memory("user-1", "sess-memory")

    assert loaded == record


def test_conversation_memory_migration_contract_covers_authority_fields() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    migration = repo_root / "Backend" / "migrations" / "20260926_conversation_memory.sql"
    sql = migration.read_text(encoding="utf-8")

    assert "geoai_conversation_memory_states" in sql
    assert "explicit_ui_selections JSONB" in sql
    assert "authoritative_runtime_facts JSONB" in sql
    assert "UNIQUE (principal_id, session_id, summary_version)" in sql


@pytest.mark.asyncio
async def test_postgres_event_sequence_locks_session_row_before_max_sequence():
    manager = _LockingContractManager()
    store = PostgresAgentStore(manager=manager)

    persisted = await store.append_event(
        "user-1",
        AgentEvent(
            event_type="controller_decision",
            session_id="sess-lock",
            turn_id="turn-1",
            trace_id="trace-1",
            payload={"action": "retrieve_kb"},
        ),
    )

    assert persisted.sequence == 1
    lock_index = next(
        index
        for index, statement in enumerate(manager.session.statements)
        if "SELECT id" in statement and "FOR UPDATE" in statement
    )
    max_index = next(
        index
        for index, statement in enumerate(manager.session.statements)
        if "COALESCE(MAX(sequence), 0) + 1" in statement
    )
    insert_index = next(
        index
        for index, statement in enumerate(manager.session.statements)
        if "INSERT INTO geoai_agent_events" in statement
    )
    assert lock_index < max_index < insert_index
