from __future__ import annotations

from datetime import datetime

import pytest

from app.api.search_routes import search_documents
from app.core.auth import UserIdentity
from app.models.search_models import DocumentResult, SearchRequest
from app.services.demo_quota_service import DemoQuotaDecision, DemoQuotaStatus


def make_result(doc_id: str = "doc-1") -> DocumentResult:
    return DocumentResult(
        id=doc_id,
        title="土地利用图制图规范",
        content="土地利用图制图规范相关内容。",
        similarity=0.91,
        metadata={"standard_code": "DB1310/T 365-2025"},
        spatial_info=None,
        file_type="pdf",
        file_size=0,
        upload_time=datetime.now(),
    )


class AssetServiceStub:
    async def enrich_search_results(self, results: list[DocumentResult]) -> list[DocumentResult]:
        return results


class SearchServiceStub:
    def __init__(self) -> None:
        self.generated = False
        self.detected = False

    def _is_document_summary_query(self, query: str) -> bool:
        return False

    async def detect_intent(self, query: str) -> str:
        self.detected = True
        return "search"

    async def search(self, query, top_k, threshold, spatial_filter=None, metadata_filter=None):
        return [make_result()]

    async def generate_answer(self, query, results, top_context_docs=5, history=None):
        self.generated = True
        return "AI 生成回答。", 0.2


class QuotaServiceStub:
    def __init__(self, allowed: bool) -> None:
        self.calls = 0
        self.allowed = allowed

    async def consume_generation(self, visitor_id: str, ip_hash: str) -> DemoQuotaDecision:
        self.calls += 1
        status = DemoQuotaStatus(
            remaining=9 if self.allowed else 0,
            daily_limit=10,
            global_remaining=299 if self.allowed else 0,
            reset_at="2026-05-31T00:00:00+08:00",
            exhausted=not self.allowed,
            contact_text="请联系项目作者获取更多演示额度。",
        )
        return DemoQuotaDecision(allowed=self.allowed, quota=status, reason=None if self.allowed else "visitor_quota_exhausted")


@pytest.mark.asyncio
async def test_visitor_ai_request_consumes_quota_and_generates_answer() -> None:
    search_service = SearchServiceStub()
    quota_service = QuotaServiceStub(allowed=True)

    response = await search_documents(
        SearchRequest(query="土地利用图怎么制图", use_generation=True),
        current_user=UserIdentity(username="demo-visitor", role="visitor", visitor_id="visitor-1", ip_hash="ip-1"),
        search_service=search_service,
        asset_service=AssetServiceStub(),
        quota_service=quota_service,
    )

    assert quota_service.calls == 1
    assert search_service.detected is True
    assert search_service.generated is True
    assert response.generated_answer == "AI 生成回答。"
    assert response.quota is not None
    assert response.quota.remaining == 9


@pytest.mark.asyncio
async def test_visitor_ai_request_exhausted_returns_search_only_response() -> None:
    search_service = SearchServiceStub()

    response = await search_documents(
        SearchRequest(query="土地利用图怎么制图", use_generation=True),
        current_user=UserIdentity(username="demo-visitor", role="visitor", visitor_id="visitor-1", ip_hash="ip-1"),
        search_service=search_service,
        asset_service=AssetServiceStub(),
        quota_service=QuotaServiceStub(allowed=False),
    )

    assert search_service.detected is False
    assert search_service.generated is False
    assert response.generated_answer is None
    assert response.results[0].id == "doc-1"
    assert response.quota is not None
    assert response.quota.exhausted is True
    assert response.quota.contact_text == "请联系项目作者获取更多演示额度。"


@pytest.mark.asyncio
async def test_admin_ai_request_does_not_consume_demo_quota() -> None:
    search_service = SearchServiceStub()
    quota_service = QuotaServiceStub(allowed=False)

    response = await search_documents(
        SearchRequest(query="土地利用图怎么制图", use_generation=True),
        current_user=UserIdentity(username="admin", role="admin"),
        search_service=search_service,
        asset_service=AssetServiceStub(),
        quota_service=quota_service,
    )

    assert quota_service.calls == 0
    assert search_service.detected is True
    assert search_service.generated is True
    assert response.generated_answer == "AI 生成回答。"
    assert response.quota is None


@pytest.mark.asyncio
async def test_search_without_generation_skips_ai_intent_detection() -> None:
    search_service = SearchServiceStub()
    quota_service = QuotaServiceStub(allowed=True)

    response = await search_documents(
        SearchRequest(query="土地利用图怎么制图", use_generation=False),
        current_user=UserIdentity(username="demo-visitor", role="visitor", visitor_id="visitor-1", ip_hash="ip-1"),
        search_service=search_service,
        asset_service=AssetServiceStub(),
        quota_service=quota_service,
    )

    assert quota_service.calls == 0
    assert search_service.detected is False
    assert search_service.generated is False
    assert response.generated_answer is None
    assert response.results[0].id == "doc-1"
