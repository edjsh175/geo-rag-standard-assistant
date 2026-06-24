from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.models.search_models import DocumentResult
from app.services.search_service import SearchService


def make_result(
    doc_id: str,
    title: str,
    standard_code: str | None,
    similarity: float,
) -> DocumentResult:
    metadata = {"document_name": title}
    if standard_code is not None:
        metadata["standard_code"] = standard_code

    return DocumentResult(
        id=doc_id,
        title=title,
        content=f"content for {title}",
        similarity=similarity,
        metadata=metadata,
        spatial_info=None,
        file_type="pdf",
        file_size=0,
        upload_time=datetime.now(),
        source_url=None,
    )


def build_service() -> SearchService:
    return SearchService.__new__(SearchService)


def test_extract_keyword_terms_preserves_spaced_chinese_terms() -> None:
    service = build_service()

    terms = service._extract_keyword_terms("\u6ed1\u5761\u9632\u6cbb \u76d1\u6d4b")

    assert "\u6ed1\u5761\u9632\u6cbb" in terms
    assert "\u76d1\u6d4b" in terms


def test_policy_chunk_result_carries_filterable_metadata() -> None:
    service = build_service()
    row = SimpleNamespace(
        id=1,
        standard_code="DB50_T 1846-2025",
        document_name="DB50_T 1846-2025 \u964d\u96e8\u8bf1\u53d1\u6ed1\u5761\u98ce\u9669\u9884\u8b66\u89c4\u8303.zip",
        content="\u6ed1\u5761\u76d1\u6d4b",
        category="\u5730\u65b9\u6807\u51c6",
        keyword="\u6ed1\u5761 \u76d1\u6d4b",
        chinese_name="\u964d\u96e8\u8bf1\u53d1\u6ed1\u5761\u98ce\u9669\u9884\u8b66\u89c4\u8303",
        english_name=None,
        release_date="2025-03-01",
        implement_date="2025-06-01",
        standard_status="\u73b0\u884c",
        release_unit="\u91cd\u5e86\u5e02\u5e02\u573a\u76d1\u7763\u7ba1\u7406\u5c40",
        charge_unit=None,
        draft_unit=None,
        application_scope=None,
    )

    result = service._build_policy_chunk_result(row, similarity=0.9, match_type="keyword")

    assert result.file_type == "zip"
    assert result.metadata["document_type"] == "\u6807\u51c6\u89c4\u8303"
    assert result.metadata["release_date"] == "2025-03-01"
    assert result.metadata["source"] == "\u91cd\u5e86\u5e02\u5e02\u573a\u76d1\u7763\u7ba1\u7406\u5c40"


@pytest.mark.asyncio
async def test_rerank_prioritizes_exact_standard_code_matches() -> None:
    service = build_service()
    results = [
        make_result("noise-1", "noise 1", "DB1310_T 365-2025", 0.95),
        make_result("target-1", "target 1", "DB50/T 1846-2025", 0.82),
        make_result("target-2", "target 2", "DB50_T 1846-2025", 0.80),
        make_result("noise-2", "noise 2", "DB50/T 1900-2025", 0.79),
    ]

    reranked = await service._rerank_results("DB50_T 1846-2025", results, top_k=10)

    assert [result.id for result in reranked[:2]] == ["target-1", "target-2"]
    assert reranked[0].metadata["standard_code_match_type"] == "exact"
    assert reranked[1].metadata["standard_code_match_type"] == "exact"
    assert reranked[2].metadata["standard_code_match_type"] == "none"


@pytest.mark.asyncio
async def test_rerank_tolerates_standard_code_format_variants() -> None:
    service = build_service()
    results = [
        make_result("noise", "noise", "GB/T 11111-2020", 0.90),
        make_result("target", "target", "GB_T 38509-2020", 0.70),
    ]

    reranked = await service._rerank_results("GBT385092020", results, top_k=10)

    assert reranked[0].id == "target"
    assert reranked[0].metadata["standard_code_match_type"] == "exact"


@pytest.mark.asyncio
async def test_rerank_preserves_order_when_no_exact_standard_code_match() -> None:
    service = build_service()
    results = [
        make_result("first", "first", "DB50/T 1900-2025", 0.91),
        make_result("second", "second", "DB50/T 1846-2024", 0.88),
    ]

    reranked = await service._rerank_results("DB50_T 1846-2025", results, top_k=10)

    assert [result.id for result in reranked] == ["first", "second"]
    assert reranked[0].metadata["standard_code_match_type"] == "none"
    assert reranked[1].metadata["standard_code_match_type"] == "none"


@pytest.mark.asyncio
async def test_rerank_ignores_natural_language_queries() -> None:
    service = build_service()
    results = [
        make_result("first", "滑坡防治设计规范", "GB/T 38509-2020", 0.90),
        make_result("second", "其他规范", "DB50/T 1846-2025", 0.85),
    ]

    reranked = await service._rerank_results("滑坡防治设计规范", results, top_k=10)

    assert [result.id for result in reranked] == ["first", "second"]
    assert "standard_code_match_type" not in reranked[0].metadata
    assert "standard_code_match_type" not in reranked[1].metadata
