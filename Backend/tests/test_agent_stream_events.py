from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.api.search_routes import stream_search_documents
from app.core.auth import UserIdentity
from app.models.search_models import DocumentResult, SearchRequest, SearchResponse
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


def make_candidate(chunk_id: str = "chunk-1") -> RetrievalCandidate:
    result = DocumentResult(
        id=chunk_id,
        title="规划标准",
        content="规划标准要求。",
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


class RetrievalPortStub:
    async def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        return RetrievalResult(
            candidates=(make_candidate(),),
            embedding_available=False,
            diagnostics=RetrievalDiagnostics(keyword_count=1),
        )

    async def fetch_chunks(self, chunk_ids):
        return [make_candidate(chunk_ids[0])] if chunk_ids else []


class ControllerStub:
    async def decide(self, *, question, context_summary, observations, stage_policy):
        if not observations:
            return ToolCall(
                tool_call_id="retrieve-1",
                name="retrieve_kb",
                arguments={"query": question, "search_mode": "keyword"},
            )
        return ToolCall(
            tool_call_id="compose-1",
            name="compose_answer",
            arguments={"evidence_ids": observations[-1].payload["evidence_ids"]},
        )


class AnswerGeneratorStub:
    async def generate(self, *, question, snapshot, stage_policy):
        return GeneratedAnswer(
            kind="knowledge_answer",
            answer="基于冻结证据回答。",
            citations=tuple(item.citation_id for item in snapshot.items),
        )


@pytest.mark.asyncio
async def test_runtime_stream_projects_same_run_events_in_order() -> None:
    runtime = AgentRuntime(
        retrieval_port=RetrievalPortStub(),
        controller=ControllerStub(),
        answer_generator=AnswerGeneratorStub(),
        session_store=InMemoryAgentSessionStore(),
    )

    frames = [
        frame
        async for frame in runtime.stream(
            AgentRunRequest(question="规划标准有什么要求？", session_id="session-1")
        )
    ]

    events = [frame.event for frame in frames if frame.event is not None]
    result_frames = [frame for frame in frames if frame.result is not None]

    assert [event.event_type for event in events] == [
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
    assert len(result_frames) == 1
    result = result_frames[0].result
    assert result is not None
    assert {event.session_id for event in events} == {result.session_id}
    assert {event.turn_id for event in events} == {result.turn_id}
    assert {event.trace_id for event in events} == {result.trace_id}
    assert [event.event_type for event in result.events] == [
        event.event_type for event in events
    ]
    assert all("reasoning" not in key.lower() for event in events for key in event.payload)


class StreamApplicationServiceStub:
    def __init__(self) -> None:
        self.calls: list[tuple[SearchRequest, bool]] = []

    async def stream(self, request: SearchRequest, *, generation_allowed: bool):
        self.calls.append((request, generation_allowed))
        yield SimpleNamespace(
            event=SimpleNamespace(
                event_type="controller_decision",
                session_id="session-1",
                turn_id="turn-1",
                trace_id="trace-1",
                payload={"tool_name": "retrieve_kb"},
                created_at=datetime.now(),
            ),
            response=None,
        )
        yield SimpleNamespace(
            event=None,
            response=SearchResponse(
                query=request.query,
                generated_answer="answer",
                session_id="session-1",
                trace_id="trace-1",
                final_mode="agent",
                publication_state="published",
            ),
        )


class QuotaServiceStub:
    async def consume_generation(self, visitor_id: str, ip_hash: str):
        raise AssertionError("admin request must not consume visitor quota")


@pytest.mark.asyncio
async def test_stream_route_serializes_application_runtime_events_and_final_response() -> None:
    application_service = StreamApplicationServiceStub()
    response = await stream_search_documents(
        SearchRequest(query="规划标准", use_generation=True, session_id="session-1"),
        current_user=UserIdentity(username="admin", role="admin"),
        application_service=application_service,
        quota_service=QuotaServiceStub(),
    )

    chunks: list[str] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
    payload = "".join(chunks)

    assert application_service.calls[0][1] is True
    assert "event: controller_decision" in payload
    assert '"trace_id": "trace-1"' in payload
    assert "event: result" in payload
    assert '"generated_answer": "answer"' in payload
