"""Test R-09 and R-10: ContextSnapshot observability on failure and action surface identity."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.agent.context.engine import ContextEngine
from app.services.agent.context.snapshot import ContextSnapshot
from app.services.agent.events import AgentEvent
from app.services.agent.runtime import AgentRunRequest, AgentRuntime
from app.services.agent.session import AgentSession, InMemoryAgentSessionStore
from app.services.agent.evidence import EvidenceLedger


@pytest.mark.asyncio
async def test_r09_save_snapshot_failure_records_event_and_sets_audit_degraded():
    """Verify that when save_snapshot fails, runtime emits context_snapshot_persist_failed event and sets audit_degraded=True."""
    store = InMemoryAgentSessionStore()
    runtime = AgentRuntime(
        session_store=store,
        retrieval_port=MagicMock(),
        controller=MagicMock(),
        answer_generator=MagicMock(),
    )

    session = AgentSession(
        principal_id="user-p",
        session_id="sess-audit-1",
        evidence_ledger=EvidenceLedger(session_id="sess-audit-1"),
        events=[AgentEvent(event_type="user_message", session_id="sess-audit-1", turn_id="turn-1", event_id="e-1", payload={"text": "hello"})],
    )
    request = AgentRunRequest(
        question="hello",
        session_id="sess-audit-1",
        principal_id="user-p",
    )

    # Mock store.save_snapshot to raise an exception
    store.save_snapshot = AsyncMock(side_effect=RuntimeError("Disk I/O error"))

    snapshot = ContextSnapshot.create(
        stage="controller",
        session_id="sess-audit-1",
        turn_id="turn-1",
        frame_payload={"sample": "data"},
        projection_sections={"section": "content"},
    )

    session_events = list(session.events)
    turn_events = []

    await runtime._save_snapshot_audited(
        snapshot=snapshot,
        session=session,
        request=request,
        stage="controller",
        session_events=session_events,
        turn_events=turn_events,
    )

    assert session.audit_degraded is True
    # The fail event should be appended
    fail_events = [e for e in session_events if e.event_type == "context_snapshot_persist_failed"]
    assert len(fail_events) == 1
    assert fail_events[0].payload["stage"] == "controller"
    assert "Disk I/O error" in fail_events[0].payload["error"]
    assert fail_events[0].payload["audit_degraded"] is True


@pytest.mark.asyncio
async def test_r09_strict_audit_mode_raises_on_failure():
    """Verify that when strict_audit is set to True, snapshot save failure raises immediately (fail-close)."""
    store = InMemoryAgentSessionStore()
    runtime = AgentRuntime(
        session_store=store,
        retrieval_port=MagicMock(),
        controller=MagicMock(),
        answer_generator=MagicMock(),
    )
    runtime.strict_audit = True

    session = AgentSession(
        principal_id="user-p",
        session_id="sess-audit-strict",
        evidence_ledger=EvidenceLedger(session_id="sess-audit-strict"),
    )
    request = AgentRunRequest(
        question="hello",
        session_id="sess-audit-strict",
        principal_id="user-p",
    )
    store.save_snapshot = AsyncMock(side_effect=RuntimeError("Strict persistence failure"))

    snapshot = ContextSnapshot.create(
        stage="controller",
        session_id="sess-audit-strict",
        turn_id="turn-1",
        frame_payload={"sample": "data"},
        projection_sections={"section": "content"},
    )

    with pytest.raises(RuntimeError, match="Strict persistence failure"):
        await runtime._save_snapshot_audited(
            snapshot=snapshot,
            session=session,
            request=request,
            stage="controller",
        )


def test_r10_context_snapshot_contains_action_surface_identity():
    """Verify that ContextSnapshot records action surface version identity in snapshot payload."""
    engine = ContextEngine()
    frame = engine.build_frame(
        session_id="sess-identity",
        principal_id="user-1",
        question="Find regional zones",
        events=[],
        working_evidence=[],
    )

    _, snapshot = engine.project_for_controller(
        frame,
        tool_contracts_text="tool contracts xyz",
        tool_names="toolA, toolB",
        available_capabilities=["toolA", "toolB"],
        available_control_actions=["compose_answer"],
    )

    record = snapshot.to_record("user-1")
    action_surface = record.snapshot_payload.get("action_surface_identity")
    assert action_surface is not None
    assert action_surface["schema_version"] == "v3"
    assert action_surface["available_capabilities"] == ["toolA", "toolB"]
    assert action_surface["available_control_actions"] == ["compose_answer"]
    assert action_surface["tool_names"] == "toolA, toolB"
    assert len(action_surface["tool_contracts_hash"]) == 64
