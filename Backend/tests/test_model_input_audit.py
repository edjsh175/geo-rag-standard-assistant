from __future__ import annotations

import pytest

from app.services.agent.answer_generator import AnswerGenerator
from app.services.agent.context.engine import ContextEngine
from app.services.agent.contracts import EvidenceItem, FrozenEvidenceSnapshot
from app.services.agent.controller import MainController
from app.services.agent.controller_protocol import ExecutableActionState
from app.services.agent.model_client import (
    LLMConfigStageModelClient,
    ModelRequest,
    build_model_input_audit_record,
    model_request_messages_hash,
)
from app.services.agent.stage_policy import LLMStagePolicy
from app.services.agent.store import InMemoryAgentStore
from app.services.agent.tools import build_default_tool_registry
from app.services.agent.reviewer import GroundingReviewer


@pytest.mark.asyncio
async def test_controller_provider_messages_match_persisted_model_input_audit_hash() -> None:
    class FakeLLMConfig:
        supports_reasoning = False

        def __init__(self) -> None:
            self.calls = []

        async def chat_completion(self, **kwargs):
            self.calls.append(kwargs)
            return '{"action":"direct_answer","answer":"ok"}'

    class FakeBoundModel:
        async def ainvoke(self, messages):
            from langchain_core.messages import AIMessage
            llm.calls.append({"messages": messages})
            return AIMessage(content='{"action":"direct_answer","answer":"ok"}')

    class FakeChatModel:
        def __init__(self, **kwargs):
            pass

        def bind_tools(self, tools, **kwargs):
            return FakeBoundModel()

    store = InMemoryAgentStore()
    llm = FakeLLMConfig()
    client = LLMConfigStageModelClient(
        llm,
        audit_sink=store.save_model_input_audit,
        chat_model_factory=FakeChatModel,
    )
    registry = build_default_tool_registry()
    controller = MainController(model_client=client, tool_registry=registry)
    engine = ContextEngine()
    frame = engine.build_frame(
        session_id="sess-audit",
        principal_id="user-audit",
        question="你好",
        events=(),
        working_evidence=(),
        current_turn_id="turn-1",
    )
    action_state = ExecutableActionState.compute(
        registry=registry,
        map_context=None,
        identity_resolution=None,
        has_evidence=False,
        selectable_evidence_ids=(),
        provider_health={},
    )
    projection, snapshot = engine.project_for_controller(
        frame,
        tool_contracts_text="",
        tool_names="",
        available_capabilities=tuple(action_state.available_capabilities),
        available_control_actions=tuple(action_state.available_control_actions),
    )

    await controller.decide(
        projection=projection,
        action_state=action_state,
        observations=(),
        stage_policy=LLMStagePolicy(False, False),
        audit_context={
            "principal_id": "user-audit",
            "session_id": "sess-audit",
            "turn_id": "turn-1",
            "context_snapshot_id": snapshot.snapshot_id,
        },
    )

    rows = await store.list_model_input_audits(
        "user-audit",
        "sess-audit",
        "turn-1",
    )
    assert len(rows) == 1
    provider_messages = tuple(
        {"role": item["role"], "content": item["content"]}
        for item in llm.calls[0]["messages"]
    )
    assert rows[0].messages_hash == model_request_messages_hash(provider_messages)
    assert rows[0].context_snapshot_id == snapshot.snapshot_id
    assert rows[0].action_surface_hash
    assert rows[0].tool_contract_hash


@pytest.mark.asyncio
async def test_answer_and_reviewer_audits_bind_exact_frozen_snapshot() -> None:
    class FakeLLMConfig:
        supports_reasoning = False

        def __init__(self) -> None:
            self.calls = []
            self.responses = [
                '{"kind":"knowledge_answer","units":[{"unit_id":"u1","text":"事实","citations":["E1"]}]}',
                '{"verdict":"SUPPORTED","findings":[{"unit_id":"u1","status":"SUPPORTED","citations":["E1"]}]}',
            ]

        async def chat_completion(self, **kwargs):
            self.calls.append(kwargs)
            return self.responses.pop(0)

    store = InMemoryAgentStore()
    llm = FakeLLMConfig()
    client = LLMConfigStageModelClient(llm, audit_sink=store.save_model_input_audit)
    generator = AnswerGenerator(model_client=client)
    reviewer = GroundingReviewer(model_client=client)
    snapshot = FrozenEvidenceSnapshot(
        snapshot_id="frozen-1",
        session_id="sess-audit",
        turn_id="turn-1",
        items=(
            EvidenceItem(
                evidence_id="ev-1",
                citation_id="E1",
                session_id="sess-audit",
                first_turn_id="turn-1",
                chunk_id="chunk-1",
                document_id="doc-1",
                text="事实依据",
                title="依据",
                score=1.0,
                metadata={},
                source="kb",
                match_type="hybrid",
                content_hash="hash-1",
            ),
        ),
    )
    policy = LLMStagePolicy(False, False)
    audit_context = {
        "principal_id": "user-audit",
        "session_id": "sess-audit",
        "turn_id": "turn-1",
        "context_snapshot_id": "context-answer",
    }

    answer = await generator.generate(
        question="事实是什么？",
        snapshot=snapshot,
        stage_policy=policy,
        audit_context=audit_context,
    )
    await reviewer.review(
        question="事实是什么？",
        answer=answer,
        snapshot=snapshot,
        stage_policy=policy,
        audit_context={**audit_context, "context_snapshot_id": "context-reviewer"},
    )

    rows = await store.list_model_input_audits("user-audit", "sess-audit", "turn-1")
    assert [row.stage for row in rows] == ["answer_generation", "reviewer"]
    assert [row.frozen_evidence_snapshot_id for row in rows] == ["frozen-1", "frozen-1"]
    assert rows[0].context_snapshot_id == "context-answer"
    assert rows[1].context_snapshot_id == "context-reviewer"
    for row, call in zip(rows, llm.calls):
        provider_messages = tuple(
            {"role": item["role"], "content": item["content"]}
            for item in call["messages"]
        )
        assert row.messages_hash == model_request_messages_hash(provider_messages)


def test_model_input_audit_identity_is_scoped_beyond_call_id_and_attempt() -> None:
    base = dict(
        stage="controller",
        messages=({"role": "user", "content": "prompt"},),
        call_id="reused-call-id",
        attempt=1,
    )
    first = build_model_input_audit_record(
        ModelRequest(
            **base,
            audit_context={
                "principal_id": "user-audit",
                "session_id": "sess-audit",
                "turn_id": "turn-1",
            },
        )
    )
    second = build_model_input_audit_record(
        ModelRequest(
            **base,
            audit_context={
                "principal_id": "user-audit",
                "session_id": "sess-audit",
                "turn_id": "turn-2",
            },
        )
    )

    assert first.audit_id != second.audit_id
