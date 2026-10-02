from __future__ import annotations

import pytest

from app.services.agent.controller import MainController
from app.services.agent.context.engine import ContextEngine
from app.services.agent.model_client import ModelResponse
from app.services.agent.stage_policy import LLMStagePolicy
from app.services.agent.tools import build_default_tool_registry


class FakeModelClient:
    def __init__(self, response: ModelResponse) -> None:
        self.response = response
        self.calls = []

    async def complete(self, request):
        self.calls.append(request)
        return self.response


@pytest.mark.asyncio
async def test_controller_actual_model_request_receives_authority_class_sections() -> None:
    client = FakeModelClient(
        ModelResponse(content='{"action":"direct_answer","answer":"收到"}')
    )
    controller = MainController(
        model_client=client,
        tool_registry=build_default_tool_registry(),
    )
    engine = ContextEngine()
    frame = engine.build_frame(
        session_id="session-authority",
        principal_id="admin:test",
        question="继续",
        events=(),
        working_evidence=(),
        metadata={
            "user_ui_selections": {
                "document": {"document_id": "14741", "title": "服务端权威标题"}
            },
            "client_hints": {
                "document_selection": {
                    "document_id": "untrusted-doc",
                    "admission_status": "rejected",
                }
            },
        },
        current_turn_id="turn-1",
    )
    projection, _ = engine.project_for_controller(
        frame,
        tool_contracts_text="",
        tool_names="",
    )

    await controller.decide(
        projection=projection,
        observations=(),
        stage_policy=LLMStagePolicy(False, True),
    )

    user_prompt = client.calls[0].messages[1]["content"]
    assert "User UI Selections" in user_prompt
    assert "14741" in user_prompt
    assert "服务端权威标题" in user_prompt
    assert "Client Hints" in user_prompt
    assert "untrusted-doc" in user_prompt
    assert "rejected" in user_prompt


@pytest.mark.asyncio
async def test_controller_returns_structured_tool_call_and_uses_controller_reasoning_policy() -> None:
    client = FakeModelClient(
        ModelResponse(
            content=None,
            tool_calls=(
                {
                    "name": "retrieve_kb",
                    "args": {"query": "重庆滑坡监测"},
                    "id": "call-1",
                    "type": "tool_call",
                },
            ),
        )
    )
    controller = MainController(
        model_client=client,
        tool_registry=build_default_tool_registry(),
    )

    decision = await controller.decide(
        question="重庆滑坡监测有什么要求？",
        context_summary="当前尚无证据",
        working_evidence=(),
        observations=(),
        stage_policy=LLMStagePolicy(True, True),
    )

    assert decision.action == "tool_call"
    assert decision.tool == "retrieve_kb"
    assert decision.arguments["query"] == "重庆滑坡监测"
    assert client.calls[0].stage == "controller"
    assert client.calls[0].request_reasoning is True
    system_prompt = client.calls[0].messages[0]["content"]
    assert "compose_answer" in system_prompt
    assert "input_schema=" not in system_prompt
    tool_schema_text = str(client.calls[0].tools)
    assert "retrieve_kb" in tool_schema_text
    assert "query" in tool_schema_text


@pytest.mark.asyncio
async def test_controller_prefers_native_model_tool_call_channel() -> None:
    client = FakeModelClient(
        ModelResponse(
            content=None,
            tool_calls=(
                {
                    "name": "retrieve_kb",
                    "args": {"query": "重庆滑坡监测"},
                    "id": "call-native-controller",
                    "type": "tool_call",
                },
            ),
        )
    )
    controller = MainController(
        model_client=client,
        tool_registry=build_default_tool_registry(),
    )

    decision = await controller.decide(
        question="重庆滑坡监测有什么要求？",
        context_summary="当前尚无证据",
        working_evidence=(),
        observations=(),
        stage_policy=LLMStagePolicy(False, True),
    )

    assert decision.action == "tool_call"
    assert decision.tool == "retrieve_kb"
    assert decision.arguments == {"query": "重庆滑坡监测"}
    assert decision.tool_call_id == "call-native-controller"
    assert client.calls[0].tools
    assert client.calls[0].response_schema is not None
    assert "retrieve_kb" not in str(client.calls[0].response_schema)


@pytest.mark.asyncio
async def test_controller_rejects_text_encoded_tool_call() -> None:
    client = FakeModelClient(
        ModelResponse(
            content='{"action":"tool_call","tool":"retrieve_kb","arguments":{"query":"重庆滑坡监测"}}'
        )
    )
    controller = MainController(
        model_client=client,
        tool_registry=build_default_tool_registry(),
    )

    with pytest.raises(ValueError, match="native tool-calling channel"):
        await controller.decide(
            question="重庆滑坡监测有什么要求？",
            context_summary="",
            working_evidence=(),
            observations=(),
            stage_policy=LLMStagePolicy(False, True),
        )


@pytest.mark.asyncio
async def test_controller_receives_working_evidence_catalog_for_semantic_decisions() -> None:
    client = FakeModelClient(
        ModelResponse(
            content=(
                '{"action":"compose_answer",'
                '"arguments":{"answer_kind":"knowledge_answer",'
                '"selected_evidence_ids":["ev-1"]}}'
            )
        )
    )
    controller = MainController(
        model_client=client,
        tool_registry=build_default_tool_registry(),
    )

    await controller.decide(
        question="有什么要求？",
        context_summary="",
        working_evidence=(
            {
                "evidence_id": "ev-1",
                "citation_id": "E1",
                "title": "规划标准",
                "excerpt": "重庆市滑坡监测应按本标准执行。",
            },
        ),
        observations=(),
        stage_policy=LLMStagePolicy(False, True),
    )

    user_prompt = client.calls[0].messages[1]["content"]
    assert "ev-1" in user_prompt
    assert "E1" in user_prompt
    assert "重庆市滑坡监测应按本标准执行" in user_prompt


@pytest.mark.asyncio
async def test_controller_model_request_exposes_publication_evidence_budget_and_item_costs() -> None:
    from app.services.agent.context.engine import ContextEngine

    client = FakeModelClient(
        ModelResponse(content='{"action":"direct_answer","answer":"ok"}')
    )
    controller = MainController(
        model_client=client,
        tool_registry=build_default_tool_registry(),
    )
    frame = ContextEngine().build_frame(
        session_id="budget-controller",
        principal_id="admin:test",
        question="继续",
        events=(),
        working_evidence=(
            {
                "evidence_id": "ev-budget-1",
                "citation_id": "E1",
                "title": "预算证据",
                "excerpt": "摘要",
                "publication_token_cost": 321,
            },
        ),
        current_turn_id="turn-1",
    )
    projection, _ = ContextEngine().project_for_controller(
        frame,
        tool_contracts_text="",
        tool_names="",
        publication_evidence_budget={
            "max_evidence_tokens": 900,
            "answer_context_limit": 5900,
            "reviewer_context_limit": 2000,
            "reviewer_enabled": True,
        },
    )

    await controller.decide(
        projection=projection,
        observations=(),
        stage_policy=LLMStagePolicy(False, True),
    )

    user_prompt = client.calls[0].messages[1]["content"]
    assert "Publication Evidence Budget" in user_prompt
    assert '"max_evidence_tokens": 900' in user_prompt
    assert '"publication_token_cost": 321' in user_prompt


@pytest.mark.asyncio
async def test_controller_rejects_non_tool_direct_answer_shape() -> None:
    client = FakeModelClient(
        ModelResponse(content='{"answer":"直接回答知识问题"}')
    )
    controller = MainController(
        model_client=client,
        tool_registry=build_default_tool_registry(),
    )

    with pytest.raises(ValueError, match="tool call"):
        await controller.decide(
            question="有什么要求？",
            context_summary="",
            working_evidence=(),
            observations=(),
            stage_policy=LLMStagePolicy(False, True),
        )
