from __future__ import annotations

from datetime import datetime

import pytest

from app.models.search_models import DocumentResult
from app.services.rag.retriever import RagRetriever
from app.services.rag.types import SearchContext


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

    retriever = RagRetriever(
        get_query_embedding=get_query_embedding,
        exact_standard_code_search=exact_search,
        keyword_search=keyword_search,
        vector_search=vector_search,
    )

    retrieved = await retriever.retrieve(
        SearchContext(
            query="DB50/T 1846-2025",
            top_k=10,
            threshold=0.7,
            search_mode="hybrid",
        )
    )

    assert [result.id for result in retrieved.results] == ["exact", "keyword"]
    assert retrieved.embedding_available is False
    assert retrieved.exact_count == 1
    assert retrieved.keyword_count == 1
    assert retrieved.vector_count == 0
