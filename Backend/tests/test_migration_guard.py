"""Unit tests for startup migration guard."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core.migration_guard import (
    DatabaseMigrationError,
    verify_required_database_tables,
)


@pytest.mark.asyncio
async def test_migration_guard_detects_missing_tables() -> None:
    # Mock engine where only some tables exist
    mock_engine = MagicMock()
    mock_conn = AsyncMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn

    # Simulate query returning only 'documents' and 'geoai_agent_sessions'
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [("documents",), ("geoai_agent_sessions",)]
    mock_conn.execute.return_value = mock_result

    with pytest.raises(DatabaseMigrationError, match="Missing required table"):
        await verify_required_database_tables(mock_engine, required_tables=["documents", "geoai_agent_events"])


@pytest.mark.asyncio
async def test_migration_guard_passes_when_all_tables_exist() -> None:
    mock_engine = MagicMock()
    mock_conn = AsyncMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [("documents",), ("geoai_agent_events",)]
    mock_conn.execute.return_value = mock_result

    # Should pass without error
    await verify_required_database_tables(mock_engine, required_tables=["documents", "geoai_agent_events"])


@pytest.mark.asyncio
async def test_migration_guard_raises_on_none_engine() -> None:
    with pytest.raises(DatabaseMigrationError, match="engine is not initialized"):
        await verify_required_database_tables(None)
