from __future__ import annotations

from datetime import datetime

import pytest

from app.models.search_models import DocumentResult
from app.services.agent.controller import ControllerOutputError
from app.services.agent.runtime import AgentRunRequest, AgentRuntime
from app.services.agent.store import InMemoryAgentStore
from app.services.agent.tool_runtime import ToolCall
from app.services.rag.contracts import (
    RetrievalChannelDiagnostic,
    RetrievalCandidate,
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


class OneCandidateRetrievalPort(EmptyRetrievalPort):
    async def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        result = DocumentResult(
            id="chunk-1",
            title="Planning standard",
            content="durable evidence",
            similarity=0.95,
            metadata={"chunk_id": "chunk-1", "match_type": "keyword"},
            spatial_info=None,
            file_type="pdf",
            file_size=0,
            upload_time=datetime.now(),
            source_url=None,
        )
        return RetrievalResult(
            candidates=(RetrievalCandidate.from_document_result(result),),
            embedding_available=False,
            diagnostics=RetrievalDiagnostics(keyword_count=1),
        )


class RetrieveThenInvalidController:
    def __init__(self) -> None:
        self.calls = 0

    async def decide(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return ToolCall(
                tool_call_id="retrieve-once",
                name="retrieve_kb",
                arguments={"query": "test"},
            )
        raise ControllerOutputError("invalid after retrieval")


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


@pytest.mark.asyncio
async def test_evidence_activation_is_durable_even_when_next_controller_step_fails() -> None:
    store = InMemoryAgentStore()
    runtime = AgentRuntime(
        retrieval_port=OneCandidateRetrievalPort(),
        controller=RetrieveThenInvalidController(),
        answer_generator=UnusedAnswerGenerator(),
        session_store=store,
    )

    result = await runtime.run(
        AgentRunRequest(
            question="retrieve then fail",
            principal_id="durable-user",
            session_id="durable-evidence",
        )
    )

    assert result.publication_state == "model_output_invalid"
    activations = await store.list_evidence_activations(
        "durable-user",
        "durable-evidence",
    )
    assert list(activations) == [result.turn_id]
    assert len(activations[result.turn_id]) == 1
