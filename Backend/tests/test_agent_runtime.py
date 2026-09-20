from __future__ import annotations

from datetime import datetime

import pytest

from app.models.search_models import DocumentResult
from app.services.agent.answer_generator import GeneratedAnswer
from app.services.agent.runtime import AgentRunRequest, AgentRuntime
from app.services.agent.session import InMemoryAgentSessionStore
from app.services.agent.tool_runtime import ToolCall
from app.services.rag.contracts import (
    RetrievalCandidate,
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

    async def decide(self, *, question, context_summary, observations, stage_policy):
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
    async def decide(self, *, question, context_summary, observations, stage_policy):
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
    async def decide(self, *, question, context_summary, observations, stage_policy):
        return ToolCall(
            tool_call_id="clarify-1",
            name="clarify",
            arguments={"question": "请明确行政区。"},
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
        )
    )

    assert result.publication_state == "published"
    assert result.answer.answer == "基于冻结证据回答"
    assert result.frozen_evidence is generator.snapshots[0]
    assert result.frozen_evidence.items[0].chunk_id == "chunk-1"
    assert [event.event_type for event in result.events] == [
        "user_message",
        "controller_decision",
        "tool_started",
        "tool_completed",
        "controller_decision",
        "tool_started",
        "evidence_frozen",
        "tool_completed",
        "answer_generated",
        "publication_completed",
    ]


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
        AgentRunRequest(question="滑坡监测要求", session_id="session-1")
    )

    same_session_runtime = AgentRuntime(
        retrieval_port=FakeRetrievalPort(),
        controller=ReuseThenComposeController(),
        answer_generator=FakeAnswerGenerator(),
        session_store=store,
    )
    reused = await same_session_runtime.run(
        AgentRunRequest(question="刚才那个要求呢？", session_id="session-1")
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
            AgentRunRequest(question="刚才那个要求呢？", session_id="session-2")
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
        AgentRunRequest(question="查一下这个", session_id="session-1")
    )

    assert result.publication_state == "clarification"
    assert result.clarification == "请明确行政区。"
    assert result.answer is None


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
        AgentRunRequest(question="问题一", session_id="session-1")
    )
    enabled = await runtime.run(
        AgentRunRequest(
            question="问题二",
            session_id="session-2",
            reviewer_enabled=True,
        )
    )

    assert disabled.review is None
    assert enabled.review == "reviewed"
    assert reviewer.calls == 1
