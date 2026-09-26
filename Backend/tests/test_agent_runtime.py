from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.models.search_models import DocumentResult
from app.services.agent.context.engine import ContextEngine
from app.services.agent.answer_generator import GeneratedAnswer
from app.services.agent.answer_generator import AnswerGenerationError
from app.services.agent.controller import ControllerOutputError
from app.services.agent.runtime import AgentRunRequest, AgentRuntime
from app.services.agent.session import InMemoryAgentSessionStore
from app.services.agent.tool_runtime import ToolCall
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
        title="瑙勫垝鏍囧噯",
        content=text,
        similarity=0.9,
        metadata={
            "chunk_id": chunk_id,
            "document_name": "瑙勫垝鏍囧噯",
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
                arguments={"query": "婊戝潯鐩戞祴"},
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
            arguments={"question": "璇锋槑纭鏀垮尯銆?},
        )


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
                arguments={"file_ref": "vf_1", "name": "娴嬭瘯鍥惧眰"},
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
            answer="鍩轰簬鍐荤粨璇佹嵁鍥炵瓟",
            citations=tuple(item.citation_id for item in snapshot.items),
        )


@pytest.mark.asyncio
async def test_runtime_executes_controller_tool_loop_and_publishes_frozen_answer() -> None:
    store = InMemoryAgentSessionStore()
    generator = FakeAnswerGenerator()
    runtime = AgentRuntime(
        retrieval_port=FakeRetrievalPort(
            [make_candidate("chunk-1", "閲嶅簡甯傛粦鍧＄洃娴嬭姹?)]
        ),
        controller=RetrieveThenComposeController(),
        answer_generator=generator,
        session_store=store,
    )

    result = await runtime.run(
        AgentRunRequest(
            question="閲嶅簡甯傛粦鍧＄洃娴嬫湁浠€涔堣姹傦紵",
            session_id="session-1",
            principal_id="admin:test",
        )
    )

    assert result.publication_state == "published"
    assert result.trace_id
    assert result.answer.answer == "鍩轰簬鍐荤粨璇佹嵁鍥炵瓟"
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
        retrieval_port=FakeRetrievalPort(),
        controller=BrowserThenComposeController(),
        answer_generator=FakeAnswerGenerator(),
        session_store=store,
        context_engine=context_engine,
    )

    pending = await runtime.run(
        AgentRunRequest(
            question="瀵煎叆鏁版嵁骞剁‘璁ょ粨鏋?,
            session_id="browser-session",
            principal_id="admin:test",
        )
    )
    assert pending.publication_state == "tool_execution_required"
    assert pending.continuation_token

    result = await runtime.run(
        AgentRunRequest(
            question="瀵煎叆鏁版嵁骞剁‘璁ょ粨鏋?,
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
    assert result.turn_id == pending.turn_id
    assert len(context_engine.build_calls) == 2
    assert context_engine.build_calls[0]["current_turn_id"] == pending.turn_id
    assert context_engine.build_calls[1]["current_turn_id"] == pending.turn_id
    assert any(
        event.turn_id == pending.turn_id and event.event_type == "browser_tool_completed"
        for event in context_engine.build_calls[1]["events"]
    )


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
        retrieval_port=FakeRetrievalPort([make_candidate("chunk-current", "褰撳墠闂鐩稿叧鏍囧噯鍐呭")]),
        controller=RetrieveThenComposeController(),
        answer_generator=FakeAnswerGenerator(),
        session_store=InMemoryAgentSessionStore(),
        context_engine=context_engine,
    )

    result = await runtime.run(
        AgentRunRequest(
            question="鏌ヨ褰撳墠闂瀵瑰簲鏍囧噯",
            session_id="session-current-runtime-facts",
            principal_id="admin:test",
        )
    )

    assert result.publication_state == "published"
    assert len(context_engine.build_calls) == 2
    second_build = context_engine.build_calls[1]
    assert second_build["current_turn_id"] == result.turn_id
    assert second_build["events"][-1].event_type == "tool_completed", [event.event_type for event in second_build["events"]]
    assert second_build["events"][-1].payload["status"] == "ok"


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
                answer="绋冲畾妯″瀷韬唤鍥炵瓟",
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
        retrieval_port=FakeRetrievalPort([make_candidate("chunk-identity", "璇佹嵁")]),
        controller=controller,
        answer_generator=generator,
        reviewer=reviewer,
        session_store=InMemoryAgentSessionStore(),
    )

    result = await runtime.run(
        AgentRunRequest(
            question="瑕佹眰锛?,
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
            [make_candidate("chunk-history", "鍘嗗彶婊戝潯鐩戞祴瑕佹眰")]
        ),
        controller=RetrieveThenComposeController(),
        answer_generator=FakeAnswerGenerator(),
        session_store=store,
    )
    await first_runtime.run(
        AgentRunRequest(question="婊戝潯鐩戞祴瑕佹眰", session_id="session-1", principal_id="admin:test")
    )

    same_session_runtime = AgentRuntime(
        retrieval_port=FakeRetrievalPort(),
        controller=ReuseThenComposeController(),
        answer_generator=FakeAnswerGenerator(),
        session_store=store,
    )
    reused = await same_session_runtime.run(
        AgentRunRequest(question="鍒氭墠閭ｄ釜瑕佹眰鍛紵", session_id="session-1", principal_id="admin:test")
    )
    assert reused.frozen_evidence.items[0].chunk_id == "chunk-history"

    other_session_runtime = AgentRuntime(
        retrieval_port=FakeRetrievalPort(),
        controller=ReuseThenComposeController(),
        answer_generator=FakeAnswerGenerator(),
        session_store=store,
    )
    with pytest.raises(ValueError, match="Frozen Evidence"):
        await other_session_runtime.run(
            AgentRunRequest(question="鍒氭墠閭ｄ釜瑕佹眰鍛紵", session_id="session-2", principal_id="admin:test")
        )


@pytest.mark.asyncio
async def test_runtime_can_end_with_structured_clarification_without_evidence() -> None:
    runtime = AgentRuntime(
        retrieval_port=FakeRetrievalPort(),
        controller=ClarifyController(),
        answer_generator=FakeAnswerGenerator(),
        session_store=InMemoryAgentSessionStore(),
    )

    result = await runtime.run(
        AgentRunRequest(question="鏌ヤ竴涓嬭繖涓?, session_id="session-1", principal_id="admin:test")
    )

    assert result.publication_state == "clarification"
    assert result.clarification == "璇锋槑纭鏀垮尯銆?
    assert result.answer is None

    session = runtime.session_store.get("admin:test", "session-1")
    assert session is not None
    assistant_messages = [
        event.payload["text"]
        for event in session.events
        if event.event_type == "assistant_message"
    ]
    assert assistant_messages[-1] == "璇锋槑纭鏀垮尯銆?


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
        retrieval_port=FakeRetrievalPort([make_candidate("chunk-1", "璇佹嵁")]),
        controller=RetrieveThenComposeController(),
        answer_generator=FakeAnswerGenerator(),
        reviewer=reviewer,
        session_store=InMemoryAgentSessionStore(),
    )

    disabled = await runtime.run(
        AgentRunRequest(question="闂涓€", session_id="session-1", principal_id="admin:test")
    )
    enabled = await runtime.run(
        AgentRunRequest(
            question="闂浜?,
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
        retrieval_port=FakeRetrievalPort([make_candidate("chunk-1", "璇佹嵁")]),
        controller=RetrieveThenComposeController(),
        answer_generator=FakeAnswerGenerator(),
        reviewer=RejectingReviewer(),
        session_store=InMemoryAgentSessionStore(),
    )

    result = await runtime.run(
        AgentRunRequest(
            question="闂",
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
    runtime = AgentRuntime(
        retrieval_port=FakeRetrievalPort(),
        controller=controller,
        answer_generator=FakeAnswerGenerator(),
        session_store=InMemoryAgentSessionStore(),
    )

    await runtime.run(
        AgentRunRequest(
            question="绗簩闂?,
            session_id="session-1",
            principal_id="admin:test",
            legacy_history=({"role": "user", "content": "绗竴闂?},),
        )
    )
    await runtime.run(
        AgentRunRequest(
            question="绗笁闂?,
            session_id="session-1",
            principal_id="admin:test",
            legacy_history=({"role": "user", "content": "浼€犳棫鍘嗗彶"},),
        )
    )

    assert "绗竴闂? in controller.contexts[0]
    assert "浼€犳棫鍘嗗彶" not in controller.contexts[1]


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
            question="涓€鐩存绱?,
            session_id="session-fuse",
            principal_id="admin:test",
            max_steps=1,
        )
    )

    assert result.publication_state == "resource_fuse"
    assert result.answer is None
    assert result.limitation == "Agent 杩愯杈惧埌璧勬簮淇濇姢涓婇檺锛屾湭鍙戝竷绛旀銆?
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
            question="瑙勫垝鏍囧噯",
            session_id="session-retrieval-down",
            principal_id="admin:test",
        )
    )

    assert result.publication_state == "retrieval_unavailable"
    assert result.answer is None
    assert result.limitation == "鐭ヨ瘑妫€绱㈡湇鍔″綋鍓嶄笉鍙敤锛屾湭鍙戝竷绛旀銆?
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
            question="闂",
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
                arguments={"question": "璇疯ˉ鍏呭叿浣撶殑鍦熷湴鏁存不闂銆?},
            )

    controller = RecoveringController()
    runtime = AgentRuntime(
        retrieval_port=FakeRetrievalPort(),
        controller=controller,
        answer_generator=FakeAnswerGenerator(),
        session_store=InMemoryAgentSessionStore(),
    )

    result = await runtime.run(
        AgentRunRequest(
            question="闂",
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
        retrieval_port=FakeRetrievalPort([make_candidate("chunk-1", "璇佹嵁")]),
        controller=RetrieveThenComposeController(),
        answer_generator=FailingGenerator(),
        session_store=InMemoryAgentSessionStore(),
    )

    result = await runtime.run(
        AgentRunRequest(
            question="闂",
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
    runtime = AgentRuntime(
        retrieval_port=FakeRetrievalPort(),
        controller=controller,
        answer_generator=FakeAnswerGenerator(),
        session_store=InMemoryAgentSessionStore(),
    )

    await runtime.run(
        AgentRunRequest(
            question="闇€瑕佹€濊€?,
            session_id="session-reasoning",
            principal_id="admin:test",
            thinking=True,
        )
    )

    assert controller.reasoning_flags == [True]
