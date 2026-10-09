"""Tests for Phase 3: Tool Risk Classification and Human-in-the-loop Governance."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.services.agent.tool_policy import (
    DEFAULT_TOOL_RISK_MAP,
    ToolConfirmationRequired,
    ToolExecutionContext,
    ToolPolicy,
    ToolRiskLevel,
    classify_tool_risk,
)
from app.services.agent.tools import ToolSpec


class DummyToolInput(BaseModel):
    arg: str = "val"


def test_classify_tool_risk_standard_tools() -> None:
    assert classify_tool_risk("retrieve_kb") == ToolRiskLevel.READ_ONLY
    assert classify_tool_risk("list_applicable_standards") == ToolRiskLevel.READ_ONLY
    assert classify_tool_risk("reuse_evidence") == ToolRiskLevel.READ_ONLY
    assert classify_tool_risk("inspect_layer_features") == ToolRiskLevel.READ_ONLY

    assert classify_tool_risk("locate_map") == ToolRiskLevel.MUTATING
    assert classify_tool_risk("select_region") == ToolRiskLevel.MUTATING
    assert classify_tool_risk("set_layer_visibility") == ToolRiskLevel.MUTATING
    assert classify_tool_risk("set_vector_style") == ToolRiskLevel.MUTATING

    assert classify_tool_risk("import_vector_dataset") == ToolRiskLevel.HIGH_RISK


def test_classify_tool_risk_custom_spec() -> None:
    read_spec = ToolSpec(name="custom_read", description="r", input_model=DummyToolInput, side_effect=False)
    assert classify_tool_risk("custom_read", read_spec) == ToolRiskLevel.READ_ONLY

    mutate_spec = ToolSpec(name="custom_write", description="w", input_model=DummyToolInput, side_effect=True)
    assert classify_tool_risk("custom_write", mutate_spec) == ToolRiskLevel.MUTATING

    high_spec = ToolSpec(
        name="custom_delete",
        description="d",
        input_model=DummyToolInput,
        confirmation_required=True,
    )
    assert classify_tool_risk("custom_delete", high_spec) == ToolRiskLevel.HIGH_RISK


def test_hitl_high_risk_requires_confirmation() -> None:
    policy = ToolPolicy()
    spec = ToolSpec(
        name="import_vector_dataset",
        description="Import vector layer",
        input_model=DummyToolInput,
        side_effect=True,
    )

    # Execution context requiring approval for HIGH_RISK tools
    ctx_unconfirmed = ToolExecutionContext(
        require_approval_levels=frozenset({ToolRiskLevel.HIGH_RISK}),
        confirmed_tool_call_ids=frozenset(),
    )

    with pytest.raises(ToolConfirmationRequired, match="import_vector_dataset.*requires explicit confirmation"):
        policy.authorize(spec=spec, tool_call_id="call_import_1", context=ctx_unconfirmed)

    # Once human-in-the-loop confirmation is recorded:
    ctx_confirmed = ToolExecutionContext(
        require_approval_levels=frozenset({ToolRiskLevel.HIGH_RISK}),
        confirmed_tool_call_ids=frozenset({"call_import_1"}),
    )
    # Authorization succeeds without exception
    policy.authorize(spec=spec, tool_call_id="call_import_1", context=ctx_confirmed)


def test_hitl_read_only_tool_not_blocked() -> None:
    policy = ToolPolicy()
    spec = ToolSpec(
        name="retrieve_kb",
        description="Search KB",
        input_model=DummyToolInput,
        side_effect=False,
    )

    ctx = ToolExecutionContext(
        require_approval_levels=frozenset({ToolRiskLevel.HIGH_RISK}),
        confirmed_tool_call_ids=frozenset(),
    )
    # Read only tools are authorized directly
    policy.authorize(spec=spec, tool_call_id="call_kb_1", context=ctx)
