from __future__ import annotations

import pytest

from app.services.agent.model_client import LLMConfigStageModelClient, ModelRequest
from app.services.agent.stage_policy import LLMStagePolicy


def test_reasoning_policy_is_stage_specific() -> None:
    policy = LLMStagePolicy(
        user_thinking=True,
        endpoint_supports_reasoning=True,
    )

    assert policy.for_stage("controller").request_reasoning is True
    assert policy.for_stage("answer_generation").request_reasoning is False
    assert policy.for_stage("reviewer").request_reasoning is False


def test_controller_reasoning_requires_both_user_intent_and_endpoint_capability() -> None:
    assert LLMStagePolicy(
        user_thinking=False,
        endpoint_supports_reasoning=True,
    ).for_stage("controller").request_reasoning is False
    assert LLMStagePolicy(
        user_thinking=True,
        endpoint_supports_reasoning=False,
    ).for_stage("controller").request_reasoning is False


def test_answer_and_reviewer_reasoning_stay_off_even_when_user_thinking_is_on() -> None:
    policy = LLMStagePolicy(
        user_thinking=True,
        endpoint_supports_reasoning=True,
    )

    assert policy.for_stage("answer_generation").request_reasoning is False
    assert policy.for_stage("reviewer").request_reasoning is False


@pytest.mark.asyncio
async def test_production_model_adapter_uses_declared_reasoning_capability() -> None:
    class FakeLLMConfig:
        supports_reasoning = True

        def __init__(self) -> None:
            self.calls = []

        async def chat_completion(self, **kwargs):
            self.calls.append(kwargs)
            return '{"name":"clarify"}'

    llm = FakeLLMConfig()
    client = LLMConfigStageModelClient(llm)

    assert client.supports_reasoning is True
    await client.complete(
        ModelRequest(
            stage="controller",
            messages=({"role": "user", "content": "问题"},),
            request_reasoning=True,
        )
    )

    assert llm.calls[0]["request_reasoning"] is True


@pytest.mark.asyncio
async def test_production_model_adapter_keeps_answer_stage_reasoning_off() -> None:
    class FakeLLMConfig:
        supports_reasoning = True

        def __init__(self) -> None:
            self.calls = []

        async def chat_completion(self, **kwargs):
            self.calls.append(kwargs)
            return "{}"

    llm = FakeLLMConfig()
    client = LLMConfigStageModelClient(llm)
    await client.complete(
        ModelRequest(
            stage="answer_generation",
            messages=({"role": "user", "content": "问题"},),
            request_reasoning=False,
        )
    )

    assert llm.calls[0]["request_reasoning"] is False
