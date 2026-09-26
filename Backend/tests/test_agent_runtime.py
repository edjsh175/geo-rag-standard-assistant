from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.services.agent.context import ContextEngine
from app.services.agent.context.budget import (
    ContextBudgetConfig,
    ContextBudgetManager,
    StageBudget,
)
from app.models.search_models import DocumentResult
from app.services.agent.answer_generator import GeneratedAnswer
from app.services.agent.answer_generator import AnswerGenerationError
from app.services.agent.controller import ControllerOutputError
from app.services.agent.runtime import AgentRunRequest, AgentRuntime
from app.services.agent.session import InMemoryAgentSessionStore
from app.services.agent.tool_runtime import ToolCall
from app.services.agent.tools import build_default_tool_registry
from app.services.rag.contracts import (
    RetrievalCandidate,
    RetrievalChannelDiagnostic,
    RetrievalDiagnostics,
    RetrievalQuery,
    RetrievalResult,
)


def make_candidate(chunk_id: str, text: str) -> RetrievalCandidate:
    result = DocumentResult(
        id=chunk_id,
        title="规划标准",
        content=text,
        similarity=0.9,
        metadata={
            "chunk_id": chunk_id,
            "document_name": "规划标准",
            "match_type": "keyword",
        },
        spatial_info=None,
        file_type="pdf",
        file_size=0,
        upload_time=datetime.now(),
        source_url=None,
    )
    return RetrievalCandidate.from_document_result(result)


class FakeRetrievalPort:
    def __init__(self, candidates=()) -> None:
        self.candidates = tuple(candidates)
        self.queries: list[RetrievalQuery] = []

    async def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        self.queries.append(query)
        return RetrievalResult(
            candidates=self.candidates,
            embedding_available=False,
            diagnostics=RetrievalDiagnostics(keyword_count=len(self.candidates)),
        )

    async def fetch_chunks(self, chunk_ids):
        return [candidate for candidate in self.candidates if candidate.chunk_id in chunk_ids]


class RetrieveThenComposeController:
    def __init__(self) -> None:
        self.calls = 0

    async def decide(self, *, question, context_summary, working_evidence, observations, stage_policy):
        self.calls += 1
        if not observations:
            return ToolCall(
                tool_call_id="retrieve-1",
                name="retrieve_kb",
                arguments={"query": question, "search_mode": "keyword"},
            )
        evidence_ids = observations[-1].payload["evidence_ids"]
        return ToolCall(
            tool_call_id="compose-1",
            name="compose_answer",
            arguments={"evidence_ids": evidence_ids},
        )


class ReuseThenComposeController:
    async def decide(self, *, question, context_summary, working_evidence, observations, stage_policy):
        if not observations:
            return ToolCall(
                tool_call_id="reuse-1",
                name="reuse_evidence",
                arguments={"query": "滑坡监测"},
            )
        return ToolCall(
            tool_call_id="compose-2",
            name="compose_answer",
            arguments={"evidence_ids": observations[-1].payload["evidence_ids"]},
        )


class ClarifyController:
    async def decide(self, *, question, context_summary, working_evidence, observations, stage_policy):
        return ToolCall(
            tool_call_id="clarify-1",
            name="clarify",
            arguments={"question": "请明确行政区。"},
        )


def make_identity_store(session_id: str) -> InMemoryAgentSessionStore:
    from app.services.agent.identity import EntityCandidateRef, IdentityResolution

    store = InMemoryAgentSessionStore()
    session = store.get_or_create("admin:test", session_id)
    session.identity_resolution = IdentityResolution(
        status="ambiguous",
        candidate_refs=(
            EntityCandidateRef("entity:a", "Candidate A"),
            EntityCandidateRef("entity:b", "Candidate B"),
        ),
    )
    return store


class EndlessRetrieveController:
    def __init__(self) -> None:
        self.calls = 0

    async def decide(self, *, question, context_summary, working_evidence, observations, stage_policy):
        self.calls += 1
        return ToolCall(
            tool_call_id=f"retrieve-{self.calls}",
            name="retrieve_kb",
            arguments={"query": question},
        )


class InvalidArgumentsController:
    async def decide(self, *, question, context_summary, working_evidence, observations, stage_policy):
        return ToolCall(
            tool_call_id="invalid-args",
            name="retrieve_kb",
            arguments={"query": ""},
        )


class BrowserThenComposeController:
    async def decide(self, *, question, context_summary, working_evidence, observations, stage_policy):
        if not observations:
            return ToolCall(
                tool_call_id="browser-import-1",
                name="import_vector_dataset",
                arguments={"file_ref": "vf_1", "name": "测试图层"},
            )
        return ToolCall(
            tool_call_id="compose-browser-1",
            name="compose_answer",
            arguments={"evidence_ids": [observations[-1].payload["evidence_id"]]},
        )


class FakeAnswerGenerator:
    def __init__(self) -> None:
        self.snapshots = []

    async def generate(self, *, question, snapshot, stage_policy):
        self.snapshots.append(snapshot)
        return GeneratedAnswer(
            kind="knowledge_answer",
            answer="基于冻结证据回答",
            citations=tuple(item.citation_id for item in snapshot.items),
        )


class BudgetRetryController:
    async def decide(self, *, question, context_summary, working_evidence, observations, stage_policy):
        if not observations:
            return ToolCall(
                tool_call_id="budget-retrieve",
                name="retrieve_kb",
                arguments={"query": question, "search_mode": "keyword"},
            )
        latest = observations[-1]
        if latest.status == "rejected_evidence_budget":
            return ToolCall(
                tool_call_id="budget-compose-retry",
                name="compose_answer",
                arguments={"evidence_ids": [latest.payload["selected_evidence_ids"][0]]},
            )
        return ToolCall(
            tool_call_id="budget-compose-all",
            name="compose_answer",
            arguments={"evidence_ids": list(latest.payload["evidence_ids"])},
        )


class LongAnswerGenerator:
    async def generate(self, *, question, snapshot, stage_policy):
        return GeneratedAnswer(
            kind="knowledge_answer",
            answer="x" * 1200,
            citations=tuple(item.citation_id for item in snapshot.items),
        )


class CountingReviewer:
    def __init__(self) -> None:
        self.calls = 0

    async def review(self, **kwargs):
        self.calls += 1
        raise AssertionError("reviewer must not run when its full input exceeds budget")


def make_tight_context_engine(*, available_tokens: int) -> ContextEngine:
    stage = StageBudget(
        max_tokens=available_tokens + 100,
        system_reserve=50,
        generation_reserve=50,
    )
    return ContextEngine(
        ContextBudgetManager(
            ContextBudgetConfig(
                controller=StageBudget(max_tokens=1000, system_reserve=100, generation_reserve=100),
                answer=stage,
                reviewer=stage,
            )
        )
    )


@pytest.mark.asyncio
async def test_compose_answer_over_budget_is_rejected_before_freeze_and_can_retry_smaller_selection() -> None:
    generator = FakeAnswerGenerator()
    runtime = AgentRuntime(
        retrieval_port=FakeRetrievalPort(
            [
                make_candidate("chunk-budget-1", "A" * 160),
                make_candidate("chunk-budget-2", "B" * 160),
            ]
        ),
        controller=BudgetRetryController(),
        answer_generator=generator,
        session_store=InMemoryAgentSessionStore(),
        context_engine=make_tight_context_engine(available_tokens=75),
    )

    result = await runtime.run(
        AgentRunRequest(
            question="budget test",
            session_id="budget-selection",
            principal_id="admin:test",
        )
    )

    assert result.publication_state == "published"
    rejected = [event for event in result.events if event.event_type == "compose_answer_rejected"]
    assert len(rejected) == 1
    assert rejected[0].payload["reason"] == "evidence_budget_exceeded"
    frozen = [event for event in result.events if event.event_type == "evidence_frozen"]
    assert len(frozen) == 1
    assert len(frozen[0].payload["evidence_ids"]) == 1
    assert len(generator.snapshots) == 1
    assert len(generator.snapshots[0].items) == 1


@pytest.mark.asyncio
async def test_reviewer_full_input_budget_is_fail_closed_without_trimming_or_reviewer_call() -> None:
    reviewer = CountingReviewer()
    runtime = AgentRuntime(
        retrieval_port=FakeRetrievalPort(
            [make_candidate("chunk-review-budget", "short evidence")]
        ),
        controller=RetrieveThenComposeController(),
        answer_generator=LongAnswerGenerator(),
        reviewer=reviewer,
        session_store=InMemoryAgentSessionStore(),
        context_engine=make_tight_context_engine(available_tokens=100),
    )

    result = await runtime.run(
        AgentRunRequest(
            question="review budget test",
            session_id="review-budget",
            principal_id="admin:test",
            reviewer_enabled=True,
        )
    )

    assert result.publication_state == "review_budget_exceeded"
    assert result.answer is None
    assert result.frozen_evidence is not None
    assert reviewer.calls == 0
    states = [
        event.payload.get("state")
        for event in result.events
        if event.event_type == "publication_completed"
    ]
    assert states[-1] == "review_budget_exceeded"


@pytest.mark.asyncio
async def test_runtime_executes_controller_tool_loop_and_publishes_frozen_answer() -> None:
    store = InMemoryAgentSessionStore()
    generator = FakeAnswerGenerator()
    runtime = AgentRuntime(
        retrieval_port=FakeRetrievalPort(
            [make_candidate("chunk-1", "重庆市滑坡监测要求")]
        ),
        controller=RetrieveThenComposeController(),
        answer_generator=generator,
        session_store=store,
    )

    result = await runtime.run(
        AgentRunRequest(
            question="重庆市滑坡监测有什么要求？",
            session_id="session-1",
            principal_id="admin:test",
        )
    )

    assert result.publication_state == "published"
    assert result.trace_id
    assert result.answer.answer == "基于冻结证据回答"
    assert result.frozen_evidence is generator.snapshots[0]
    assert result.frozen_evidence.items[0].chunk_id == "chunk-1"
    assert [event.event_type for event in result.events] == [
        "user_message",
        "controller_decision",
        "tool_started",
        "tool_completed",
        "controller_decision",
        "evidence_frozen",
        "answer_generated",
        "publication_completed",
    ]
    assert {event.trace_id for event in result.events} == {result.trace_id}


@pytest.mark.asyncio
async def test_browser_continuation_receipt_becomes_freezable_evidence() -> None:
    store = InMemoryAgentSessionStore()
    runtime = AgentRuntime(
        retrieval_port=FakeRetrievalPort(),
        controller=BrowserThenComposeController(),
        answer_generator=FakeAnswerGenerator(),
        session_store=store,
    )

    pending = await runtime.run(
        AgentRunRequest(
            question="导入数据并确认结果",
            session_id="browser-session",
            principal_id="admin:test",
            request_context={
                "browser_observations": {
                    "map_context": {
                        "ready": True,
                        "supported_tools": ["import_vector_dataset"],
                    }
                }
            },
        )
    )
    assert pending.publication_state == "tool_execution_required"
    assert pending.continuation_token
    assert pending.answer is not None
    assert pending.answer.timeout_seconds == pytest.approx(30.0)

    result = await runtime.run(
        AgentRunRequest(
            question="导入数据并确认结果",
            session_id="browser-session",
            principal_id="admin:test",
            continuation_token=pending.continuation_token,
            browser_tool_receipt={
                "tool_call_id": pending.pending_tool_call_id,
                "tool_name": "import_vector_dataset",
                "status": "succeeded",
                "output": {"layer_ref": "ul_1"},
                "effect": {"status": "applied", "state_revision": 2},
                "map_context": {"schema_version": 2, "revision": 2},
            },
        )
    )

    assert result.publication_state == "published"
    assert result.frozen_evidence is not None
    assert len(result.frozen_evidence.items) == 1
    assert result.frozen_evidence.items[0].source == "browser_gis"
    assert '"layer_ref":"ul_1"' in result.frozen_evidence.items[0].text


@pytest.mark.asyncio
async def test_runtime_rejects_controller_tool_outside_current_action_surface() -> None:
    class UnavailableBrowserController:
        def __init__(self) -> None:
            self.tool_registry = build_default_tool_registry()

        async def decide(self, **kwargs):
            return ToolCall(
                tool_call_id="locate-without-browser-runtime",
                name="locate_map",
                arguments={"longitude": 104.0, "latitude": 30.0},
            )

    runtime = AgentRuntime(
        retrieval_port=FakeRetrievalPort(),
        controller=UnavailableBrowserController(),
        answer_generator=FakeAnswerGenerator(),
        session_store=InMemoryAgentSessionStore(),
    )

    result = await runtime.run(
        AgentRunRequest(
            question="定位到成都",
            session_id="surface-guard-session",
            principal_id="admin:test",
            max_steps=1,
        )
    )

    assert result.publication_state == "model_output_invalid"
    assert result.pending_tool_call_id is None
    assert result.continuation_token is None
    assert all(event.event_type != "browser_tool_requested" for event in result.events)


@pytest.mark.asyncio
async def test_runtime_resolves_main_model_once_and_preserves_identity_across_stages() -> None:
    class IdentityModelClient:
        supports_reasoning = True

        def __init__(self) -> None:
            self.resolve_calls = 0

        def resolve_main_model(self, *, thinking: bool) -> str:
            self.resolve_calls += 1
            assert thinking is True
            return "stable-main"

    class IdentityController:
        def __init__(self, model_client) -> None:
            self.model_client = model_client
            self.calls = 0
            self.model_names = []

        async def decide(
            self,
            *,
            question,
            context_summary,
            working_evidence,
            observations,
            stage_policy,
            model_name=None,
        ):
            self.model_names.append(model_name)
            self.calls += 1
            if self.calls == 1:
                return ToolCall(
                    tool_call_id="retrieve-identity",
                    name="retrieve_kb",
                    arguments={"query": question},
                )
            return ToolCall(
                tool_call_id="compose-identity",
                name="compose_answer",
                arguments={"evidence_ids": observations[-1].payload["evidence_ids"]},
            )

    class IdentityAnswerGenerator:
        def __init__(self) -> None:
            self.model_names = []

        async def generate(self, *, question, snapshot, stage_policy, model_name=None):
            self.model_names.append(model_name)
            return GeneratedAnswer(
                kind="knowledge_answer",
                answer="稳定模型身份回答",
                citations=tuple(item.citation_id for item in snapshot.items),
            )

    class IdentityReviewer:
        def __init__(self) -> None:
            self.model_names = []

        async def review(self, *, model_name=None, **kwargs):
            self.model_names.append(model_name)
            return SimpleNamespace(verdict="SUPPORTED", findings=())

    model_client = IdentityModelClient()
    controller = IdentityController(model_client)
    generator = IdentityAnswerGenerator()
    reviewer = IdentityReviewer()
    runtime = AgentRuntime(
        retrieval_port=FakeRetrievalPort([make_candidate("chunk-identity", "证据")]),
        controller=controller,
        answer_generator=generator,
        reviewer=reviewer,
        session_store=InMemoryAgentSessionStore(),
    )

    result = await runtime.run(
        AgentRunRequest(
            question="要求？",
            session_id="session-identity",
            principal_id="admin:test",
            reviewer_enabled=True,
            thinking=True,
        )
    )

    assert result.publication_state == "published"
    assert model_client.resolve_calls == 1
    assert controller.model_names == ["stable-main", "stable-main"]
    assert generator.model_names == ["stable-main"]
    assert reviewer.model_names == ["stable-main"]


@pytest.mark.asyncio
async def test_same_session_can_explicitly_reuse_evidence_but_other_session_cannot() -> None:
    store = InMemoryAgentSessionStore()
    first_runtime = AgentRuntime(
        retrieval_port=FakeRetrievalPort(
            [make_candidate("chunk-history", "历史滑坡监测要求")]
        ),
        controller=RetrieveThenComposeController(),
        answer_generator=FakeAnswerGenerator(),
        session_store=store,
    )
    await first_runtime.run(
        AgentRunRequest(question="滑坡监测要求", session_id="session-1", principal_id="admin:test")
    )

    same_session_runtime = AgentRuntime(
        retrieval_port=FakeRetrievalPort(),
        controller=ReuseThenComposeController(),
        answer_generator=FakeAnswerGenerator(),
        session_store=store,
    )
    reused = await same_session_runtime.run(
        AgentRunRequest(question="刚才那个要求呢？", session_id="session-1", principal_id="admin:test")
    )
    assert reused.frozen_evidence.items[0].chunk_id == "chunk-history"

    other_session_runtime = AgentRuntime(
        retrieval_port=FakeRetrievalPort(),
        controller=ReuseThenComposeController(),
        answer_generator=FakeAnswerGenerator(),
        session_store=store,
    )
    rejected = await other_session_runtime.run(
        AgentRunRequest(question="刚才那个要求呢？", session_id="session-2", principal_id="admin:test")
    )
    assert rejected.publication_state == "model_output_invalid"
    assert rejected.frozen_evidence is None


@pytest.mark.asyncio
async def test_runtime_can_end_with_structured_clarification_without_evidence() -> None:
    from app.services.agent.identity import EntityCandidateRef, IdentityResolution

    store = InMemoryAgentSessionStore()
    session = store.get_or_create("admin:test", "session-1")
    session.identity_resolution = IdentityResolution(
        status="ambiguous",
        candidate_refs=(
            EntityCandidateRef("entity:chengdu", "Chengdu"),
            EntityCandidateRef("entity:qingyang", "Qingyang District"),
        ),
    )
    runtime = AgentRuntime(
        retrieval_port=FakeRetrievalPort(),
        controller=ClarifyController(),
        answer_generator=FakeAnswerGenerator(),
        session_store=store,
    )

    result = await runtime.run(
        AgentRunRequest(question="Which entity?", session_id="session-1", principal_id="admin:test")
    )

    assert result.publication_state == "clarification"
    assert result.clarification == "请确认您指的是：Chengdu、Qingyang District。"
    assert result.answer is None

    assistant_messages = [
        event.payload["text"]
        for event in session.events
        if event.event_type == "assistant_message"
    ]
    assert assistant_messages[-1] == result.clarification


@pytest.mark.asyncio
async def test_reviewer_is_only_invoked_when_request_explicitly_enables_it() -> None:
    class FakeReviewer:
        def __init__(self) -> None:
            self.calls = 0

        async def review(self, **kwargs):
            self.calls += 1
            return "reviewed"

    reviewer = FakeReviewer()
    runtime = AgentRuntime(
        retrieval_port=FakeRetrievalPort([make_candidate("chunk-1", "证据")]),
        controller=RetrieveThenComposeController(),
        answer_generator=FakeAnswerGenerator(),
        reviewer=reviewer,
        session_store=InMemoryAgentSessionStore(),
    )

    disabled = await runtime.run(
        AgentRunRequest(question="问题一", session_id="session-1", principal_id="admin:test")
    )
    enabled = await runtime.run(
        AgentRunRequest(
            question="问题二",
            session_id="session-2",
            principal_id="admin:test",
            reviewer_enabled=True,
        )
    )

    assert disabled.review is None
    assert enabled.review == "reviewed"
    assert reviewer.calls == 1


@pytest.mark.asyncio
async def test_reviewer_rejection_blocks_publication() -> None:
    class RejectingReviewer:
        async def review(self, **kwargs):
            return SimpleNamespace(verdict="UNSUPPORTED", findings=())

    runtime = AgentRuntime(
        retrieval_port=FakeRetrievalPort([make_candidate("chunk-1", "证据")]),
        controller=RetrieveThenComposeController(),
        answer_generator=FakeAnswerGenerator(),
        reviewer=RejectingReviewer(),
        session_store=InMemoryAgentSessionStore(),
    )

    result = await runtime.run(
        AgentRunRequest(
            question="问题",
            session_id="session-1",
            principal_id="admin:test",
            reviewer_enabled=True,
        )
    )

    assert result.publication_state == "review_rejected"
    assert result.answer is None
    assert result.limitation


@pytest.mark.asyncio
async def test_legacy_history_seeds_only_a_new_session_and_then_session_is_authoritative() -> None:
    class ContextCapturingController(ClarifyController):
        def __init__(self) -> None:
            self.contexts = []

        async def decide(self, *, question, context_summary, working_evidence, observations, stage_policy):
            self.contexts.append(context_summary)
            return await super().decide(
                question=question,
                context_summary=context_summary,
                working_evidence=working_evidence,
                observations=observations,
                stage_policy=stage_policy,
            )

    controller = ContextCapturingController()
    store = make_identity_store("session-1")
    runtime = AgentRuntime(
        retrieval_port=FakeRetrievalPort(),
        controller=controller,
        answer_generator=FakeAnswerGenerator(),
        session_store=store,
    )

    await runtime.run(
        AgentRunRequest(
            question="第二问",
            session_id="session-1",
            principal_id="admin:test",
            legacy_history=({"role": "user", "content": "第一问"},),
        )
    )
    await runtime.run(
        AgentRunRequest(
            question="第三问",
            session_id="session-1",
            principal_id="admin:test",
            legacy_history=({"role": "user", "content": "伪造旧历史"},),
        )
    )

    assert "第一问" in controller.contexts[0]
    assert "伪造旧历史" not in controller.contexts[1]


def test_session_store_isolates_same_session_id_by_principal() -> None:
    store = InMemoryAgentSessionStore()
    first = store.get_or_create("visitor:a", "same-session")
    second = store.get_or_create("visitor:b", "same-session")

    assert first is not second


@pytest.mark.asyncio
async def test_runtime_reports_resource_fuse_as_structured_failure() -> None:
    runtime = AgentRuntime(
        retrieval_port=FakeRetrievalPort(),
        controller=EndlessRetrieveController(),
        answer_generator=FakeAnswerGenerator(),
        session_store=InMemoryAgentSessionStore(),
    )

    result = await runtime.run(
        AgentRunRequest(
            question="一直检索",
            session_id="session-fuse",
            principal_id="admin:test",
            max_steps=1,
        )
    )

    assert result.publication_state == "resource_fuse"
    assert result.answer is None
    assert result.limitation == "Agent 运行达到资源保护上限，未发布答案。"
    assert result.events[-1].payload["state"] == "resource_fuse"

    session = runtime.session_store.get("admin:test", "session-fuse")
    assert session is not None
    assert any(
        event.event_type == "assistant_message"
        and event.payload.get("text") == result.limitation
        for event in session.events
    )


@pytest.mark.asyncio
async def test_runtime_reports_retrieval_unavailable_as_distinct_structured_failure() -> None:
    class UnavailablePort(FakeRetrievalPort):
        async def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
            return RetrievalResult(
                candidates=(),
                embedding_available=False,
                diagnostics=RetrievalDiagnostics(
                    channels=(
                        RetrievalChannelDiagnostic(
                            channel="keyword",
                            state="unavailable",
                            detail="postgres unavailable",
                        ),
                    ),
                ),
            )

    runtime = AgentRuntime(
        retrieval_port=UnavailablePort(),
        controller=EndlessRetrieveController(),
        answer_generator=FakeAnswerGenerator(),
        session_store=InMemoryAgentSessionStore(),
    )

    result = await runtime.run(
        AgentRunRequest(
            question="规划标准",
            session_id="session-retrieval-down",
            principal_id="admin:test",
        )
    )

    assert result.publication_state == "retrieval_unavailable"
    assert result.answer is None
    assert result.limitation == "知识检索服务当前不可用，未发布答案。"
    assert result.events[-1].payload["state"] == "retrieval_unavailable"


def test_session_store_evicts_oldest_session_when_capacity_is_reached() -> None:
    store = InMemoryAgentSessionStore(max_sessions=2)
    first = store.get_or_create("admin:test", "s1")
    store.get_or_create("admin:test", "s2")
    store.get_or_create("admin:test", "s3")

    assert store.get("admin:test", "s1") is None
    assert store.get("admin:test", "s2") is not None
    assert store.get("admin:test", "s3") is not None
    assert first.session_id == "s1"


@pytest.mark.asyncio
async def test_runtime_reports_invalid_controller_output_as_structured_failure() -> None:
    class InvalidController:
        async def decide(self, **kwargs):
            raise ControllerOutputError("invalid controller output")

    runtime = AgentRuntime(
        retrieval_port=FakeRetrievalPort(),
        controller=InvalidController(),
        answer_generator=FakeAnswerGenerator(),
        session_store=InMemoryAgentSessionStore(),
    )

    result = await runtime.run(
        AgentRunRequest(
            question="问题",
            session_id="session-invalid-controller",
            principal_id="admin:test",
        )
    )

    assert result.publication_state == "model_output_invalid"
    assert result.answer is None
    assert result.events[-1].payload["state"] == "model_output_invalid"
    assert result.events[-1].payload["failure_stage"] == "controller"
    assert "invalid controller output" in result.events[-1].payload["error"]


@pytest.mark.asyncio
async def test_runtime_returns_invalid_tool_arguments_to_controller_for_replanning() -> None:
    class RecoveringController:
        def __init__(self) -> None:
            self.calls = 0
            self.seen_observations = []

        async def decide(self, *, question, context_summary, working_evidence, observations, stage_policy):
            self.calls += 1
            self.seen_observations.append(tuple(observations))
            if self.calls == 1:
                return ToolCall(
                    tool_call_id="invalid-args",
                    name="retrieve_kb",
                    arguments={"query": ""},
                )
            return ToolCall(
                tool_call_id="clarify-after-denial",
                name="clarify",
                arguments={"question": "请补充具体的土地整治问题。"},
            )

    controller = RecoveringController()
    store = make_identity_store("session-invalid-tool")
    runtime = AgentRuntime(
        retrieval_port=FakeRetrievalPort(),
        controller=controller,
        answer_generator=FakeAnswerGenerator(),
        session_store=store,
    )

    result = await runtime.run(
        AgentRunRequest(
            question="问题",
            session_id="session-invalid-tool",
            principal_id="admin:test",
        )
    )

    assert result.publication_state == "clarification"
    assert controller.calls == 2
    denied = controller.seen_observations[1][-1]
    assert denied.status == "denied"
    assert "invalid arguments for retrieve_kb" in denied.payload["error"]
    assert any(
        event.event_type == "tool_completed"
        and event.payload.get("status") == "denied"
        for event in result.events
    )


@pytest.mark.asyncio
async def test_runtime_reports_answer_generation_failure_as_structured_failure() -> None:
    class FailingGenerator:
        async def generate(self, **kwargs):
            raise AnswerGenerationError("invalid structured answer")

    runtime = AgentRuntime(
        retrieval_port=FakeRetrievalPort([make_candidate("chunk-1", "证据")]),
        controller=RetrieveThenComposeController(),
        answer_generator=FailingGenerator(),
        session_store=InMemoryAgentSessionStore(),
    )

    result = await runtime.run(
        AgentRunRequest(
            question="问题",
            session_id="session-invalid-answer",
            principal_id="admin:test",
        )
    )

    assert result.publication_state == "model_output_invalid"
    assert result.events[-1].payload["failure_stage"] == "answer_generation"
    assert "invalid structured answer" in result.events[-1].payload["error"]


@pytest.mark.asyncio
async def test_runtime_derives_reasoning_capability_from_model_adapter_not_request() -> None:
    class ReasoningAwareClarifyController(ClarifyController):
        def __init__(self) -> None:
            self.model_client = SimpleNamespace(supports_reasoning=True)
            self.reasoning_flags = []

        async def decide(self, *, question, context_summary, working_evidence, observations, stage_policy):
            self.reasoning_flags.append(
                stage_policy.for_stage("controller").request_reasoning
            )
            return await super().decide(
                question=question,
                context_summary=context_summary,
                working_evidence=working_evidence,
                observations=observations,
                stage_policy=stage_policy,
            )

    controller = ReasoningAwareClarifyController()
    store = make_identity_store("session-reasoning")
    runtime = AgentRuntime(
        retrieval_port=FakeRetrievalPort(),
        controller=controller,
        answer_generator=FakeAnswerGenerator(),
        session_store=store,
    )

    await runtime.run(
        AgentRunRequest(
            question="需要思考",
            session_id="session-reasoning",
            principal_id="admin:test",
            thinking=True,
        )
    )

    assert controller.reasoning_flags == [True]


@pytest.mark.asyncio
async def test_runtime_passes_latest_current_turn_tool_completion_to_context_engine() -> None:
    class RecordingContextEngine(ContextEngine):
        def __init__(self) -> None:
            super().__init__()
            self.build_calls = []

        def build_frame(self, **kwargs):
            recorded = dict(kwargs)
            recorded["events"] = list(kwargs.get("events") or ())
            self.build_calls.append(recorded)
            return super().build_frame(**kwargs)

    context_engine = RecordingContextEngine()
    runtime = AgentRuntime(
        retrieval_port=FakeRetrievalPort([make_candidate("chunk-current", "current standard evidence")]),
        controller=RetrieveThenComposeController(),
        answer_generator=FakeAnswerGenerator(),
        session_store=InMemoryAgentSessionStore(),
        context_engine=context_engine,
    )

    result = await runtime.run(
        AgentRunRequest(
            question="query current standard",
            session_id="session-current-runtime-facts",
            principal_id="admin:test",
        )
    )

    assert result.publication_state == "published"
    assert len(context_engine.build_calls) == 2
    second_build = context_engine.build_calls[1]
    assert second_build["current_turn_id"] == result.turn_id
    assert second_build["events"][-1].event_type == "tool_completed"
    assert second_build["events"][-1].payload["status"] == "ok"
