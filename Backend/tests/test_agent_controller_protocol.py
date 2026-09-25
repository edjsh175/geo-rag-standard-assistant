"""Unit tests for GeoAI Controller Protocol, Executable Action Surface, and Direct Answer."""

from __future__ import annotations

import pytest

from app.services.agent.context.engine import ContextEngine, extract_previous_turn_runtime_facts
from app.services.agent.context.frame import ContextFrame
from app.services.agent.controller import MainController
from app.services.agent.controller_protocol import (
    CLARIFY_ACTION,
    COMPOSE_ANSWER_ACTION,
    DIRECT_ANSWER_ACTION,
    TOOL_CALL_ACTION,
    ControllerDecision,
    ExecutableActionState,
    build_controller_decision_schema,
    normalize_legacy_controller_wire,
    validate_controller_decision_payload,
)
from app.services.agent.events import AgentEvent
from app.services.agent.model_client import ModelResponse
from app.services.agent.runtime import AgentRunRequest, AgentRuntime
from app.services.agent.stage_policy import LLMStagePolicy
from app.services.agent.tools import build_default_tool_registry, executable_tool_names


class FakeModelClient:
    def __init__(self, response: ModelResponse) -> None:
        self.response = response
        self.calls = []

    async def complete(self, request):
        self.calls.append(request)
        return self.response


def test_executable_action_state_dynamic_surface():
    registry = build_default_tool_registry()

    # 1. 2D map ready with user vector layers
    map_context_2d = {
        "ready": True,
        "dimension": "2d",
        "supported_tools": [
            "locate_map",
            "set_layer_visibility",
            "import_vector_dataset",
            "set_vector_style",
            "fit_vector_layer",
            "inspect_layer_features",
            "get_feature_geometry",
        ],
    }
    state_2d = ExecutableActionState.compute(
        registry=registry,
        map_context=map_context_2d,
        identity_status="resolved",
    )
    assert "locate_map" in state_2d.available_capabilities
    assert "import_vector_dataset" in state_2d.available_capabilities
    assert "retrieve_kb" in state_2d.available_capabilities  # non-browser tool always kept
    assert DIRECT_ANSWER_ACTION in state_2d.available_control_actions
    assert COMPOSE_ANSWER_ACTION in state_2d.available_control_actions
    assert CLARIFY_ACTION not in state_2d.available_control_actions  # resolved identity

    # 2. 3D map ready: only supports locate_map and set_layer_visibility
    map_context_3d = {
        "ready": True,
        "dimension": "3d",
        "supported_tools": ["locate_map", "set_layer_visibility"],
    }
    state_3d = ExecutableActionState.compute(
        registry=registry,
        map_context=map_context_3d,
        identity_status="ambiguous",
    )
    assert "locate_map" in state_3d.available_capabilities
    assert "set_layer_visibility" in state_3d.available_capabilities
    assert "import_vector_dataset" not in state_3d.available_capabilities
    assert "set_vector_style" not in state_3d.available_capabilities
    assert CLARIFY_ACTION in state_3d.available_control_actions  # ambiguous identity exposed

    # 3. Map not ready: no browser tools
    map_context_not_ready = {"ready": False}
    state_not_ready = ExecutableActionState.compute(
        registry=registry,
        map_context=map_context_not_ready,
    )
    assert "locate_map" not in state_not_ready.available_capabilities
    assert "retrieve_kb" in state_not_ready.available_capabilities


def test_build_controller_decision_schema():
    registry = build_default_tool_registry()
    state = ExecutableActionState.compute(registry=registry)
    specs = registry.specs_for(state.available_capabilities)
    capability_schemas = {spec.name: spec.input_schema for spec in specs}

    schema = build_controller_decision_schema(
        capability_schemas=capability_schemas,
        allowed_control_actions=list(state.available_control_actions),
        allowed_answer_kinds=list(state.allowed_answer_kinds),
    )
    assert "oneOf" in schema
    actions_in_schema = {
        branch["properties"]["action"].get("const") for branch in schema["oneOf"]
    }
    assert COMPOSE_ANSWER_ACTION in actions_in_schema
    assert DIRECT_ANSWER_ACTION in actions_in_schema
    assert TOOL_CALL_ACTION in actions_in_schema


def test_validate_direct_answer_payload():
    registry = build_default_tool_registry()
    state = ExecutableActionState.compute(registry=registry)

    # Valid direct answer
    decision = validate_controller_decision_payload(
        {"action": "direct_answer", "answer": "这是关于刚才操作步骤的说明。"},
        state=state,
        registry=registry,
        tool_call_id="call-123",
    )
    assert decision.action == DIRECT_ANSWER_ACTION
    assert decision.answer == "这是关于刚才操作步骤的说明。"
    assert decision.name == DIRECT_ANSWER_ACTION
    assert decision.arguments == {}

    # Reject empty answer
    with pytest.raises(ValueError, match="answer must be a non-empty string"):
        validate_controller_decision_payload(
            {"action": "direct_answer", "answer": "   "},
            state=state,
            registry=registry,
            tool_call_id="call-123",
        )

    # Reject bare protocol token disguised as answer
    with pytest.raises(ValueError, match="bare protocol identifier"):
        validate_controller_decision_payload(
            {"action": "direct_answer", "answer": "retrieve_kb"},
            state=state,
            registry=registry,
            tool_call_id="call-123",
        )


def test_validate_compose_answer_payload():
    registry = build_default_tool_registry()
    state = ExecutableActionState.compute(registry=registry)

    # Valid compose_answer with explicit evidence ids
    decision = validate_controller_decision_payload(
        {
            "action": "compose_answer",
            "arguments": {
                "answer_kind": "knowledge_answer",
                "selected_evidence_ids": ["ev-1", "ev-2"],
                "answer_mode": "full",
            },
        },
        state=state,
        registry=registry,
        tool_call_id="compose-1",
    )
    assert decision.action == COMPOSE_ANSWER_ACTION
    assert decision.arguments["selected_evidence_ids"] == ["ev-1", "ev-2"]
    assert decision.arguments["evidence_ids"] == ["ev-1", "ev-2"]

    # Reject knowledge_answer without selected_evidence_ids
    with pytest.raises(ValueError, match="selected_evidence_ids must be a non-empty array"):
        validate_controller_decision_payload(
            {
                "action": "compose_answer",
                "arguments": {
                    "answer_kind": "knowledge_answer",
                    "selected_evidence_ids": [],
                },
            },
            state=state,
            registry=registry,
            tool_call_id="compose-1",
        )


def test_context_frame_role_projections():
    frame = ContextFrame.create(
        session={"session_id": "sess-1"},
        user_question="成都市青羊区规划指标",
        spatial={"dimension": "2d", "center": [104.06, 30.67]},
        conversation=[{"role": "user", "text": "成都市青羊区规划指标"}],
        working_evidence=[
            {"evidence_id": "ev-1", "citation_id": "E1", "title": "规划标准", "excerpt": "指标规定容积率"}
        ],
        runtime_facts={"dialogue_focus": "青羊区"},
    )

    # 1. for_controller
    proj_ctrl = frame.for_controller(
        tool_contracts_text="- retrieve_kb",
        tool_names="retrieve_kb",
        available_capabilities=("retrieve_kb",),
        available_control_actions=("compose_answer", "direct_answer"),
    )
    assert proj_ctrl.user_question == "成都市青羊区规划指标"
    assert "user: 成都市青羊区规划指标" in proj_ctrl.conversation_text
    assert len(proj_ctrl.working_evidence) == 1
    assert "retrieve_kb" in proj_ctrl.available_capabilities

    # 2. for_retrieval
    proj_retrieval = frame.for_retrieval(resolved_query="成都市青羊区控制性详细规划指标")
    assert proj_retrieval.resolved_query == "成都市青羊区控制性详细规划指标"
    assert proj_retrieval.semantic_context == "青羊区"

    # 3. for_answer
    proj_answer = frame.for_answer(resolved_goal="说明青羊区规划指标")
    assert proj_answer.resolved_goal == "说明青羊区规划指标"
    assert len(proj_answer.citable_evidence) == 1

    # 4. for_reviewer
    proj_reviewer = frame.for_reviewer(candidate_answer="青羊区容积率指标如下...")
    assert proj_reviewer.candidate_answer == "青羊区容积率指标如下..."
    assert len(proj_reviewer.citable_evidence) == 1


def test_previous_turn_runtime_facts_extraction():
    events = [
        AgentEvent(event_type="user_message", session_id="s1", turn_id="t1", payload={"text": "你好"}),
        AgentEvent(event_type="controller_decision", session_id="s1", turn_id="t1", payload={"action": "locate_map", "tool_name": "locate_map"}),
        AgentEvent(event_type="tool_started", session_id="s1", turn_id="t1", payload={"tool_name": "locate_map", "tool_call_id": "c1"}),
        AgentEvent(event_type="tool_completed", session_id="s1", turn_id="t1", payload={"tool_name": "locate_map", "tool_call_id": "c1", "status": "ok"}),
        AgentEvent(event_type="publication_completed", session_id="s1", turn_id="t1", payload={"state": "grounded"}),
    ]
    facts = extract_previous_turn_runtime_facts(events)
    assert facts["turn_id"] == "t1"
    assert facts["controller_actions"] == ["locate_map"]
    assert len(facts["tool_calls"]) == 1
    assert facts["tool_calls"][0]["status"] == "ok"
    assert facts["publication_state"] == "grounded"


@pytest.mark.asyncio
async def test_runtime_executes_direct_answer_action():
    client = FakeModelClient(
        ModelResponse(content='{"action":"direct_answer","answer":"我刚才已经将地图定位到天府广场。"}')
    )
    controller = MainController(
        model_client=client,
        tool_registry=build_default_tool_registry(),
    )
    from app.services.agent.session import InMemoryAgentSessionStore

    runtime = AgentRuntime(
        controller=controller,
        retrieval_port=None,
        session_store=InMemoryAgentSessionStore(),
        answer_generator=None,
    )
    result = await runtime.run(
        AgentRunRequest(question="你刚才做了什么？", session_id="s1", principal_id="u1")
    )
    assert result.publication_state == "published"
    assert result.answer.answer == "我刚才已经将地图定位到天府广场。"
    assert result.published_result.visible_text == "我刚才已经将地图定位到天府广场。"
    assert result.frozen_evidence is None
    # Verify events include controller_decision and publication_completed
    event_types = [ev.event_type for ev in result.events]
    assert "controller_decision" in event_types
    assert "publication_completed" in event_types
    assert "tool_started" not in event_types  # direct_answer does not start a tool
