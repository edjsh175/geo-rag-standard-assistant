"""Apply the standard applicability schema migration idempotently."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys

from sqlalchemy import text

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import db_manager


async def _run() -> None:
    await db_manager._init_postgres()
    try:
        migration = (
            BACKEND_ROOT / "migrations" / "20261002_standard_applicability.sql"
        ).read_text(encoding="utf-8")
        executable_sql = "\n".join(
            line for line in migration.splitlines()
            if not line.lstrip().startswith("--")
        )
        statements = [
            statement.strip()
            for statement in executable_sql.split(";")
            if statement.strip()
        ]
        if db_manager.postgres_engine is None:
            raise RuntimeError("PostgreSQL engine is not initialized")
        async with db_manager.postgres_engine.begin() as connection:
            for statement in statements:
                await connection.execute(text(statement))
        print(f"Applied {len(statements)} standard applicability migration statements.")
    finally:
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(_run())
