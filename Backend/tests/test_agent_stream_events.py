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
    async def decide(self, *, question, context_summary, working_evidence, observations, stage_policy):
        if not observations:
            return ToolCall(
                tool_call_id="retrieve-1",
                name="retrieve_kb",
                arguments={"query": question, "search_mode": "keyword", "secret": "do-not-expose"},
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
            AgentRunRequest(question="规划标准有什么要求？", session_id="session-1", principal_id="admin:test")
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
        "evidence_frozen",
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
    started = next(event for event in events if event.event_type == "tool_started")
    assert started.payload["arguments"] == {"query": "规划标准有什么要求？"}
    completed = next(event for event in events if event.event_type == "tool_completed")
    assert completed.payload["result_summary"] == {
        "evidence_ids": [result.frozen_evidence.items[0].evidence_id],
        "candidate_count": 1,
        "admitted_count": 1,
        "evidence_count": 1,
    }
    assert "secret" not in str(started.payload)


class StreamApplicationServiceStub:
    def __init__(self) -> None:
        self.calls: list[tuple[SearchRequest, bool]] = []

    async def stream(self, request: SearchRequest, *, generation_allowed: bool, principal_id: str):
        assert principal_id == "admin:admin"
        self.calls.append((request, generation_allowed))
        yield SimpleNamespace(
            event=SimpleNamespace(
                event_id="evt-1",
                sequence=1,
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
    assert '"event_id"' in payload
    assert '"sequence"' in payload
    assert "event: result" in payload
    assert '"generated_answer": "answer"' in payload


@pytest.mark.asyncio
async def test_session_detail_prefers_assistant_message_over_publication_metadata() -> None:
    from app.services.agent.events import AgentEvent
    from app.services.agent.session_service import AgentSessionService
    from app.services.agent.store import InMemoryAgentStore

    store = InMemoryAgentStore()
    service = AgentSessionService(session_store=store)
    await store.get_or_create_session("admin:test", "session-history")
    await store.append_event("admin:test", AgentEvent(
        event_type="assistant_message", session_id="session-history", turn_id="turn-1",
        payload={"text": "服务端保存的完整回答"},
    ))
    await store.append_event("admin:test", AgentEvent(
        event_type="publication_completed", session_id="session-history", turn_id="turn-1",
        payload={"state": "published", "citations": ["citation-1"]},
    ))

    detail = await service.get_session_detail(principal_id="admin:test", session_id="session-history")
    assert detail is not None
    assistant = next(message for message in detail["messages"] if message["role"] == "assistant")
    assert assistant["content"] == "服务端保存的完整回答"
    assert assistant["metadata"]["publication_state"] == "published"


@pytest.mark.asyncio
async def test_reviewer_events_exist_only_for_real_review_and_preserve_verdict() -> None:
    class Reviewer:
        async def review(self, **kwargs):
            return SimpleNamespace(verdict="UNSUPPORTED", findings=({}, {}))

    store = InMemoryAgentSessionStore()
    runtime = AgentRuntime(
        retrieval_port=RetrievalPortStub(), controller=ControllerStub(),
        answer_generator=AnswerGeneratorStub(), reviewer=Reviewer(), session_store=store,
    )
    disabled = await runtime.run(AgentRunRequest(
        question="问题", session_id="review-off", principal_id="admin:test"))
    enabled = await runtime.run(AgentRunRequest(
        question="问题", session_id="review-on", principal_id="admin:test", reviewer_enabled=True))

    assert not any(event.event_type.startswith("review_") for event in disabled.events)
    started = [event for event in enabled.events if event.event_type == "review_started"]
    completed = [event for event in enabled.events if event.event_type == "review_completed"]
    assert len(started) == len(completed) == 1
    assert started[0].payload["review_id"] == completed[0].payload["review_id"]
    assert completed[0].payload["verdict"] == "UNSUPPORTED"
    assert completed[0].payload["finding_count"] == 2


@pytest.mark.asyncio
async def test_reviewer_exception_closes_running_row_with_safe_error() -> None:
    class Reviewer:
        async def review(self, **kwargs):
            raise RuntimeError("provider_key=secret raw stack text")

    runtime = AgentRuntime(
        retrieval_port=RetrievalPortStub(), controller=ControllerStub(),
        answer_generator=AnswerGeneratorStub(), reviewer=Reviewer(),
        session_store=InMemoryAgentSessionStore(),
    )
    result = await runtime.run(AgentRunRequest(
        question="问题", session_id="review-error", principal_id="admin:test", reviewer_enabled=True))
    started = next(event for event in result.events if event.event_type == "review_started")
    completed = next(event for event in result.events if event.event_type == "review_completed")
    assert started.payload["review_id"] == completed.payload["review_id"]
    assert completed.payload["error"] == {"code": "REVIEW_FAILED", "message": "证据审查执行失败。"}
    assert "secret" not in str(completed.payload)
    assert result.publication_state == "review_failed"


@pytest.mark.asyncio
async def test_browser_stream_resume_keeps_one_tool_call_id_and_safe_receipt_summary() -> None:
    class BrowserController:
        def __init__(self, continuation=False):
            self.continuation = continuation

        async def decide(self, **kwargs):
            if not self.continuation:
                return ToolCall("browser-call-1", "locate_map", {"longitude": 104.06, "latitude": 30.67, "zoom": 12})
            evidence = kwargs["observations"][-1].payload["evidence_id"]
            return ToolCall("compose-after-browser", "compose_answer", {"evidence_ids": [evidence]})

    store = InMemoryAgentSessionStore()
    first = AgentRuntime(
        retrieval_port=RetrievalPortStub(), controller=BrowserController(),
        answer_generator=AnswerGeneratorStub(), session_store=store,
    )
    initial_frames = [frame async for frame in first.stream(AgentRunRequest(
        question="定位成都", session_id="browser-stream", principal_id="admin:test",
        request_context={"browser_observations": {"map_context": {
            "ready": True, "supported_tools": ["locate_map"], "dimension": "3d"}}},
    ))]
    pending = next(frame.result for frame in initial_frames if frame.result is not None)
    initial_events = [frame.event for frame in initial_frames if frame.event is not None]
    resumed_runtime = AgentRuntime(
        retrieval_port=RetrievalPortStub(), controller=BrowserController(continuation=True),
        answer_generator=AnswerGeneratorStub(), session_store=store,
    )
    resumed_frames = [frame async for frame in resumed_runtime.stream(AgentRunRequest(
        question="定位成都", session_id="browser-stream", principal_id="admin:test",
        continuation_token=pending.continuation_token,
        browser_tool_receipt={
            "tool_call_id": pending.pending_tool_call_id, "tool_name": "locate_map", "status": "succeeded",
            "output": {"secret": "must-not-leak"},
            "effect": {"status": "applied", "state_revision": 7, "credential": "hidden"},
            "map_context": {"dimension": "3d", "revision": 7},
        },
    ))]
    result = next(frame.result for frame in resumed_frames if frame.result is not None)
    resumed_events = [frame.event for frame in resumed_frames if frame.event is not None]
    start = next(event for event in initial_events if event.event_type == "tool_started")
    requested = next(event for event in initial_events if event.event_type == "browser_tool_requested")
    receipt = next(event for event in resumed_events if event.event_type == "browser_tool_completed")
    assert start.payload["tool_call_id"] == requested.payload["tool_call_id"] == receipt.payload["tool_call_id"]
    assert receipt.payload["receipt"] == {"effect_status": "applied", "state_revision": 7, "map_dimension": "3d"}
    assert "secret" not in str(receipt.payload)
    assert len([event for event in result.events if event.event_type == "publication_completed"]) == 1
