"""
Startup and deployment database schema / migration verification guard.
Prevents runtime UndefinedTableError exceptions by verifying schema readiness at startup.
"""

from __future__ import annotations

import logging
from typing import Sequence
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


class DatabaseMigrationError(RuntimeError):
    """Raised when required database tables or migration states are missing."""


REQUIRED_TABLE_MIGRATION_MAP: dict[str, str] = {
    # 20260617_api_contract_tables.sql
    "search_feedback": "Backend/migrations/20260617_api_contract_tables.sql",
    "document_overrides": "Backend/migrations/20260617_api_contract_tables.sql",
    "document_reindex_jobs": "Backend/migrations/20260617_api_contract_tables.sql",
    "search_logs": "Backend/migrations/20260617_api_contract_tables.sql",
    # 20260618_document_lifecycle.sql
    "documents": "Backend/migrations/20260618_document_lifecycle.sql",
    "document_versions": "Backend/migrations/20260618_document_lifecycle.sql",
    "document_chunks": "Backend/migrations/20260618_document_lifecycle.sql",
    "index_jobs": "Backend/migrations/20260618_document_lifecycle.sql",
    "document_events": "Backend/migrations/20260618_document_lifecycle.sql",
    # 20260925_agent_context_persistence.sql
    "geoai_agent_sessions": "Backend/migrations/20260925_agent_context_persistence.sql",
    "geoai_agent_events": "Backend/migrations/20260925_agent_context_persistence.sql",
    "geoai_agent_evidence": "Backend/migrations/20260925_agent_context_persistence.sql",
    "geoai_agent_evidence_activations": "Backend/migrations/20260926_agent_evidence_activations.sql",
    "geoai_context_snapshots": "Backend/migrations/20260925_agent_context_persistence.sql",
    "geoai_pending_browser_executions": "Backend/migrations/20260925_agent_context_persistence.sql",
}


async def verify_required_database_tables(
    engine: AsyncEngine | None,
    required_tables: Sequence[str] | None = None,
) -> None:
    """Verify that all required tables exist in PostgreSQL public schema and embedding dimension invariants hold."""
    from app.core.config import validate_embedding_dimension_invariants

    validate_embedding_dimension_invariants()

    if engine is None:
        raise DatabaseMigrationError("PostgreSQL engine is not initialized.")

    tables_to_check = required_tables or list(REQUIRED_TABLE_MIGRATION_MAP.keys())

    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        existing_tables = {row[0] for row in result.fetchall()}

    missing = [tbl for tbl in tables_to_check if tbl not in existing_tables]
    if missing:
        migrations_needed = sorted(
            {REQUIRED_TABLE_MIGRATION_MAP.get(tbl, "Backend/migrations/*.sql") for tbl in missing}
        )
        msg = (
            f"Database schema verification failed. Missing required table(s): {', '.join(missing)}. "
            f"Please apply migration(s): {', '.join(migrations_needed)}"
        )
        logger.error(msg)
        raise DatabaseMigrationError(msg)

    logger.info("All %d required database tables verified successfully.", len(tables_to_check))
