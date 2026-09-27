"""Unit tests for startup migration guard."""

from __future__ import annotations

from pathlib import Path
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core.migration_guard import (
    DatabaseMigrationError,
    REQUIRED_TABLE_MIGRATION_MAP,
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


def test_model_input_audit_table_is_required_by_migration_guard() -> None:
    assert REQUIRED_TABLE_MIGRATION_MAP["geoai_model_input_audits"] == (
        "Backend/migrations/20260926_model_input_audit.sql"
    )


def test_model_input_audit_identity_scope_has_forward_migration() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    migration = (
        repo_root
        / "Backend"
        / "migrations"
        / "20260926_model_input_audit_identity_scope.sql"
    )

    sql = migration.read_text(encoding="utf-8")
    assert "DROP CONSTRAINT IF EXISTS uq_geoai_model_input_audits_call_attempt" in sql
    assert "uq_geoai_model_input_audits_scoped_call_attempt" in sql
    assert "principal_id, session_id, turn_id, stage, call_id, attempt" in sql


def test_spatial_regions_table_is_required_by_migration_guard() -> None:
    assert REQUIRED_TABLE_MIGRATION_MAP["spatial_regions"] == (
        "Backend/migrations/20260927_spatial_regions.sql"
    )
    repo_root = Path(__file__).resolve().parents[2]
    migration = (
        repo_root
        / "Backend"
        / "migrations"
        / "20260927_spatial_regions.sql"
    )
    assert migration.exists()
    sql = migration.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS spatial_regions" in sql
    assert "GEOMETRY(MultiPolygon, 4326)" in sql
    assert "uq_spatial_regions_adcode" in sql
    assert "idx_spatial_regions_geometry" in sql

