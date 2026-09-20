from __future__ import annotations

import pytest

from app.services.agent.controller import MainController
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
async def test_controller_returns_structured_tool_call_and_uses_controller_reasoning_policy() -> None:
    client = FakeModelClient(
        ModelResponse(
            content=(
                '{"tool_call_id":"call-1","name":"retrieve_kb",'
                '"arguments":{"query":"重庆滑坡监测","top_k":5}}'
            )
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

    assert decision.name == "retrieve_kb"
    assert decision.arguments["query"] == "重庆滑坡监测"
    assert client.calls[0].stage == "controller"
    assert client.calls[0].request_reasoning is True
    system_prompt = client.calls[0].messages[0]["content"]
    assert '"query"' in system_prompt
    assert '"type"' in system_prompt
    assert "compose_answer" in system_prompt


@pytest.mark.asyncio
async def test_controller_receives_working_evidence_catalog_for_semantic_decisions() -> None:
    client = FakeModelClient(
        ModelResponse(
            content=(
                '{"tool_call_id":"compose-1","name":"compose_answer",'
                '"arguments":{"evidence_ids":["ev-1"]}}'
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
