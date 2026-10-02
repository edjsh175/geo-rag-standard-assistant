"""Application-scoped Agent infrastructure dependencies.

This module owns the production AgentStore instance so API entry points share
one durable persistence boundary.  Tests should inject InMemoryAgentStore into
services directly instead of relying on an implicit production fallback.
"""

from __future__ import annotations

from app.services.agent.store import AgentStore, PostgresAgentStore


_agent_store: AgentStore = PostgresAgentStore()


def get_agent_store() -> AgentStore:
    """Return the application-scoped production AgentStore."""

    return _agent_store


__all__ = ["get_agent_store"]
