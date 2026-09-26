from __future__ import annotations

import importlib
import importlib.util
from dataclasses import replace

import pytest

import app.models.agent_context as agent_context_models
from app.services.agent.context import ContextEngine
from app.services.agent.events import AgentEvent
from app.services.agent.model_client import ModelResponse
from app.services.agent.runtime import AgentRunRequest, AgentRuntime
from app.services.agent.stage_policy import LLMStagePolicy
from app.services.agent.store import InMemoryAgentStore
from app.services.agent.tool_runtime import ToolCall


def _conversation_memory_module():
    spec = importlib.util.find_spec("app.services.agent.conversation_memory")
    assert spec is not None, "conversation memory module is missing"
    return importlib.import_module("app.services.agent.conversation_memory")


def _memory_record_type():
    record_type = getattr(agent_context_models, "ConversationMemoryStateRecord", None)
    assert record_type is not None, "ConversationMemoryStateRecord is missing"
    return record_type


def _event(
    sequence: int,
    event_type: str,
    *,
    turn_id: str,
    text: str | None = None,
    payload: dict | None = None,
) -> AgentEvent:
    body = dict(payload or {})
    if text is not None:
        body["text"] = text
    return AgentEvent(
        event_type=event_type,
        session_id="session-memory",
        turn_id=turn_id,
        event_id=f"ev-{sequence}",
        sequence=sequence,
        payload=body,
    )


def test_conversation_memory_plans_old_prefix_and_extracts_only_durable_authority() -> None:
    module = _conversation_memory_module()

    class FixedEstimator:
        def estimate(self, text: str) -> int:
            return 20 if text else 0

    events = [
        _event(
            1,
            "user_message",
            turn_id="turn-1",
            text="old user constraint",
            payload={
                "user_ui_selections": {
                    "document": {"document_id": "doc-1", "title": "Selected"}
                }
            },
        ),
        _event(2, "assistant_message", turn_id="turn-1", text="old assistant reply"),
        _event(
            3,
            "browser_tool_completed",
            turn_id="turn-1",
            payload={
                "tool_name": "locate_map",
                "status": "succeeded",
                "effect": {"status": "applied", "state_revision": 7},
            },
        ),
        _event(4, "user_message", turn_id="turn-2", text="newer user message"),
        _event(5, "assistant_message", turn_id="turn-2", text="newer assistant reply"),
        _event(6, "user_message", turn_id="turn-3", text="current question"),
    ]

    planner = module.ConversationMemoryPlanner(
        estimator=FixedEstimator(),
        controller_context_tokens=100,
    )
    plan = planner.plan(
        events=events,
        current_turn_id="turn-3",
        previous=None,
    )

    assert plan.should_summarize is True
    assert [event.sequence for event in plan.events_to_summarize] == [1, 2, 4]
    assert [event.sequence for event in plan.recent_events] == [5]
    assert [event.sequence for event in plan.all_source_events] == [1, 2, 3, 4]

    facts = module.extract_authoritative_memory_facts(plan.all_source_events)
    assert facts["explicit_ui_selections"] == {
        "document": {"document_id": "doc-1", "title": "Selected"}
    }
    assert facts["authoritative_runtime_facts"] == {
        "last_browser_effect": {
            "event_id": "ev-3",
            "turn_id": "turn-1",
            "tool_name": "locate_map",
            "status": "succeeded",
            "effect": {"status": "applied", "state_revision": 7},
        }
    }


@pytest.mark.asyncio
async def test_conversation_memory_summarizer_keeps_llm_output_non_authoritative() -> None:
    module = _conversation_memory_module()

    class FakeModelClient:
        def __init__(self) -> None:
            self.calls = []

        async def complete(self, request):
            self.calls.append(request)
            return ModelResponse(
                content=(
                    '{"rolling_summary":"用户正在完善规划查询流程。",'
                    '"active_goal":"继续规划查询",'
                    '"user_constraints":["只使用已选文档"]}'
                )
            )

    events = (
        _event(1, "user_message", turn_id="turn-1", text="只使用已选文档"),
        _event(2, "assistant_message", turn_id="turn-1", text="明白"),
    )
    client = FakeModelClient()
    summarizer = module.ConversationMemorySummarizer(model_client=client)
    facts = {
        "explicit_ui_selections": {"document": {"document_id": "doc-1"}},
        "authoritative_runtime_facts": {
            "last_browser_effect": {"effect": {"state_revision": 3}}
        },
    }

    record = await summarizer.summarize(
        principal_id="user-memory",
        session_id="session-memory",
        turn_id="turn-2",
        events_to_summarize=events,
        all_source_events=events,
        previous=None,
        authoritative_facts=facts,
        stage_policy=LLMStagePolicy(False, False),
        model_name="main-model",
    )

    assert "NON-AUTHORITATIVE" in client.calls[0].messages[0]["content"]
    assert record.summary_version == 1
    assert record.covered_from_sequence == 1
    assert record.covered_to_sequence == 2
    assert record.source_event_ids == ("ev-1", "ev-2")
    assert record.explicit_ui_selections == facts["explicit_ui_selections"]
    assert record.authoritative_runtime_facts == facts["authoritative_runtime_facts"]
    assert client.calls[0].stage == "conversation_memory"
    assert client.calls[0].audit_context["turn_id"] == "turn-2"

    other_principal = await summarizer.summarize(
        principal_id="user-memory-other",
        session_id="session-memory",
        turn_id="turn-2",
        events_to_summarize=events,
        all_source_events=events,
        previous=None,
        authoritative_facts=facts,
        stage_policy=LLMStagePolicy(False, False),
        model_name="main-model",
    )
    assert other_principal.memory_id != record.memory_id


@pytest.mark.asyncio
async def test_conversation_memory_identity_is_scoped_by_principal_and_session() -> None:
    module = _conversation_memory_module()

    class FakeModelClient:
        async def complete(self, request):
            return ModelResponse(
                content=(
                    '{"rolling_summary":"summary",'
                    '"active_goal":"goal","user_constraints":[]}'
                )
            )

    summarizer = module.ConversationMemorySummarizer(model_client=FakeModelClient())
    events = (
        _event(1, "user_message", turn_id="turn-1", text="old user"),
        _event(2, "assistant_message", turn_id="turn-1", text="old assistant"),
    )
    kwargs = dict(
        session_id="shared-session-id",
        turn_id="turn-2",
        events_to_summarize=events,
        all_source_events=events,
        previous=None,
        authoritative_facts={
            "explicit_ui_selections": {},
            "authoritative_runtime_facts": {},
        },
        stage_policy=LLMStagePolicy(False, False),
        model_name=None,
    )

    first = await summarizer.summarize(principal_id="user-a", **kwargs)
    second = await summarizer.summarize(principal_id="user-b", **kwargs)

    assert first.memory_id != second.memory_id


@pytest.mark.asyncio
async def test_in_memory_store_versions_conversation_memory_without_overwrite() -> None:
    record_type = _memory_record_type()
    store = InMemoryAgentStore()
    assert hasattr(store, "save_conversation_memory")
    assert hasattr(store, "get_latest_conversation_memory")

    first = record_type(
        memory_id="memory-1",
        principal_id="user-memory",
        session_id="session-memory",
        summary_version=1,
        covered_from_sequence=1,
        covered_to_sequence=4,
        rolling_summary="summary-v1",
        active_goal="goal",
        user_constraints=("constraint",),
        explicit_ui_selections={},
        authoritative_runtime_facts={},
        source_event_ids=("ev-1", "ev-2"),
        source_hash="hash-v1",
    )
    second = replace(
        first,
        memory_id="memory-2",
        summary_version=2,
        covered_to_sequence=8,
        rolling_summary="summary-v2",
        source_hash="hash-v2",
    )

    await store.save_conversation_memory(first)
    await store.save_conversation_memory(second)
    assert await store.get_latest_conversation_memory(
        "user-memory", "session-memory"
    ) == second

    with pytest.raises(RuntimeError, match="version conflict"):
        await store.save_conversation_memory(
            replace(second, rolling_summary="conflicting-v2")
        )


def test_context_engine_projects_memory_summary_plus_only_uncovered_recent_dialogue() -> None:
    record_type = _memory_record_type()
    memory = record_type(
        memory_id="memory-1",
        principal_id="user-memory",
        session_id="session-memory",
        summary_version=1,
        covered_from_sequence=1,
        covered_to_sequence=2,
        rolling_summary="用户长期目标：完成规划核查。",
        active_goal="规划核查",
        user_constraints=("只使用已选文档",),
        explicit_ui_selections={"document": {"document_id": "doc-1"}},
        authoritative_runtime_facts={},
        source_event_ids=("ev-1", "ev-2"),
        source_hash="hash-v1",
    )
    events = [
        _event(1, "user_message", turn_id="turn-1", text="old user"),
        _event(2, "assistant_message", turn_id="turn-1", text="old assistant"),
        _event(3, "user_message", turn_id="turn-2", text="recent user"),
        _event(4, "assistant_message", turn_id="turn-2", text="recent assistant"),
        _event(5, "user_message", turn_id="turn-3", text="current question"),
    ]

    engine = ContextEngine()
    frame = engine.build_frame(
        session_id="session-memory",
        principal_id="user-memory",
        question="current question",
        events=events,
        current_turn_id="turn-3",
        working_evidence=[],
        conversation_memory=memory,
    )
    projection, _ = engine.project_for_controller(
        frame,
        tool_contracts_text="",
        tool_names="",
    )

    assert [item["text"] for item in frame.conversation] == [
        "recent user",
        "recent assistant",
    ]
    assert "用户长期目标：完成规划核查。" in projection.conversation_text
    assert "recent user" in projection.conversation_text
    assert "old user" not in projection.conversation_text
    assert frame.conversation_memory["summary_version"] == 1


def test_historical_memory_selection_does_not_impersonate_current_ui_state() -> None:
    record_type = _memory_record_type()
    memory = record_type(
        memory_id="memory-ui-1",
        principal_id="user-memory",
        session_id="session-memory",
        summary_version=1,
        covered_from_sequence=1,
        covered_to_sequence=2,
        rolling_summary="用户之前选择过一个文档。",
        active_goal="继续处理文档",
        user_constraints=(),
        explicit_ui_selections={"document": {"document_id": "doc-old"}},
        authoritative_runtime_facts={},
        source_event_ids=("ev-1", "ev-2"),
        source_hash="hash-ui-1",
    )

    frame = ContextEngine().build_frame(
        session_id="session-memory",
        principal_id="user-memory",
        question="继续",
        events=(),
        current_turn_id="turn-2",
        working_evidence=[],
        metadata={},
        conversation_memory=memory,
    )

    assert frame.user_ui_selections == {}
    assert frame.conversation_memory["explicit_ui_selections"] == {
        "document": {"document_id": "doc-old"}
    }


def test_conversation_memory_semantic_payload_is_strictly_bounded() -> None:
    module = _conversation_memory_module()

    with pytest.raises(ValueError, match="rolling_summary"):
        module.ConversationMemorySummarizer._parse(
            '{"rolling_summary":"' + ("长" * 501) + '","active_goal":"g","user_constraints":[]}'
        )
    with pytest.raises(ValueError, match="active_goal"):
        module.ConversationMemorySummarizer._parse(
            '{"rolling_summary":"s","active_goal":"'
            + ("长" * 121)
            + '","user_constraints":[]}'
        )
    with pytest.raises(ValueError, match="user_constraints"):
        module.ConversationMemorySummarizer._parse(
            '{"rolling_summary":"s","active_goal":"g","user_constraints":'
            + str(["x"] * 7).replace("'", '"')
            + "}"
        )


def test_conversation_memory_stage_has_small_non_blocking_deadline() -> None:
    policy = LLMStagePolicy(
        user_thinking=True,
        endpoint_supports_reasoning=True,
    ).for_stage("conversation_memory")

    assert policy.request_reasoning is False
    assert policy.timeout_seconds <= 12.0


class _EmptyRetrievalPort:
    async def retrieve(self, query):
        raise AssertionError("direct answer test must not retrieve")

    async def fetch_chunks(self, chunk_ids):
        return []


class _CapturingDirectController:
    def __init__(self) -> None:
        self.projections = []

    async def decide(self, **kwargs):
        self.projections.append(kwargs.get("projection"))
        return ToolCall(
            tool_call_id="direct-memory",
            name="direct_answer",
            arguments={"answer": "ok"},
        )


async def _seed_long_dialogue(store: InMemoryAgentStore) -> None:
    for index in range(1, 6):
        turn_id = await store.allocate_turn_id(
            "user-memory", "session-memory-runtime"
        )
        user_payload = {"text": f"旧用户约束{index}-" + ("规划" * 500)}
        if index == 1:
            user_payload["user_ui_selections"] = {
                "document": {"document_id": "doc-old", "title": "旧选中文档"}
            }
        await store.append_event(
            "user-memory",
            AgentEvent(
                event_type="user_message",
                session_id="session-memory-runtime",
                turn_id=turn_id,
                payload=user_payload,
            ),
        )
        await store.append_event(
            "user-memory",
            AgentEvent(
                event_type="assistant_message",
                session_id="session-memory-runtime",
                turn_id=turn_id,
                payload={"text": f"旧助手回复{index}-" + ("回复" * 500)},
            ),
        )


@pytest.mark.asyncio
async def test_runtime_compacts_long_history_before_controller_and_persists_memory() -> None:
    record_type = _memory_record_type()
    store = InMemoryAgentStore()
    await store.get_or_create_session("user-memory", "session-memory-runtime")
    await _seed_long_dialogue(store)

    class FakeSummarizer:
        def __init__(self) -> None:
            self.calls = []

        async def summarize(self, **kwargs):
            self.calls.append(kwargs)
            events = tuple(kwargs["all_source_events"])
            facts = kwargs["authoritative_facts"]
            return record_type(
                memory_id="memory-runtime-1",
                principal_id=kwargs["principal_id"],
                session_id=kwargs["session_id"],
                summary_version=1,
                covered_from_sequence=min(event.sequence for event in events),
                covered_to_sequence=max(event.sequence for event in events),
                rolling_summary="长期摘要：用户正在连续完成规划核查。",
                active_goal="继续规划核查",
                user_constraints=("保留用户长期约束",),
                explicit_ui_selections=facts["explicit_ui_selections"],
                authoritative_runtime_facts=facts["authoritative_runtime_facts"],
                source_event_ids=tuple(event.event_id for event in events),
                source_hash="runtime-source-hash",
            )

    controller = _CapturingDirectController()
    summarizer = FakeSummarizer()
    runtime = AgentRuntime(
        retrieval_port=_EmptyRetrievalPort(),
        controller=controller,
        answer_generator=object(),
        session_store=store,
        conversation_memory_summarizer=summarizer,
    )

    result = await runtime.run(
        AgentRunRequest(
            question="继续",
            principal_id="user-memory",
            session_id="session-memory-runtime",
            request_context={
                "user_ui_selections": {
                    "document": {"document_id": "doc-current", "title": "当前选中文档"}
                }
            },
        )
    )

    assert result.publication_state == "published"
    assert len(summarizer.calls) == 1
    assert (
        summarizer.calls[0]["stage_policy"]
        .for_stage("conversation_memory")
        .timeout_seconds
        <= 5.0
    )
    latest = await store.get_latest_conversation_memory(
        "user-memory", "session-memory-runtime"
    )
    assert latest is not None
    assert latest.rolling_summary.startswith("长期摘要")
    assert latest.explicit_ui_selections["document"]["document_id"] == "doc-old"
    projection = controller.projections[0]
    assert "长期摘要：用户正在连续完成规划核查。" in projection.conversation_text
    assert "旧用户约束1" not in projection.conversation_text
    events = await store.list_events("user-memory", "session-memory-runtime")
    current_user = next(
        event
        for event in reversed(events)
        if event.event_type == "user_message" and event.payload.get("text") == "继续"
    )
    assert current_user.payload["user_ui_selections"]["document"]["document_id"] == "doc-current"
    assert any(event.event_type == "conversation_memory_updated" for event in result.events)


@pytest.mark.asyncio
async def test_runtime_memory_failure_degrades_to_recent_window_without_blocking() -> None:
    store = InMemoryAgentStore()
    await store.get_or_create_session("user-memory", "session-memory-failure")
    for index in range(1, 6):
        turn_id = await store.allocate_turn_id(
            "user-memory", "session-memory-failure"
        )
        await store.append_event(
            "user-memory",
            AgentEvent(
                event_type="user_message",
                session_id="session-memory-failure",
                turn_id=turn_id,
                payload={"text": f"旧消息{index}-" + ("历史" * 600)},
            ),
        )
        await store.append_event(
            "user-memory",
            AgentEvent(
                event_type="assistant_message",
                session_id="session-memory-failure",
                turn_id=turn_id,
                payload={"text": f"旧回复{index}-" + ("历史" * 600)},
            ),
        )

    class FailingSummarizer:
        async def summarize(self, **kwargs):
            raise RuntimeError("summary unavailable")

    controller = _CapturingDirectController()
    runtime = AgentRuntime(
        retrieval_port=_EmptyRetrievalPort(),
        controller=controller,
        answer_generator=object(),
        session_store=store,
        conversation_memory_summarizer=FailingSummarizer(),
    )

    result = await runtime.run(
        AgentRunRequest(
            question="继续",
            principal_id="user-memory",
            session_id="session-memory-failure",
        )
    )

    assert result.publication_state == "published"
    assert any(event.event_type == "conversation_memory_failed" for event in result.events)
    assert await store.get_latest_conversation_memory(
        "user-memory", "session-memory-failure"
    ) is None


@pytest.mark.asyncio
async def test_runtime_memory_persist_conflict_degrades_without_blocking_request() -> None:
    record_type = _memory_record_type()

    class RacingStore(InMemoryAgentStore):
        async def save_conversation_memory(self, record):
            winner = replace(
                record,
                memory_id="winner-memory",
                rolling_summary="并发请求已经先持久化了摘要。",
            )
            await super().save_conversation_memory(winner)
            raise RuntimeError("conversation memory version conflict")

    store = RacingStore()
    await store.get_or_create_session("user-memory", "session-memory-runtime")
    await _seed_long_dialogue(store)

    class FakeSummarizer:
        async def summarize(self, **kwargs):
            events = tuple(kwargs["all_source_events"])
            return record_type(
                memory_id="losing-memory",
                principal_id=kwargs["principal_id"],
                session_id=kwargs["session_id"],
                summary_version=1,
                covered_from_sequence=min(event.sequence for event in events),
                covered_to_sequence=max(event.sequence for event in events),
                rolling_summary="本请求生成的摘要。",
                active_goal="继续",
                user_constraints=(),
                explicit_ui_selections={},
                authoritative_runtime_facts={},
                source_event_ids=tuple(event.event_id for event in events),
                source_hash="race-source-hash",
            )

    runtime = AgentRuntime(
        retrieval_port=_EmptyRetrievalPort(),
        controller=_CapturingDirectController(),
        answer_generator=object(),
        session_store=store,
        conversation_memory_summarizer=FakeSummarizer(),
    )

    result = await runtime.run(
        AgentRunRequest(
            question="继续",
            principal_id="user-memory",
            session_id="session-memory-runtime",
        )
    )

    assert result.publication_state == "published"
    latest = await store.get_latest_conversation_memory(
        "user-memory", "session-memory-runtime"
    )
    assert latest is not None
    assert latest.memory_id == "winner-memory"
    assert any(
        event.event_type == "conversation_memory_failed"
        and event.payload.get("phase") == "persist"
        for event in result.events
    )


@pytest.mark.asyncio
async def test_runtime_invalidates_memory_when_durable_source_hash_no_longer_matches() -> None:
    record_type = _memory_record_type()
    store = InMemoryAgentStore()
    await store.get_or_create_session("user-memory", "session-memory-invalid")
    turn_id = await store.allocate_turn_id("user-memory", "session-memory-invalid")
    first = await store.append_event(
        "user-memory",
        AgentEvent(
            event_type="user_message",
            session_id="session-memory-invalid",
            turn_id=turn_id,
            payload={"text": "原始历史问题"},
        ),
    )
    second = await store.append_event(
        "user-memory",
        AgentEvent(
            event_type="assistant_message",
            session_id="session-memory-invalid",
            turn_id=turn_id,
            payload={"text": "原始历史回答"},
        ),
    )
    await store.save_conversation_memory(
        record_type(
            memory_id="corrupt-memory",
            principal_id="user-memory",
            session_id="session-memory-invalid",
            summary_version=1,
            covered_from_sequence=first.sequence,
            covered_to_sequence=second.sequence,
            rolling_summary="CORRUPTED MEMORY SHOULD NOT BE USED",
            active_goal="corrupt",
            user_constraints=(),
            explicit_ui_selections={},
            authoritative_runtime_facts={},
            source_event_ids=(first.event_id, second.event_id),
            source_hash="definitely-not-the-source-hash",
        )
    )

    controller = _CapturingDirectController()
    runtime = AgentRuntime(
        retrieval_port=_EmptyRetrievalPort(),
        controller=controller,
        answer_generator=object(),
        session_store=store,
    )

    result = await runtime.run(
        AgentRunRequest(
            question="继续",
            principal_id="user-memory",
            session_id="session-memory-invalid",
        )
    )

    assert result.publication_state == "published"
    assert "CORRUPTED MEMORY" not in controller.projections[0].conversation_text
    assert any(
        event.event_type == "conversation_memory_invalidated"
        for event in result.events
    )
