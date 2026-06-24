"""Search observability persistence."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
import json
import logging
from typing import Any, Optional

from sqlalchemy import text

from app.core.database import db_manager
from app.services.rag.types import SearchContext

logger = logging.getLogger(__name__)

SessionProvider = Callable[[], AbstractAsyncContextManager[Any]]


class RagSearchLogger:
    """Persist search logs without making observability a hard dependency."""

    def __init__(self, session_provider: Optional[SessionProvider] = None) -> None:
        self._session_provider = session_provider

    def build_payload(
        self,
        context: SearchContext,
        results_count: int,
        duration_seconds: float,
        used_rerank: bool,
        embedding_available: Optional[bool],
    ) -> dict[str, Any]:
        return {
            "query": context.query,
            "mode": context.mode,
            "top_k": context.top_k,
            "threshold": context.threshold,
            "filters": {
                "metadata": self._model_dump(context.metadata_filter),
                "spatial": self._model_dump(context.spatial_filter),
            },
            "results_count": results_count,
            "duration_seconds": duration_seconds,
            "used_rerank": used_rerank,
            "embedding_available": embedding_available,
        }

    async def log_search(
        self,
        context: SearchContext,
        results_count: int,
        duration_seconds: float,
        used_rerank: bool,
        embedding_available: Optional[bool],
    ) -> None:
        payload = self.build_payload(
            context,
            results_count=results_count,
            duration_seconds=duration_seconds,
            used_rerank=used_rerank,
            embedding_available=embedding_available,
        )

        session_provider = self._session_provider
        if session_provider is None:
            if not db_manager.postgres_sessionmaker:
                logger.info("Search log skipped because PostgreSQL is unavailable: %s", payload)
                return
            session_provider = db_manager.get_postgres_session

        try:
            sql = text(
                """
                INSERT INTO search_logs (
                    query,
                    mode,
                    top_k,
                    threshold,
                    filters,
                    results_count,
                    duration_seconds,
                    used_rerank,
                    embedding_available,
                    created_at
                )
                VALUES (
                    :query,
                    :mode,
                    :top_k,
                    :threshold,
                    CAST(:filters AS jsonb),
                    :results_count,
                    :duration_seconds,
                    :used_rerank,
                    :embedding_available,
                    NOW()
                )
                """
            )
            async with session_provider() as session:
                await session.execute(
                    sql,
                    {
                        "query": payload["query"],
                        "mode": payload["mode"],
                        "top_k": payload["top_k"],
                        "threshold": payload["threshold"],
                        "filters": json.dumps(payload["filters"], ensure_ascii=False),
                        "results_count": payload["results_count"],
                        "duration_seconds": payload["duration_seconds"],
                        "used_rerank": payload["used_rerank"],
                        "embedding_available": payload["embedding_available"],
                    },
                )
        except Exception as exc:
            logger.warning("Search log persistence failed: %s", exc)

    def _model_dump(self, model: Any) -> Optional[dict[str, Any]]:
        if model is None:
            return None
        if hasattr(model, "model_dump"):
            return model.model_dump(mode="json", exclude_none=True)
        return dict(model)
