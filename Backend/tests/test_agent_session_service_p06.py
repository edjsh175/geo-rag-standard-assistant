"""Tests for Phase P: P-06 Server-Authoritative Conversation History & Session Service."""
from __future__ import annotations

from types import SimpleNamespace
import pytest
from fastapi import FastAPI
import httpx

from app.api.agent_routes import get_agent_session_service, router as agent_router
from app.core.security import require_authenticated_user
from app.services.agent.events import AgentEvent
from app.services.agent.session import AgentSession, PendingBrowserExecution
from app.services.agent.session_service import AgentSessionService
from app.services.agent.store import InMemoryAgentStore


@pytest.mark.asyncio
async def test_session_service_list_and_detail_reconstruction() -> None:
    store = InMemoryAgentStore()
    service = AgentSessionService(session_store=store)

    principal_id = "admin:alice"
    session_id = "sess-100"

    session = await store.get_or_create_session(principal_id, session_id)
    await store.save_session(session)

    # Append user_message
    await store.append_event(
        principal_id,
        AgentEvent(
            event_type="user_message",
            session_id=session_id,
            turn_id="turn-1",
            trace_id="tr-1",
            payload={"text": "成都市有哪些绿地规划标准？"},
        ),
    )

    # Append publication_completed
    await store.append_event(
        principal_id,
        AgentEvent(
            event_type="publication_completed",
            session_id=session_id,
            turn_id="turn-1",
            trace_id="tr-1",
            payload={
                "generated_answer": "成都市绿地系统规划明确了以下指标：...",
                "results": [{"id": "doc-1", "title": "成都市城市绿线管理办法"}],
                "map_action": {"type": "locate_map", "target": "cesium"},
                "state": "published",
            },
        ),
    )

    # List sessions
    sessions = await service.list_sessions(principal_id=principal_id)
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == session_id

    # Get session detail
    detail = await service.get_session_detail(principal_id=principal_id, session_id=session_id)
    assert detail is not None
    assert detail["session_id"] == session_id
    assert len(detail["messages"]) == 2

    user_msg = detail["messages"][0]
    assert user_msg["role"] == "user"
    assert user_msg["content"] == "成都市有哪些绿地规划标准？"
    assert user_msg["turn_id"] == "turn-1"

    asst_msg = detail["messages"][1]
    assert asst_msg["role"] == "assistant"
    assert "成都市绿地系统规划" in asst_msg["content"]
    assert len(asst_msg["references"]) == 1
    assert asst_msg["map_action"] == {"type": "locate_map", "target": "cesium"}

    assert len(detail["turns"]) == 1
    assert detail["turns"][0]["turn_id"] == "turn-1"
    assert detail["turns"][0]["status"] == "published"


@pytest.mark.asyncio
async def test_session_service_delete_session() -> None:
    store = InMemoryAgentStore()
    service = AgentSessionService(session_store=store)

    principal_id = "admin:alice"
    session_id = "sess-to-delete"

    session = await store.get_or_create_session(principal_id, session_id)
    await store.save_session(session)

    # Delete
    deleted = await service.delete_session(principal_id=principal_id, session_id=session_id)
    assert deleted is True

    # Re-query
    detail = await service.get_session_detail(principal_id=principal_id, session_id=session_id)
    assert detail is None

    sessions = await service.list_sessions(principal_id=principal_id)
    assert len(sessions) == 0


@pytest.mark.asyncio
async def test_agent_routes_session_endpoints_e2e() -> None:
    store = InMemoryAgentStore()
    service = AgentSessionService(session_store=store)

    principal_id = "admin:bob"
    session_id = "sess-api-test"

    session = await store.get_or_create_session(principal_id, session_id)
    await store.save_session(session)
    await store.append_event(
        principal_id,
        AgentEvent(
            event_type="user_message",
            session_id=session_id,
            turn_id="turn-1",
            trace_id="tr-test",
            payload={"text": "测试会话问题"},
        ),
    )

    app = FastAPI()
    app.include_router(agent_router, prefix="/api/agent")

    user_identity = SimpleNamespace(role="admin", username="bob", visitor_id=None)
    app.dependency_overrides[require_authenticated_user] = lambda: user_identity
    app.dependency_overrides[get_agent_session_service] = lambda: service

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # GET /api/agent/sessions
        resp = await client.get("/api/agent/sessions")
        assert resp.status_code == 200
        sess_list = resp.json()
        assert len(sess_list) == 1
        assert sess_list[0]["session_id"] == session_id

        # GET /api/agent/sessions/{session_id}
        resp = await client.get(f"/api/agent/sessions/{session_id}")
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["session_id"] == session_id
        assert len(detail["messages"]) == 1
        assert detail["messages"][0]["content"] == "测试会话问题"

        # GET /api/agent/sessions/nonexistent -> 404
        resp404 = await client.get("/api/agent/sessions/nonexistent")
        assert resp404.status_code == 404

        # DELETE /api/agent/sessions/{session_id}
        del_resp = await client.delete(f"/api/agent/sessions/{session_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["deleted"] is True

        # After delete -> 404
        resp_after_del = await client.get(f"/api/agent/sessions/{session_id}")
        assert resp_after_del.status_code == 404
