from __future__ import annotations

import asyncio

import pytest

from app.services.agent.answer_generator import GeneratedAnswer
from app.services.agent.events import AgentEvent
from app.services.agent.runtime import AgentRunRequest, AgentRuntime
from app.services.agent.session import PendingBrowserExecution
from app.services.agent.store import InMemoryAgentStore
from app.services.rag.contracts import RetrievalDiagnostics, RetrievalQuery, RetrievalResult


class EmptyRetrievalPort:
    async def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        return RetrievalResult(
            candidates=(),
            embedding_available=False,
            diagnostics=RetrievalDiagnostics(),
        )

    async def fetch_chunks(self, chunk_ids):
        return ()


class CountingController:
    def __init__(self) -> None:
        self.calls = 0

    async def decide(self, **kwargs):
        self.calls += 1
        raise AssertionError("controller must not run after cancellation")


class SlowController:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def decide(self, **kwargs):
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


class CancelThenDirectController:
    def __init__(self, store: InMemoryAgentStore) -> None:
        self.store = store

    async def decide(self, **kwargs):
        await self.store.append_event(
            "user-1",
            AgentEvent(
                event_type="run_cancel_requested",
                session_id="session-race",
                turn_id="turn-1",
                trace_id="trace-cancel",
                payload={"reason": "user_requested"},
            ),
        )
        from app.services.agent.tool_runtime import ToolCall

        return ToolCall(
            tool_call_id="direct-after-cancel",
            name="direct_answer",
            arguments={"answer": "must not publish"},
        )


class UnusedAnswerGenerator:
    async def generate(self, **kwargs) -> GeneratedAnswer:  # pragma: no cover
        raise AssertionError("answer generator should not run")


@pytest.mark.asyncio
async def test_runtime_honors_durable_cancel_request_before_controller() -> None:
    store = InMemoryAgentStore()
    await store.get_or_create_session("user-1", "session-1")
    await store.append_event(
        "user-1",
        AgentEvent(
            event_type="run_cancel_requested",
            session_id="session-1",
            turn_id="turn-1",
            payload={"reason": "user_requested"},
        ),
    )
    controller = CountingController()
    runtime = AgentRuntime(
        retrieval_port=EmptyRetrievalPort(),
        controller=controller,
        answer_generator=UnusedAnswerGenerator(),
        session_store=store,
    )

    result = await runtime.run(
        AgentRunRequest(
            question="should stop",
            principal_id="user-1",
            session_id="session-1",
        )
    )

    assert result.publication_state == "cancelled"
    assert controller.calls == 0
    events = await store.list_events("user-1", "session-1")
    assert [event.event_type for event in events][-1] == "run_cancelled"


@pytest.mark.asyncio
async def test_request_cancellation_is_idempotent_for_same_turn() -> None:
    store = InMemoryAgentStore()
    await store.get_or_create_session("user-1", "session-1")
    await store.append_event(
        "user-1",
        AgentEvent(
            event_type="user_message",
            session_id="session-1",
            turn_id="turn-1",
            trace_id="trace-1",
            payload={"text": "hello"},
        ),
    )
    runtime = AgentRuntime(
        retrieval_port=EmptyRetrievalPort(),
        controller=CountingController(),
        answer_generator=UnusedAnswerGenerator(),
        session_store=store,
    )

    first = await runtime.request_cancellation(
        principal_id="user-1",
        session_id="session-1",
        turn_id="turn-1",
        reason="user_requested",
    )
    second = await runtime.request_cancellation(
        principal_id="user-1",
        session_id="session-1",
        turn_id="turn-1",
        reason="user_requested",
    )

    assert first.event_id == second.event_id
    events = await store.list_events("user-1", "session-1")
    assert sum(event.event_type == "run_cancel_requested" for event in events) == 1


@pytest.mark.asyncio
async def test_stream_close_requests_and_completes_server_side_cancellation() -> None:
    store = InMemoryAgentStore()
    controller = SlowController()
    runtime = AgentRuntime(
        retrieval_port=EmptyRetrievalPort(),
        controller=controller,
        answer_generator=UnusedAnswerGenerator(),
        session_store=store,
    )
    stream = runtime.stream(
        AgentRunRequest(
            question="long request",
            principal_id="user-1",
            session_id="session-stream",
        )
    )

    first = await anext(stream)
    assert first.event is not None
    assert first.event.event_type == "user_message"
    await asyncio.wait_for(controller.started.wait(), timeout=1.0)

    await asyncio.wait_for(stream.aclose(), timeout=1.0)

    await asyncio.wait_for(controller.cancelled.wait(), timeout=1.0)
    events = await store.list_events("user-1", "session-stream")
    assert any(event.event_type == "run_cancel_requested" for event in events)
    assert any(event.event_type == "run_cancelled" for event in events)


@pytest.mark.asyncio
async def test_request_cancellation_rejects_already_published_turn() -> None:
    store = InMemoryAgentStore()
    await store.get_or_create_session("user-1", "session-published")
    await store.append_event(
        "user-1",
        AgentEvent(
            event_type="user_message",
            session_id="session-published",
            turn_id="turn-1",
            trace_id="trace-1",
        ),
    )
    await store.append_event(
        "user-1",
        AgentEvent(
            event_type="publication_completed",
            session_id="session-published",
            turn_id="turn-1",
            trace_id="trace-1",
            payload={"state": "published"},
        ),
    )
    runtime = AgentRuntime(
        retrieval_port=EmptyRetrievalPort(),
        controller=CountingController(),
        answer_generator=UnusedAnswerGenerator(),
        session_store=store,
    )

    with pytest.raises(ValueError, match="already terminal"):
        await runtime.request_cancellation(
            principal_id="user-1",
            session_id="session-published",
            turn_id="turn-1",
        )


@pytest.mark.asyncio
async def test_request_cancellation_immediately_closes_pending_browser_turn() -> None:
    store = InMemoryAgentStore()
    session = await store.get_or_create_session("user-1", "session-browser")
    session.pending_browser_execution = PendingBrowserExecution(
        token="continue-1",
        question="show layer",
        turn_id="turn-1",
        trace_id="trace-1",
        tool_call_id="call-browser-1",
        tool_name="set_layer_visibility",
        observations=(),
        request_context={},
        reviewer_enabled=False,
        thinking=False,
        max_steps=5,
        steps_used=1,
        max_elapsed_seconds=60.0,
        retrieval_constraints=None,
        main_model_name=None,
        session_id="session-browser",
    )
    await store.save_session(session)
    await store.append_event(
        "user-1",
        AgentEvent(
            event_type="browser_tool_requested",
            session_id="session-browser",
            turn_id="turn-1",
            trace_id="trace-1",
            payload={"tool_call_id": "call-browser-1"},
        ),
    )
    runtime = AgentRuntime(
        retrieval_port=EmptyRetrievalPort(),
        controller=CountingController(),
        answer_generator=UnusedAnswerGenerator(),
        session_store=store,
    )

    await runtime.request_cancellation(
        principal_id="user-1",
        session_id="session-browser",
        turn_id="turn-1",
    )

    assert await store.get_pending_execution("user-1", "session-browser") is None
    events = await store.list_events("user-1", "session-browser")
    assert [event.event_type for event in events][-2:] == [
        "run_cancel_requested",
        "run_cancelled",
    ]


@pytest.mark.asyncio
async def test_cancel_arriving_during_controller_prevents_direct_answer_publication() -> None:
    store = InMemoryAgentStore()
    runtime = AgentRuntime(
        retrieval_port=EmptyRetrievalPort(),
        controller=CancelThenDirectController(store),
        answer_generator=UnusedAnswerGenerator(),
        session_store=store,
    )

    result = await runtime.run(
        AgentRunRequest(
            question="race",
            principal_id="user-1",
            session_id="session-race",
        )
    )

    assert result.publication_state == "cancelled"
    events = await store.list_events("user-1", "session-race")
    assert not any(
        event.event_type == "publication_completed"
        and event.payload.get("state") == "published"
        for event in events
    )
