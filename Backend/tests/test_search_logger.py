from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from app.models.search_models import MetadataFilter, SpatialFilter
from app.services.rag.search_logger import RagSearchLogger
from app.services.rag.types import SearchContext


def make_context() -> SearchContext:
    return SearchContext(
        query="重庆滑坡防治",
        top_k=5,
        threshold=0.35,
        search_mode="hybrid",
        use_rerank=True,
        metadata_filter=MetadataFilter(region="重庆市"),
        spatial_filter=SpatialFilter(
            geometry={"type": "Point", "coordinates": [105.5, 29.5]},
            spatial_relation="near",
            distance=5000,
        ),
    )


def test_search_logger_builds_serializable_payload() -> None:
    logger = RagSearchLogger()

    payload = logger.build_payload(
        make_context(),
        results_count=3,
        duration_seconds=0.123,
        used_rerank=True,
        embedding_available=False,
    )

    assert payload["query"] == "重庆滑坡防治"
    assert payload["mode"] == "hybrid"
    assert payload["top_k"] == 5
    assert payload["threshold"] == 0.35
    assert payload["filters"]["metadata"]["region"] == "重庆市"
    assert payload["filters"]["spatial"]["spatial_relation"] == "near"
    assert payload["results_count"] == 3
    assert payload["duration_seconds"] == 0.123
    assert payload["used_rerank"] is True
    assert payload["embedding_available"] is False


@pytest.mark.asyncio
async def test_search_logger_persists_payload_without_blocking() -> None:
    executed: dict = {}

    class FakeSession:
        async def execute(self, statement, params):
            executed["statement"] = statement
            executed["params"] = params

    @asynccontextmanager
    async def session_provider():
        yield FakeSession()

    logger = RagSearchLogger(session_provider=session_provider)

    await logger.log_search(
        make_context(),
        results_count=3,
        duration_seconds=0.123,
        used_rerank=True,
        embedding_available=False,
    )

    assert "INSERT INTO search_logs" in str(executed["statement"])
    assert executed["params"]["query"] == "重庆滑坡防治"
    assert executed["params"]["results_count"] == 3


@pytest.mark.asyncio
async def test_search_logger_ignores_persistence_failure() -> None:
    @asynccontextmanager
    async def broken_session_provider():
        raise RuntimeError("database down")
        yield

    logger = RagSearchLogger(session_provider=broken_session_provider)

    await logger.log_search(
        make_context(),
        results_count=0,
        duration_seconds=0.01,
        used_rerank=False,
        embedding_available=False,
    )
