from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from app.core.database import db_manager
from app.services.geosql.contracts import CompiledGeoQuery


class GeoQueryExecutor:
    def __init__(self, *, statement_timeout_ms: int = 3000) -> None:
        if not 100 <= statement_timeout_ms <= 30000:
            raise ValueError("GeoSQL statement_timeout_ms must be between 100 and 30000")
        self.statement_timeout_ms = statement_timeout_ms

    async def execute(self, query: CompiledGeoQuery) -> list[dict[str, Any]]:
        sql = query.sql.strip()
        if not sql.upper().startswith("SELECT ") or ";" in sql:
            raise ValueError("GeoSQL executor accepts one SELECT statement only")
        async with db_manager.get_postgres_session() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            await session.execute(
                text("SELECT set_config('statement_timeout', :timeout_ms, true)"),
                {"timeout_ms": str(self.statement_timeout_ms)},
            )
            result = await session.execute(text(sql), dict(query.params))
            rows = [dict(row) for row in result.mappings().all()]

        for row in rows:
            geometry = row.get("geometry")
            if isinstance(geometry, str):
                row["geometry"] = json.loads(geometry)
        return rows
