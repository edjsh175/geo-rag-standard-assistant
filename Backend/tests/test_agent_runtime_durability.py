from __future__ import annotations

import pytest

from app.services.agent.controller import ControllerOutputError
from app.services.agent.runtime import AgentRunRequest, AgentRuntime
from app.services.agent.store import InMemoryAgentStore
from app.services.agent.tool_runtime import ToolCall
from app.services.rag.contracts import (
    RetrievalChannelDiagnostic,
    RetrievalDiagnostics,
    RetrievalQuery,
    RetrievalResult,
)


class EmptyRetrievalPort:
    async def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        return RetrievalResult(
            candidates=(),
            embedding_available=False,
            diagnostics=RetrievalDiagnostics(),
        )

    async def fetch_chunks(self, chunk_ids):
        return ()


class EndlessRetrieveController:
    def __init__(self) -> None:
        self.calls = 0

    async def decide(self, **kwargs):
        self.calls += 1
        return ToolCall(
            tool_call_id=f"retrieve-{self.calls}",
            name="retrieve_kb",
            arguments={"query": "test"},
        )


class UnusedAnswerGenerator:
    async def generate(self, **kwargs):  # pragma: no cover - should not be reached
        raise AssertionError("answer generator should not be called")


class DirectController:
    async def decide(self, **kwargs):
        return ToolCall(
            tool_call_id="direct-1",
            name="direct_answer",
            arguments={"answer": "hello from controller"},
        )


class InvalidController:
    async def decide(self, **kwargs):
        raise ControllerOutputError("invalid controller output")


class UnavailableRetrievalPort(EmptyRetrievalPort):
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


async def assert_terminal_state_is_durable(
    *,
    runtime: AgentRuntime,
    store: InMemoryAgentStore,
    principal_id: str,
    session_id: str,
    expected_state: str,
) -> None:
    result = await runtime.run(
        AgentRunRequest(
            question="test question",
            principal_id=principal_id,
            session_id=session_id,
        )
    )
    assert result.publication_state == expected_state
    persisted = await store.list_events(principal_id, session_id)
    assert persisted
    assert [event.sequence for event in persisted] == list(range(1, len(persisted) + 1))
    assert any(
        event.event_type == "publication_completed"
        and event.payload.get("state") == expected_state
        for event in persisted
    )


@pytest.mark.asyncio
async def test_resource_fuse_terminal_events_are_durable_before_return() -> None:
    store = InMemoryAgentStore()
    runtime = AgentRuntime(
        retrieval_port=EmptyRetrievalPort(),
        controller=EndlessRetrieveController(),
        answer_generator=UnusedAnswerGenerator(),
        session_store=store,
    )

    result = await runtime.run(
        AgentRunRequest(
            question="keep retrieving",
            principal_id="durable-user",
            session_id="durable-session",
            max_steps=1,
        )
    )

    assert result.publication_state == "resource_fuse"
    persisted = await store.list_events("durable-user", "durable-session")
    assert [event.sequence for event in persisted] == list(range(1, len(persisted) + 1))
    assert any(
        event.event_type == "publication_completed"
        and event.payload.get("state") == "resource_fuse"
        for event in persisted
    )
    assert any(
        event.event_type == "assistant_message"
        and event.payload.get("text") == result.limitation
        for event in persisted
    )


@pytest.mark.asyncio
async def test_direct_answer_terminal_state_is_durable_before_return() -> None:
    store = InMemoryAgentStore()
    runtime = AgentRuntime(
        retrieval_port=EmptyRetrievalPort(),
        controller=DirectController(),
        answer_generator=UnusedAnswerGenerator(),
        session_store=store,
    )
    await assert_terminal_state_is_durable(
        runtime=runtime,
        store=store,
        principal_id="durable-user",
        session_id="durable-direct",
        expected_state="published",
    )


@pytest.mark.asyncio
async def test_model_output_invalid_terminal_state_is_durable_before_return() -> None:
    store = InMemoryAgentStore()
    runtime = AgentRuntime(
        retrieval_port=EmptyRetrievalPort(),
        controller=InvalidController(),
        answer_generator=UnusedAnswerGenerator(),
        session_store=store,
    )
    await assert_terminal_state_is_durable(
        runtime=runtime,
        store=store,
        principal_id="durable-user",
        session_id="durable-invalid",
        expected_state="model_output_invalid",
    )


@pytest.mark.asyncio
async def test_retrieval_unavailable_terminal_state_is_durable_before_return() -> None:
    store = InMemoryAgentStore()
    runtime = AgentRuntime(
        retrieval_port=UnavailableRetrievalPort(),
        controller=EndlessRetrieveController(),
        answer_generator=UnusedAnswerGenerator(),
        session_store=store,
    )
    await assert_terminal_state_is_durable(
        runtime=runtime,
        store=store,
        principal_id="durable-user",
        session_id="durable-retrieval-down",
        expected_state="retrieval_unavailable",
    )


class FailingAppendStore(InMemoryAgentStore):
    async def append_event(self, principal_id, event):
        raise RuntimeError("durable append failed")


@pytest.mark.asyncio
async def test_durable_append_failure_happens_before_event_listener_visibility() -> None:
    store = FailingAppendStore()
    runtime = AgentRuntime(
        retrieval_port=EmptyRetrievalPort(),
        controller=EndlessRetrieveController(),
        answer_generator=UnusedAnswerGenerator(),
        session_store=store,
    )
    visible_events = []

    with pytest.raises(RuntimeError, match="durable append failed"):
        await runtime.run(
            AgentRunRequest(
                question="hello",
                principal_id="durable-user",
                session_id="durable-failure",
            ),
            event_listener=visible_events.append,
        )

    assert visible_events == []
    assert await store.list_events("durable-user", "durable-failure") == []
