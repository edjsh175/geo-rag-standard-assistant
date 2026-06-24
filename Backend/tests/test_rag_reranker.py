from __future__ import annotations

from datetime import datetime

import pytest

from app.models.search_models import DocumentResult
from app.services.rag.reranker import RagReranker
from app.services.search_service import SearchService


def make_result(
    doc_id: str,
    title: str,
    standard_code: str | None,
    similarity: float,
    content: str = "",
) -> DocumentResult:
    metadata = {"document_name": title}
    if standard_code:
        metadata["standard_code"] = standard_code
    return DocumentResult(
        id=doc_id,
        title=title,
        content=content,
        similarity=similarity,
        metadata=metadata,
        spatial_info=None,
        file_type="pdf",
        file_size=0,
        upload_time=datetime.now(),
        source_url=None,
    )


def test_reranker_prioritizes_exact_standard_code_without_changing_similarity() -> None:
    reranker = RagReranker()
    results = [
        make_result("noise", "noise", "DB51/T 1000-2024", 0.95),
        make_result("target", "target", "DB50/T 1846-2025", 0.72),
    ]

    reranked = reranker.rerank("DB50_T 1846-2025", results, top_k=10)

    assert [result.id for result in reranked] == ["target", "noise"]
    assert reranked[0].similarity == 0.72
    assert reranked[0].metadata["standard_code_match_type"] == "exact"
    assert "standard_code_exact" in reranked[0].metadata["rerank_reasons"]
    assert isinstance(reranked[0].metadata["rerank_score"], float)


def test_reranker_keeps_stable_order_when_scores_tie() -> None:
    reranker = RagReranker()
    results = [
        make_result("first", "alpha", None, 0.8),
        make_result("second", "beta", None, 0.8),
    ]

    reranked = reranker.rerank("无明显匹配词", results, top_k=10)

    assert [result.id for result in reranked] == ["first", "second"]


@pytest.mark.asyncio
async def test_search_service_skips_reranker_when_use_rerank_false() -> None:
    service = SearchService.__new__(SearchService)

    async def exact_search(query: str, top_k: int) -> list[DocumentResult]:
        return []

    async def keyword_search(query: str, top_k: int) -> list[DocumentResult]:
        return [
            make_result("first", "first", None, 0.4),
            make_result("second", "second", None, 0.9),
        ]

    async def vector_search(*args, **kwargs) -> list[DocumentResult]:
        return []

    async def get_query_embedding(query: str) -> list[float]:
        raise AssertionError("embedding should not run in keyword mode")

    async def fail_rerank(*args, **kwargs) -> list[DocumentResult]:
        raise AssertionError("reranker should not run when use_rerank=False")

    service._exact_standard_code_search = exact_search
    service._keyword_search = keyword_search
    service._vector_search = vector_search
    service._get_query_embedding = get_query_embedding
    service._rerank_results = fail_rerank
    service._log_search = lambda *args, **kwargs: None

    results = await service.search(
        "滑坡防治",
        search_mode="keyword",
        use_rerank=False,
        top_k=10,
    )

    assert [result.id for result in results] == ["first", "second"]
    assert all("rerank_score" not in result.metadata for result in results)
