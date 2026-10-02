from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.services.agent.controller_protocol import ControllerDecision
from app.services.agent.graph.planning import PlanningGraphContext, build_planning_graph
from app.services.agent.tool_runtime import ToolObservation


@dataclass
class Outcome:
    observation: ToolObservation | None = None
    terminal_error: str | None = None


@pytest.mark.asyncio
async def test_planning_graph_owns_controller_tool_replan_loop() -> None:
    projections = []
    decisions = [
        ControllerDecision(
            action="tool_call",
            tool="retrieve_kb",
            arguments={"query": "成都"},
            tool_call_id="call-1",
        ),
        ControllerDecision(
            action="compose_answer",
            arguments={"answer_kind": "knowledge_answer", "selected_evidence_ids": ["ev-1"]},
            tool_call_id="call-2",
        ),
    ]
    executed = []

    async def project_context():
        projection = {"version": len(projections) + 1}
        projections.append(projection)
        return projection

    async def decide(projection):
        assert projection == projections[-1]
        return decisions.pop(0)

    async def execute_tool(decision):
        executed.append(decision.tool)
        return Outcome(
            observation=ToolObservation(
                tool_call_id="call-1",
                tool_name="retrieve_kb",
                status="completed",
                payload={"evidence_ids": ["ev-1"]},
                is_terminal=False,
            )
        )

    context = PlanningGraphContext(
        project_context=project_context,
        decide=decide,
        execute_tool=execute_tool,
    )
    result = await build_planning_graph().ainvoke(
        {"principal_id": "p", "session_id": "s", "turn_id": "t", "trace_id": "tr"},
        context=context,
    )

    assert len(projections) == 2
    assert executed == ["retrieve_kb"]
    assert context.latest_decision.action == "compose_answer"
    assert result["decision_kind"] == "compose_answer"


@pytest.mark.asyncio
async def test_planning_graph_stops_for_browser_handoff() -> None:
    decision = ControllerDecision(
        action="tool_call",
        tool="locate_map",
        arguments={"longitude": 104.0, "latitude": 30.0},
        tool_call_id="call-map",
    )

    async def project_context():
        return object()

    async def decide(_projection):
        return decision

    async def execute_tool(_decision):
        return Outcome(
            observation=ToolObservation(
                tool_call_id="call-map",
                tool_name="locate_map",
                status="browser_execution_required",
                payload={"map_action": {}},
                is_terminal=True,
            )
        )

    context = PlanningGraphContext(project_context, decide, execute_tool)
    result = await build_planning_graph().ainvoke(
        {"principal_id": "p", "session_id": "s", "turn_id": "t", "trace_id": "tr"},
        context=context,
    )

    assert result["publication_kind"] == "browser_execution_required"
    assert context.latest_decision is decision


@pytest.mark.asyncio
async def test_planning_graph_stops_on_terminal_tool_error() -> None:
    decision = ControllerDecision(
        action="tool_call",
        tool="retrieve_kb",
        arguments={"query": "成都"},
        tool_call_id="call-1",
    )

    async def project_context():
        return object()

    async def decide(_projection):
        return decision

    async def execute_tool(_decision):
        return Outcome(terminal_error="retrieval_unavailable")

    context = PlanningGraphContext(project_context, decide, execute_tool)
    result = await build_planning_graph().ainvoke(
        {"principal_id": "p", "session_id": "s", "turn_id": "t", "trace_id": "tr"},
        context=context,
    )

    assert result["publication_kind"] == "retrieval_unavailable"


@pytest.mark.asyncio
async def test_planning_graph_owns_compose_answer_control_boundary() -> None:
    decision = ControllerDecision(
        action="compose_answer",
        arguments={"selected_evidence_ids": ["ev-1"]},
        tool_call_id="compose-1",
    )
    handled = []

    async def project_context():
        return {"evidence_ids": ["ev-1"]}

    async def decide(_projection):
        return decision

    async def execute_tool(_decision):  # pragma: no cover - control actions are not tools
        raise AssertionError("compose_answer must not enter tool execution")

    async def handle_control(control, projection):
        handled.append((control.action, projection))
        return "compose_answer"

    context = PlanningGraphContext(
        project_context=project_context,
        decide=decide,
        execute_tool=execute_tool,
        handle_control=handle_control,
    )
    result = await build_planning_graph().ainvoke(
        {"principal_id": "p", "session_id": "s", "turn_id": "t", "trace_id": "tr"},
        context=context,
    )

    assert result["publication_kind"] == "compose_answer"
    assert handled == [("compose_answer", {"evidence_ids": ["ev-1"]})]


@pytest.mark.asyncio
async def test_planning_graph_replans_internally_when_control_handler_rejects_compose() -> None:
    decisions = [
        ControllerDecision(
            action="compose_answer",
            arguments={"selected_evidence_ids": ["ev-too-large"]},
            tool_call_id="compose-1",
        ),
        ControllerDecision(
            action="compose_answer",
            arguments={"selected_evidence_ids": ["ev-1"]},
            tool_call_id="compose-2",
        ),
    ]
    projections = []
    handled = []

    async def project_context():
        projection = {"version": len(projections) + 1}
        projections.append(projection)
        return projection

    async def decide(_projection):
        return decisions.pop(0)

    async def execute_tool(_decision):  # pragma: no cover - control actions are not tools
        raise AssertionError("compose_answer must not enter tool execution")

    async def handle_control(control, projection):
        handled.append((control.tool_call_id, projection["version"]))
        if control.tool_call_id == "compose-1":
            return None
        return "compose_answer"

    context = PlanningGraphContext(
        project_context=project_context,
        decide=decide,
        execute_tool=execute_tool,
        handle_control=handle_control,
    )
    result = await build_planning_graph().ainvoke(
        {"principal_id": "p", "session_id": "s", "turn_id": "t", "trace_id": "tr"},
        context=context,
    )

    assert len(projections) == 2
    assert handled == [("compose-1", 1), ("compose-2", 2)]
    assert result["publication_kind"] == "compose_answer"


@pytest.mark.asyncio
async def test_planning_graph_finalizes_terminal_inside_graph() -> None:
    decision = ControllerDecision(
        action="compose_answer",
        arguments={"selected_evidence_ids": ["ev-1"]},
        tool_call_id="compose-1",
    )
    finalized = []

    async def project_context():
        return {"evidence_ids": ["ev-1"]}

    async def decide(_projection):
        return decision

    async def execute_tool(_decision):  # pragma: no cover - control actions are not tools
        raise AssertionError("compose_answer must not enter tool execution")

    async def handle_control(_control, _projection):
        return "compose_answer"

    async def finalize_terminal(kind, control, projection, tool_outcome):
        finalized.append((kind, control, projection, tool_outcome))
        return {"publication_state": "published"}

    context = PlanningGraphContext(
        project_context=project_context,
        decide=decide,
        execute_tool=execute_tool,
        handle_control=handle_control,
        finalize_terminal=finalize_terminal,
    )
    result = await build_planning_graph().ainvoke(
        {"principal_id": "p", "session_id": "s", "turn_id": "t", "trace_id": "tr"},
        context=context,
    )

    assert result["publication_kind"] == "compose_answer"
    assert context.terminal_result == {"publication_state": "published"}
    assert finalized == [
        ("compose_answer", decision, {"evidence_ids": ["ev-1"]}, None)
    ]


@pytest.mark.asyncio
async def test_compose_rejection_replans_inside_graph_without_runtime_restart() -> None:
    decisions = [
        ControllerDecision(
            action="compose_answer",
            arguments={"selected_evidence_ids": ["ev-too-large"]},
            tool_call_id="compose-1",
        ),
        ControllerDecision(
            action="compose_answer",
            arguments={"selected_evidence_ids": ["ev-1"]},
            tool_call_id="compose-2",
        ),
    ]
    projections = []
    handled = []

    async def project_context():
        projection = {"version": len(projections) + 1}
        projections.append(projection)
        return projection

    async def decide(_projection):
        return decisions.pop(0)

    async def execute_tool(_decision):  # pragma: no cover - control actions are not tools
        raise AssertionError("compose_answer must not enter tool execution")

    async def handle_control(control, _projection):
        handled.append(control.tool_call_id)
        if control.tool_call_id == "compose-1":
            return None
        return "compose_answer"

    context = PlanningGraphContext(
        project_context=project_context,
        decide=decide,
        execute_tool=execute_tool,
        handle_control=handle_control,
    )
    result = await build_planning_graph().ainvoke(
        {"principal_id": "p", "session_id": "s", "turn_id": "t", "trace_id": "tr"},
        context=context,
    )

    assert result["publication_kind"] == "compose_answer"
    assert len(projections) == 2
    assert handled == ["compose-1", "compose-2"]
