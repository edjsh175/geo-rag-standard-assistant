"""P0 regression tests for the AgentStore single-truth-source contract."""

from __future__ import annotations

import pytest

from app.services.agent.store import (
    AgentStoreUnavailableError,
    InMemoryAgentStore,
    PostgresAgentStore,
)


class _UnavailableManager:
    postgres_sessionmaker = None


@pytest.mark.asyncio
async def test_production_postgres_store_fails_closed_without_explicit_fallback() -> None:
    store = PostgresAgentStore(manager=_UnavailableManager())

    with pytest.raises(AgentStoreUnavailableError, match="refusing process-local fallback"):
        await store.get_or_create_session("user-1", "session-1")


@pytest.mark.asyncio
async def test_inmemory_fallback_requires_explicit_injection() -> None:
    fallback = InMemoryAgentStore()
    store = PostgresAgentStore(manager=_UnavailableManager(), fallback=fallback)

    session = await store.get_or_create_session("user-1", "session-1")

    assert session.principal_id == "user-1"
    assert session.session_id == "session-1"
    assert await fallback.get_session("user-1", "session-1") is session


def test_search_and_agent_routes_share_application_scoped_agent_store() -> None:
    from app.api import agent_routes, search_routes

    assert agent_routes._store is search_routes._agent_session_store
    assert agent_routes.get_agent_session_service().session_store is agent_routes._store
    assert agent_routes.get_agent_trace_service().session_store is agent_routes._store
