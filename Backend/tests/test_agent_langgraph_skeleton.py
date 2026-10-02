from __future__ import annotations

from app.services.agent.graph import build_planning_graph
from app.services.agent.graph.state import AgentGraphState


def test_graph_state_contains_references_not_duplicate_durable_business_state() -> None:
    annotations = AgentGraphState.__annotations__
    assert {"principal_id", "session_id", "turn_id", "trace_id", "question"} <= set(annotations)
    forbidden = {"session", "events", "evidence_ledger", "working_evidence", "frozen_evidence", "map_state", "browser_receipt"}
    assert forbidden.isdisjoint(annotations)


def test_production_langgraph_has_single_minimal_topology() -> None:
    graph = build_planning_graph().get_graph()
    node_names = set(graph.nodes)
    assert {"project_context", "plan", "execute_tool", "handle_control", "finalize_terminal"} <= node_names
    assert {"load_turn", "generate_answer", "review", "publish", "await_browser"}.isdisjoint(node_names)
