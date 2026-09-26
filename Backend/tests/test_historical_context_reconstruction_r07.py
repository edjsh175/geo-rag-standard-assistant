"""Test R-07: Historical Context Reconstruction authority and hash verification."""

import pytest

from app.services.agent.context.engine import ContextEngine
from app.services.agent.context.reconstruct import GeoAIHistoricalContextReconstructor
from app.services.agent.events import AgentEvent


def test_reconstruct_controller_matches_hash_on_identical_history():
    """Verify that reconstruct_controller successfully reproduces the projection and frame hash from durable events and evidence."""
    engine = ContextEngine()
    reconstructor = GeoAIHistoricalContextReconstructor(context_engine=engine)

    events = [
        AgentEvent(event_type="user_message", session_id="sess-replay-1", turn_id="turn-1", event_id="evt-1", payload={"text": "Hello, need spatial analysis"}),
        AgentEvent(event_type="assistant_message", session_id="sess-replay-1", turn_id="turn-1", event_id="evt-2", payload={"text": "I can help with that"}),
        AgentEvent(event_type="user_message", session_id="sess-replay-1", turn_id="turn-2", event_id="evt-3", payload={"text": "Check zone boundaries"}),
    ]
    catalog = [
        {"evidence_id": "ev-1", "title": "Zone Policy", "text": "Zone A is protected.", "score": 0.9},
    ]

    frame = engine.build_frame(
        session_id="sess-replay-1",
        principal_id="principal-1",
        question="Check zone boundaries",
        events=events,
        working_evidence=catalog,
        current_turn_id="turn-2",
    )

    proj, snapshot = engine.project_for_controller(
        frame,
        tool_contracts_text="tool query_spatial: spatial relation check",
        tool_names="query_spatial",
        available_capabilities=["query_spatial"],
        available_control_actions=["compose_answer", "direct_answer"],
    )

    snapshot_record = snapshot.to_record("principal-1")

    # Replay reconstruction
    result = reconstructor.reconstruct_controller(
        snapshot=snapshot_record,
        events=events,
        working_evidence=catalog,
        evidence_catalog=(),
        user_question="Check zone boundaries",
        tool_contracts_text="tool query_spatial: spatial relation check",
        tool_names="query_spatial",
        available_capabilities=["query_spatial"],
        available_control_actions=["compose_answer", "direct_answer"],
    )

    assert result.matched is True
    assert result.expected_projection_hash == snapshot.projection_hash
    assert result.reconstructed_projection_hash == snapshot.projection_hash
    assert result.sections_matched is True
    assert len(result.differing_sections) == 0


def test_reconstruct_controller_detects_mismatch_when_evidence_modified():
    """Verify that reconstruct_controller detects tamper or deviation when historical evidence is altered."""
    engine = ContextEngine()
    reconstructor = GeoAIHistoricalContextReconstructor(context_engine=engine)

    events = [
        AgentEvent(event_type="user_message", session_id="sess-tamper", turn_id="turn-1", event_id="evt-1", payload={"text": "Initial query"}),
    ]
    catalog = [
        {"evidence_id": "ev-1", "title": "Original Doc", "text": "Original text.", "score": 0.8},
    ]

    frame = engine.build_frame(
        session_id="sess-tamper",
        principal_id="principal-1",
        question="Initial query",
        events=events,
        working_evidence=catalog,
        current_turn_id="turn-1",
    )

    _, snapshot = engine.project_for_controller(
        frame,
        tool_contracts_text="contracts",
        tool_names="tools",
    )
    snapshot_record = snapshot.to_record("principal-1")

    # Tampered evidence catalog
    tampered_catalog = [
        {"evidence_id": "ev-1", "title": "Tampered Doc", "text": "Tampered text changed.", "score": 0.8},
    ]

    result = reconstructor.reconstruct_controller(
        snapshot=snapshot_record,
        events=events,
        working_evidence=tampered_catalog,
        evidence_catalog=(),
        user_question="Initial query",
        tool_contracts_text="contracts",
        tool_names="tools",
    )

    assert result.matched is False
    assert result.reconstructed_projection_hash != snapshot.projection_hash
    assert "evidence_catalog" in result.differing_sections or "working_evidence" in result.differing_sections
