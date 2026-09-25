"""Unit tests for GeoAI AgentStore and persistence contracts."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import pytest

from app.models.agent_context import ContextSnapshotRecord
from app.services.agent.contracts import EvidenceItem
from app.services.agent.events import AgentEvent
from app.services.agent.session import PendingBrowserExecution
from app.services.agent.store import InMemoryAgentStore


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
