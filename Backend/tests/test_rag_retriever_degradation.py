from __future__ import annotations

from datetime import datetime

import pytest

from app.models.search_models import DocumentResult
from app.services.rag.contracts import RetrievalQuery
from app.services.rag.postgres_adapter import PostgresRetrievalAdapter


def make_result(doc_id: str, similarity: float) -> DocumentResult:
    return DocumentResult(
        id=doc_id,
        title=doc_id,
        content="",
        similarity=similarity,
        metadata={"document_name": doc_id},
        spatial_info=None,
        file_type="pdf",
        file_size=0,
        upload_time=datetime.now(),
        source_url=None,
    )


@pytest.mark.asyncio
async def test_retriever_keeps_exact_and_keyword_when_embedding_fails() -> None:
    async def get_query_embedding(query: str) -> list[float]:
        raise RuntimeError("embedding provider unavailable")

    async def exact_search(query: str, top_k: int) -> list[DocumentResult]:
        return [make_result("exact", 1.0)]

    async def keyword_search(query: str, top_k: int) -> list[DocumentResult]:
        return [make_result("keyword", 0.8)]

    async def vector_search(*args, **kwargs) -> list[DocumentResult]:
        raise AssertionError("vector search should not run without embedding")

    retriever = PostgresRetrievalAdapter()
    retriever._get_query_embedding = get_query_embedding  # type: ignore[method-assign]
    retriever._exact_standard_code_search = exact_search  # type: ignore[method-assign]
    retriever._keyword_search = keyword_search  # type: ignore[method-assign]
    retriever._vector_search = vector_search  # type: ignore[method-assign]

    retrieved = await retriever.retrieve(
        RetrievalQuery(
            query_text="DB50/T 1846-2025",
            top_k=10,
            threshold=0.7,
            search_mode="hybrid",
        )
    )

    assert [candidate.chunk_id for candidate in retrieved.candidates] == ["exact", "keyword"]
    assert retrieved.embedding_available is False
    assert retrieved.diagnostics.exact_count == 1
    assert retrieved.diagnostics.keyword_count == 1
    assert retrieved.diagnostics.vector_count == 0
    assert retrieved.diagnostics.is_degraded is True
    assert retrieved.diagnostics.unavailable_channels == ("vector",)


@pytest.mark.asyncio
async def test_retriever_distinguishes_total_backend_unavailability_from_zero_matches() -> None:
    async def unavailable_exact(query: str, top_k: int) -> list[DocumentResult]:
        raise RuntimeError("postgres unavailable")

    async def unavailable_keyword(query: str, top_k: int) -> list[DocumentResult]:
        raise RuntimeError("postgres unavailable")

    retriever = PostgresRetrievalAdapter()
    retriever._exact_standard_code_search = unavailable_exact  # type: ignore[method-assign]
    retriever._keyword_search = unavailable_keyword  # type: ignore[method-assign]

    retrieved = await retriever.retrieve(
        RetrievalQuery(
            query_text="规划标准",
            top_k=10,
            search_mode="keyword",
        )
    )

    assert retrieved.candidates == ()
    assert retrieved.diagnostics.is_fully_unavailable is True
    assert retrieved.diagnostics.unavailable_channels == ("exact", "keyword")
