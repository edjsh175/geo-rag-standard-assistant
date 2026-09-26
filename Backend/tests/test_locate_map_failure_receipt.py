from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services.agent.evidence import EvidenceLedger
from app.services.agent.tool_runtime import ToolCall, ToolRuntime
from app.services.agent.tools import LocateMapInput, build_default_tool_registry


class UnusedRetrievalPort:
    async def retrieve(self, query):  # pragma: no cover - locate_map never retrieves
        raise AssertionError("locate_map must not call retrieval")


def test_controller_locate_map_payload_accepts_out_of_range_finite_coordinates() -> None:
    registry = build_default_tool_registry()

    arguments = registry.validate(
        "locate_map", {"longitude": 999, "latitude": 30, "zoom": 8}
    )

    assert arguments == {"longitude": 999.0, "latitude": 30.0, "zoom": 8.0}


@pytest.mark.asyncio
async def test_locate_map_runtime_returns_browser_action_payload_for_out_of_range_coordinate() -> None:
    runtime = ToolRuntime(
        retrieval_port=UnusedRetrievalPort(),
        evidence_ledger=EvidenceLedger(session_id="locate-map-failure-receipt"),
    )

    observation = await runtime.execute(
        turn_id="turn-1",
        call=ToolCall(
            tool_call_id="locate-999",
            name="locate_map",
            arguments={"longitude": 999, "latitude": 30, "zoom": 8},
        ),
    )

    assert observation.status == "browser_execution_required"
    assert observation.payload["map_action"] == {
        "type": "locate_map",
        "target": "browser_map",
        "timeout_seconds": 30.0,
        "payload": {"longitude": 999.0, "latitude": 30.0, "zoom": 8.0},
    }


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_locate_map_still_rejects_non_finite_coordinates(value: float) -> None:
    with pytest.raises(ValidationError):
        LocateMapInput(longitude=value, latitude=30)


def test_locate_map_still_rejects_invalid_zoom() -> None:
    with pytest.raises(ValidationError):
        LocateMapInput(longitude=999, latitude=30, zoom=23)
