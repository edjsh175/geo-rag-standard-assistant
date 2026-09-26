"""Unit tests for GeoAI AgentStore and persistence contracts."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import re
import pytest

from app.models.agent_context import ContextSnapshotRecord
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
