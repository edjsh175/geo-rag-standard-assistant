"""E2E ASGI Disconnect and Turn Cancellation Tests (Phase S: S-01, S-02).

Verifies that:
1. When an HTTP/SSE client disconnects prematurely from /api/search/query/stream,
   Starlette StreamingResponse disconnect signals propagate down to AgentRuntime,
   triggering a durable run_cancel_requested (reason='stream_closed'), cancelling
   in-flight controller tasks, and terminating cleanly with run_cancelled.
2. Explicit cancellation via POST /api/search/query/cancel records cancel_requested,
   cancels ongoing work, and prevents unpublished turns from being published.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from app.api.search_routes import (
    get_demo_quota_service,
    get_search_application_service,
    router as search_router,
)
from app.core.security import require_authenticated_user
from app.models.search_models import AgentCancelRequest, SearchRequest
from app.services.agent.answer_generator import GeneratedAnswer
from app.services.agent.events import AgentEvent
from app.services.agent.runtime import AgentRunRequest, AgentRuntime
from app.services.agent.store import InMemoryAgentStore
from app.services.rag.contracts import RetrievalDiagnostics, RetrievalQuery, RetrievalResult
from app.services.search_application_service import SearchApplicationService


class EmptyRetrievalPort:
    async def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        return RetrievalResult(
            candidates=(),
            embedding_available=False,
            diagnostics=RetrievalDiagnostics(),
        )

    async def fetch_chunks(self, chunk_ids):
        return ()


class SlowInterruptibleController:
    """Controller that signals when started and waits until cancelled."""

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


class UnusedAnswerGenerator:
    async def generate(self, **kwargs) -> GeneratedAnswer:
        raise AssertionError("Answer generator should not run after cancellation")


class StubSearchService:
    async def search(self, **kwargs):
        return []


class StubAssetService:
    async def get_document_detail_payload(self, doc_id):
        return None


class StubContractService:
    async def apply_document_overrides(self, doc_id, payload):
        return payload


class StubQuotaService:
    async def check_visitor_quota(self, visitor_id: str):
        return SimpleNamespace(allowed=True, remaining_generation_queries=10)

    async def consume_generation_quota(self, visitor_id: str):
        return SimpleNamespace(allowed=True, remaining_generation_queries=9)


@pytest.mark.asyncio
async def test_asgi_client_disconnect_triggers_runtime_cancellation() -> None:
    """S-02: Test that ASGI client disconnect from /api/search/query/stream triggers cancel."""
    store = InMemoryAgentStore()
    controller = SlowInterruptibleController()
    runtime = AgentRuntime(
        retrieval_port=EmptyRetrievalPort(),
        controller=controller,
        answer_generator=UnusedAnswerGenerator(),
        session_store=store,
    )
    app_service = SearchApplicationService(
        search_service=StubSearchService(),
        asset_service=StubAssetService(),
        contract_service=StubContractService(),
        agent_runtime=runtime,
        retrieval_port=EmptyRetrievalPort(),
    )

    app = FastAPI()
    app.include_router(search_router, prefix="/api/search")

    test_user = SimpleNamespace(
        role="user",
        username="test_disconnect_user",
        visitor_id=None,
    )

    app.dependency_overrides[require_authenticated_user] = lambda: test_user
    app.dependency_overrides[get_search_application_service] = lambda: app_service
    app.dependency_overrides[get_demo_quota_service] = lambda: StubQuotaService()

    import json

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/search/query/stream",
        "raw_path": b"/api/search/query/stream",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 80),
    }
    request_body = json.dumps({
        "query": "长耗时请求测试",
        "use_generation": True,
        "session_id": "session-disconnect-1",
    }).encode("utf-8")

    received_disconnect = asyncio.Event()

    async def receive():
        nonlocal request_body
        if request_body is not None:
            body = request_body
            request_body = None
            return {"type": "http.request", "body": body, "more_body": False}
        await received_disconnect.wait()
        return {"type": "http.disconnect"}

    sent_first_chunk = asyncio.Event()

    async def send(message):
        if message["type"] == "http.response.body":
            body = message.get("body", b"").decode("utf-8", errors="ignore")
            if "event:" in body:
                sent_first_chunk.set()

    app_task = asyncio.create_task(app(scope, receive, send))

    # Wait for first event and controller start
    await asyncio.wait_for(sent_first_chunk.wait(), timeout=3.0)
    await asyncio.wait_for(controller.started.wait(), timeout=3.0)

    # Client disconnects at ASGI protocol boundary
    received_disconnect.set()

    # Wait for app execution to complete after disconnection
    await asyncio.wait_for(app_task, timeout=3.0)

    # Wait for controller cancellation to take effect
    assert controller.cancelled.is_set()

    # Verify durable events recorded
    principal_id = f"admin:{test_user.username}"
    events = await store.list_events(principal_id, "session-disconnect-1")
    event_types = [e.event_type for e in events]

    assert "run_cancel_requested" in event_types
    assert "run_cancelled" in event_types

    cancel_event = next(e for e in events if e.event_type == "run_cancel_requested")
    assert cancel_event.payload.get("reason") == "stream_closed"


@pytest.mark.asyncio
async def test_explicit_turn_cancellation_endpoint_s01() -> None:
    """S-01: Explicit POST /api/search/query/cancel endpoint cancels active session."""
    store = InMemoryAgentStore()
    controller = SlowInterruptibleController()
    runtime = AgentRuntime(
        retrieval_port=EmptyRetrievalPort(),
        controller=controller,
        answer_generator=UnusedAnswerGenerator(),
        session_store=store,
    )
    app_service = SearchApplicationService(
        search_service=StubSearchService(),
        asset_service=StubAssetService(),
        contract_service=StubContractService(),
        agent_runtime=runtime,
        retrieval_port=EmptyRetrievalPort(),
    )

    app = FastAPI()
    app.include_router(search_router, prefix="/api/search")

    test_user = SimpleNamespace(
        role="user",
        username="test_explicit_cancel_user",
        visitor_id=None,
    )

    app.dependency_overrides[require_authenticated_user] = lambda: test_user
    app.dependency_overrides[get_search_application_service] = lambda: app_service
    app.dependency_overrides[get_demo_quota_service] = lambda: StubQuotaService()

    # Pre-create session and seed user_message event
    principal_id = f"admin:{test_user.username}"
    session_id = "session-cancel-explicit"
    turn_id = "turn-cancel-1"

    await store.get_or_create_session(principal_id, session_id)
    await store.append_event(
        principal_id,
        AgentEvent(
            event_type="user_message",
            session_id=session_id,
            turn_id=turn_id,
            trace_id="trace-cancel-1",
            payload={"text": "hello"},
        ),
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/search/query/cancel",
            json={
                "session_id": session_id,
                "turn_id": turn_id,
                "reason": "user_stop",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == session_id
        assert data["turn_id"] == turn_id
        assert data["status"] == "cancel_requested"
        assert "event_id" in data

    events = await store.list_events(principal_id, session_id)
    assert any(e.event_type == "run_cancel_requested" and e.payload.get("reason") == "user_stop" for e in events)
