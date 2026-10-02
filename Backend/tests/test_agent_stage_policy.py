from __future__ import annotations

import pytest

from app.services.agent.model_client import (
    LLMConfigStageModelClient,
    ModelRequest,
    model_request_messages_hash,
)
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
    assert llm.calls[0]["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_production_model_adapter_requests_json_for_every_structured_stage() -> None:
    class FakeLLMConfig:
        supports_reasoning = False

        def __init__(self) -> None:
            self.calls = []

        async def chat_completion(self, **kwargs):
            self.calls.append(kwargs)
            return "{}"

    llm = FakeLLMConfig()
    client = LLMConfigStageModelClient(llm)

    for stage in ("controller", "answer_generation", "reviewer"):
        await client.complete(
            ModelRequest(
                stage=stage,
                messages=({"role": "user", "content": "问题"},),
            )
        )

    assert [call["response_format"] for call in llm.calls] == [
        {"type": "json_object"},
        {"type": "json_object"},
        {"type": "json_object"},
    ]


@pytest.mark.asyncio
async def test_resolved_main_model_identity_stays_stable_across_stages() -> None:
    class FakeLLMConfig:
        supports_reasoning = True

        def __init__(self) -> None:
            self.calls = []

        def resolve_main_model(self, *, thinking: bool) -> str:
            return "reasoning-main" if thinking else "default-main"

        async def chat_completion(self, **kwargs):
            self.calls.append(kwargs)
            return "{}"

    llm = FakeLLMConfig()
    client = LLMConfigStageModelClient(llm)
    model_name = client.resolve_main_model(thinking=True)

    await client.complete(
        ModelRequest(
            stage="controller",
            messages=({"role": "user", "content": "问题"},),
            request_reasoning=True,
            model_name=model_name,
        )
    )
    await client.complete(
        ModelRequest(
            stage="answer_generation",
            messages=({"role": "user", "content": "问题"},),
            request_reasoning=False,
            model_name=model_name,
        )
    )

    assert [call["model"] for call in llm.calls] == ["reasoning-main", "reasoning-main"]
    assert [call["request_reasoning"] for call in llm.calls] == [True, False]


@pytest.mark.asyncio
async def test_model_input_audit_hashes_the_exact_request_before_provider_call() -> None:
    class FakeLLMConfig:
        supports_reasoning = False

        def __init__(self) -> None:
            self.provider_calls = 0

        async def chat_completion(self, **kwargs):
            self.provider_calls += 1
            return "{}"

    saved = []
    llm = FakeLLMConfig()

    async def audit_sink(record):
        assert llm.provider_calls == 0
        saved.append(record)

    client = LLMConfigStageModelClient(llm, audit_sink=audit_sink)
    request = ModelRequest(
        stage="controller",
        messages=(
            {"role": "system", "content": "system contract"},
            {"role": "user", "content": "actual prompt"},
        ),
        request_reasoning=True,
        model_name="main-model",
        temperature=0.1,
        call_id="call-audit-1",
        attempt=2,
        timeout_seconds=9.5,
        response_schema={"type": "object"},
        audit_context={
            "principal_id": "admin:test",
            "session_id": "session-audit",
            "turn_id": "turn-7",
            "context_snapshot_id": "snap-controller",
            "action_surface_hash": "action-hash",
            "tool_contract_hash": "tool-hash",
        },
    )

    await client.complete(request)

    assert len(saved) == 1
    record = saved[0]
    assert record.audit_id.startswith("mai-")
    assert record.messages_hash == model_request_messages_hash(request.messages)
    assert record.principal_id == "admin:test"
    assert record.session_id == "session-audit"
    assert record.turn_id == "turn-7"
    assert record.context_snapshot_id == "snap-controller"
    assert record.action_surface_hash == "action-hash"
    assert record.tool_contract_hash == "tool-hash"
    assert record.attempt == 2
    assert record.model_name == "main-model"
    assert record.request_reasoning is True
    assert record.response_schema_hash
    assert len(record.messages_section_hashes) == 2
    assert llm.provider_calls == 1


@pytest.mark.asyncio
async def test_model_input_audit_requires_call_id_when_audit_context_is_present() -> None:
    class FakeLLMConfig:
        supports_reasoning = False

        async def chat_completion(self, **kwargs):
            raise AssertionError("provider must not be called for unauditable request")

    async def audit_sink(record):
        raise AssertionError("invalid audit record must not be persisted")

    client = LLMConfigStageModelClient(FakeLLMConfig(), audit_sink=audit_sink)

    with pytest.raises(ValueError, match="call_id"):
        await client.complete(
            ModelRequest(
                stage="controller",
                messages=({"role": "user", "content": "prompt"},),
                audit_context={
                    "principal_id": "admin:test",
                    "session_id": "session-audit",
                    "turn_id": "turn-1",
                },
            )
        )


@pytest.mark.asyncio
async def test_json_schema_timeout_does_not_downgrade_to_json_object(monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    class FakeLLMConfig:
        supports_reasoning = False

        def __init__(self) -> None:
            self.calls = []

        async def chat_completion(self, **kwargs):
            self.calls.append(kwargs)
            raise TimeoutError("upstream timed out")

    llm = FakeLLMConfig()
    client = LLMConfigStageModelClient(llm)

    with pytest.raises(TimeoutError, match="upstream timed out"):
        await client.complete(
            ModelRequest(
                stage="controller",
                messages=({"role": "user", "content": "prompt"},),
                model_name="main-model",
                response_schema={"type": "object"},
            )
        )

    assert len(llm.calls) == 1
    assert llm.calls[0]["response_format"]["type"] == "json_schema"


@pytest.mark.asyncio
async def test_json_schema_capability_rejection_downgrades_once(monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    class SchemaCapabilityError(RuntimeError):
        status_code = 400
        code = "unsupported_response_format"

    class FakeLLMConfig:
        supports_reasoning = False

        def __init__(self) -> None:
            self.calls = []

        async def chat_completion(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                raise SchemaCapabilityError("json_schema response_format is not supported")
            return "{}"

    llm = FakeLLMConfig()
    client = LLMConfigStageModelClient(llm)

    await client.complete(
        ModelRequest(
            stage="controller",
            messages=({"role": "user", "content": "prompt"},),
            model_name="main-model",
            response_schema={"type": "object"},
        )
    )

    assert [call["response_format"]["type"] for call in llm.calls] == [
        "json_schema",
        "json_object",
    ]


@pytest.mark.asyncio
async def test_adapter_sends_the_resolved_model_identity_to_provider() -> None:
    class FakeLLMConfig:
        supports_reasoning = False

        def __init__(self) -> None:
            self.calls = []

        def resolve_main_model(self, *, thinking: bool) -> str:
            return "resolved-main"

        async def chat_completion(self, **kwargs):
            self.calls.append(kwargs)
            return "{}"

    llm = FakeLLMConfig()
    client = LLMConfigStageModelClient(llm)

    await client.complete(
        ModelRequest(
            stage="answer_generation",
            messages=({"role": "user", "content": "prompt"},),
            model_name=None,
        )
    )

    assert llm.calls[0]["model"] == "resolved-main"


@pytest.mark.asyncio
async def test_model_client_uses_native_tool_call_channel_when_tools_are_bound() -> None:
    from langchain_core.messages import AIMessage

    class FakeLLMConfig:
        supports_reasoning = False

    class FakeBoundModel:
        async def ainvoke(self, messages):
            factory.invocations.append(messages)
            return AIMessage(
                content="",
                tool_calls=[{
                    "name": "retrieve_kb",
                    "args": {"query": "重庆滑坡监测"},
                    "id": "call-native-1",
                    "type": "tool_call",
                }],
            )

    class FakeChatModel:
        def __init__(self, **kwargs):
            factory.model_kwargs.append(kwargs)

        def bind_tools(self, tools, **kwargs):
            factory.bind_calls.append((tools, kwargs))
            return FakeBoundModel()

    class FakeFactory:
        def __init__(self):
            self.model_kwargs = []
            self.bind_calls = []
            self.invocations = []

        def __call__(self, **kwargs):
            return FakeChatModel(**kwargs)

    llm = FakeLLMConfig()
    factory = FakeFactory()
    client = LLMConfigStageModelClient(llm, chat_model_factory=factory)
    tools = (
        {
            "type": "function",
            "function": {
                "name": "retrieve_kb",
                "description": "search knowledge base",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        },
    )

    response = await client.complete(
        ModelRequest(
            stage="controller",
            messages=({"role": "user", "content": "问题"},),
            tools=tools,
        )
    )

    assert response.content is None
    assert response.tool_calls[0]["name"] == "retrieve_kb"
    assert response.tool_calls[0]["args"] == {"query": "重庆滑坡监测"}
    assert factory.bind_calls[0][0] == list(tools)
    assert factory.bind_calls[0][1]["tool_choice"] == "auto"
    assert factory.bind_calls[0][1]["parallel_tool_calls"] is False
    assert factory.invocations[0] == [{"role": "user", "content": "问题"}]
