"""Test R-06: Controller Context Budget accounting for full prompt, Evidence Catalog priority trimming, and runtime facts."""

import json
import pytest

from app.services.agent.context.budget import (
    CharWeightedTokenEstimator,
    ContextBudgetConfig,
    ContextBudgetManager,
    StageBudget,
)
from app.services.agent.context.engine import ContextEngine
from app.services.agent.context.frame import ContextFrame
from app.services.agent.events import AgentEvent


def test_trim_controller_context_respects_catalog_allowance_and_sets_metadata():
    """Verify that when evidence catalog is large, it gets trimmed according to budget and returns catalog_metadata."""
    config = ContextBudgetConfig(
        controller=StageBudget(max_tokens=300, system_reserve=20, generation_reserve=20)
    )
    manager = ContextBudgetManager(config=config, estimator=CharWeightedTokenEstimator())

    # Build 20 evidence items
    catalog = [
        {"evidence_id": f"ev-{i}", "title": f"Doc {i}", "text": "Some text content here " * 5, "score": 0.5 + (i * 0.02)}
        for i in range(20)
    ]
    working = catalog[:5]
    facts = {
        "current_turn": {"turn_id": "turn-1", "status": "active"},
        "previous_turn": {"turn_id": "turn-0", "status": "done", "details": "long history " * 10},
    }

    res = manager.trim_controller_context(
        question="What is the standard?",
        conversation_lines=["user: hello", "assistant: hi"],
        working_evidence=working,
        evidence_catalog=catalog,
        runtime_facts=facts,
        tool_contracts_text="tool retrieve_kb: search docs",
    )

    # res should unpack as 4 items for backward compatibility
    summary, trimmed_ev, trimmed_map, tokens = res
    assert tokens <= config.controller.available_context_tokens
    assert len(res.evidence_catalog) < len(catalog)
    assert res.catalog_metadata["truncated"] is True
    assert res.catalog_metadata["total_count"] == 20
    assert res.catalog_metadata["projected_count"] == len(res.evidence_catalog)


def test_trim_controller_context_prioritizes_referenced_and_high_score_evidence():
    """Verify that priority evidence (referenced in question or high score) is retained over low score evidence."""
    config = ContextBudgetConfig(
        controller=StageBudget(max_tokens=400, system_reserve=20, generation_reserve=20)
    )
    manager = ContextBudgetManager(config=config, estimator=CharWeightedTokenEstimator())

    catalog = [
        {"evidence_id": "ev-ref", "title": "Special Topic", "text": "Critical data for query", "score": 0.1},
        {"evidence_id": "ev-low", "title": "Other", "text": "Filler content " * 10, "score": 0.2},
        {"evidence_id": "ev-high", "title": "Relevant", "text": "Important data " * 5, "score": 0.99},
    ]

    res = manager.trim_controller_context(
        question="Tell me about Special Topic",
        conversation_lines=[],
        working_evidence=catalog,
        evidence_catalog=catalog,
        tool_contracts_text="",
    )

    selected_ids = {e["evidence_id"] for e in res.evidence_catalog}
    # "Special Topic" is referenced in question, so it must be preserved
    assert "ev-ref" in selected_ids
    # "ev-high" has top score, so it must be preserved
    assert "ev-high" in selected_ids


def test_engine_project_for_controller_injects_catalog_metadata_and_trimmed_catalog():
    """Verify that ContextEngine passes trimmed evidence catalog and metadata into ControllerContextProjection."""
    config = ContextBudgetConfig(
        controller=StageBudget(max_tokens=350, system_reserve=20, generation_reserve=20)
    )
    budget_mgr = ContextBudgetManager(config=config, estimator=CharWeightedTokenEstimator())
    engine = ContextEngine(budget_manager=budget_mgr)

    catalog = [
        {"evidence_id": f"ev-{i}", "title": f"Doc {i}", "text": "Long text block " * 8, "score": 0.8}
        for i in range(15)
    ]
    frame = engine.build_frame(
        session_id="sess-1",
        principal_id="user-1",
        question="Query about standards",
        events=[],
        working_evidence=catalog[:3],
        evidence_memory=catalog[3:],
    )

    projection, snapshot = engine.project_for_controller(
        frame,
        tool_contracts_text="tool contracts text here",
        tool_names="tool1, tool2",
        available_capabilities=["retrieve_kb"],
        available_control_actions=["compose_answer"],
    )

    assert len(projection.evidence_catalog) < len(catalog)
    assert projection.catalog_metadata.get("truncated") is True
    assert projection.catalog_metadata.get("total_count") == 15
    assert projection.estimated_tokens <= config.controller.available_context_tokens
    # ContextSnapshot sections should contain catalog_metadata
    assert "catalog_metadata" in [s.name for s in snapshot.sections]
