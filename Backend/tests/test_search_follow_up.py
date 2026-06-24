from __future__ import annotations

from datetime import datetime

import pytest

from app.api.search_routes import search_documents
from app.models.search_models import DocumentResult, FollowUpContext, SearchRequest
from app.services.search_service import SearchService


def make_document_detail(doc_id: str, content: str = "文档内容摘要") -> dict:
    return {
        "id": doc_id,
        "title": "DB37_T 4798-2024 国有储备土地资产负债核算技术规范",
        "content": content,
        "metadata": {
            "description": "适用于国有储备土地资产负债核算。",
            "keywords": ["土地", "储备"],
            "custom_fields": {"standard_code": "DB37_T 4798-2024"},
        },
        "spatial_info": None,
        "file_info": {
            "type": "pdf",
            "size": 1024,
            "upload_time": datetime.now(),
            "filename": "DB37_T 4798-2024.pdf",
            "mime_type": "application/pdf",
        },
        "standard_info": {
            "code": "DB37_T 4798-2024",
            "status": "现行",
        },
        "download_available": True,
        "download_url": f"/api/documents/{doc_id}/download",
    }


def make_result(doc_id: str, title: str = "result") -> DocumentResult:
    return DocumentResult(
        id=doc_id,
        title=title,
        content=f"content for {title}",
        similarity=0.88,
        metadata={"document_name": title, "standard_code": "DB37_T 4798-2024"},
        spatial_info=None,
        file_type="pdf",
        file_size=0,
        upload_time=datetime.now(),
        source_url=None,
    )


class AssetServiceStub:
    def __init__(self, detail: dict | None = None) -> None:
        self.detail = detail

    async def get_document_detail_payload(self, doc_id: str) -> dict | None:
        return self.detail

    async def enrich_search_results(self, results: list[DocumentResult]) -> list[DocumentResult]:
        return results


@pytest.mark.asyncio
async def test_load_follow_up_document_result_returns_single_document_result() -> None:
    service = SearchService.__new__(SearchService)
    detail = make_document_detail("14741", content="第一条。第二条。第三条。")
    asset_service = AssetServiceStub(detail)
    context = FollowUpContext(
        target_document_id="14741",
        candidate_documents=[],
        resolution_source="explicit_text",
    )

    loaded_detail, result = await service.load_follow_up_document_result(context, asset_service)

    assert loaded_detail == detail
    assert result is not None
    assert result.id == "14741"
    assert result.similarity == 1.0
    assert result.metadata["standard_code"] == "DB37_T 4798-2024"
    assert result.metadata["follow_up_resolution_source"] == "explicit_text"


@pytest.mark.asyncio
async def test_load_follow_up_document_result_returns_none_for_empty_content() -> None:
    service = SearchService.__new__(SearchService)
    detail = make_document_detail("14741", content="   ")
    asset_service = AssetServiceStub(detail)
    context = FollowUpContext(
        target_document_id="14741",
        candidate_documents=[],
        resolution_source="selected_document",
    )

    loaded_detail, result = await service.load_follow_up_document_result(context, asset_service)

    assert loaded_detail is None
    assert result is None


@pytest.mark.asyncio
async def test_search_documents_uses_follow_up_context_before_regular_search() -> None:
    detail = make_document_detail("14741")
    follow_up_result = make_result("14741", "follow-up")

    class SearchServiceStub:
        async def load_follow_up_document_result(self, follow_up_context, asset_service):
            return detail, follow_up_result

        async def generate_document_follow_up_answer(self, query, document_detail, history=None):
            assert document_detail["id"] == "14741"
            return "这是该标准的主要内容摘要。", 0.12

        async def detect_intent(self, query: str) -> str:  # pragma: no cover - should not run
            raise AssertionError("detect_intent should not run for resolved follow-up questions")

    request = SearchRequest(
        query="第一个14741的主要内容是什么",
        use_generation=True,
        follow_up_context=FollowUpContext(
            target_document_id="14741",
            candidate_documents=[],
            resolution_source="explicit_text",
        ),
    )

    response = await search_documents(
        request,
        search_service=SearchServiceStub(),
        asset_service=AssetServiceStub(detail),
    )

    assert response.generated_answer == "这是该标准的主要内容摘要。"
    assert response.total_count == 1
    assert response.results[0].id == "14741"


@pytest.mark.asyncio
async def test_search_documents_falls_back_to_regular_search_when_follow_up_target_missing() -> None:
    regular_result = make_result("22898", "regular-search")

    class SearchServiceStub:
        def __init__(self) -> None:
            self.search_called = False

        async def load_follow_up_document_result(self, follow_up_context, asset_service):
            return None, None

        async def detect_intent(self, query: str) -> str:
            return "search"

        async def search(
            self,
            query,
            top_k,
            threshold,
            spatial_filter=None,
            metadata_filter=None,
            search_mode="hybrid",
            use_rerank=True,
        ):
            self.search_called = True
            return [regular_result]

        async def generate_answer(self, query, results, top_context_docs=5, history=None):
            return "回退后的常规检索回答。", 0.23

    search_service = SearchServiceStub()
    request = SearchRequest(
        query="14741的主要内容是什么",
        use_generation=True,
        follow_up_context=FollowUpContext(
            target_document_id="14741",
            candidate_documents=[],
            resolution_source="explicit_text",
        ),
    )

    response = await search_documents(
        request,
        search_service=search_service,
        asset_service=AssetServiceStub(None),
    )

    assert search_service.search_called is True
    assert response.generated_answer == "回退后的常规检索回答。"
    assert response.results[0].id == "22898"


@pytest.mark.asyncio
async def test_search_documents_extracts_explicit_document_id_without_follow_up_context() -> None:
    detail = make_document_detail("7873")
    follow_up_result = make_result("7873", "explicit-id-follow-up")

    class SearchServiceStub:
        def _is_document_summary_query(self, query: str) -> bool:
            return True

        def extract_explicit_document_id(self, query: str) -> str | None:
            return "7873"

        async def load_follow_up_document_result(self, follow_up_context, asset_service):
            assert follow_up_context.target_document_id == "7873"
            assert follow_up_context.resolution_source == "explicit_text"
            return detail, follow_up_result

        async def generate_document_follow_up_answer(self, query, document_detail, history=None):
            return "这是 7873 的文档摘要。", 0.08

        async def detect_intent(self, query: str) -> str:  # pragma: no cover - should not run
            raise AssertionError("detect_intent should not run when explicit document id is resolved")

    request = SearchRequest(
        query="7873的主要内容是什么？",
        use_generation=True,
    )

    response = await search_documents(
        request,
        search_service=SearchServiceStub(),
        asset_service=AssetServiceStub(detail),
    )

    assert response.generated_answer == "这是 7873 的文档摘要。"
    assert response.results[0].id == "7873"


def test_build_document_follow_up_fallback_answer_uses_document_content() -> None:
    service = SearchService.__new__(SearchService)
    detail = make_document_detail(
        "7873",
        content="本标准规定了项目总则。明确了报告编制要求。提出了建设边界约束条件。",
    )

    answer = service.build_document_follow_up_fallback_answer(
        "7873的主要内容是什么",
        detail,
    )

    assert "DB37_T 4798-2024" in answer
    assert "> " in answer
    assert "依据1" in answer
    assert "报告编制要求" in answer or "建设边界约束条件" in answer
