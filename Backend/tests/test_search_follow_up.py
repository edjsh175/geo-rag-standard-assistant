from __future__ import annotations

from datetime import datetime

import pytest

from app.api.search_routes import search_documents
from app.models.search_models import DocumentResult, FollowUpContext, SearchRequest, SearchResponse
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
async def test_search_documents_forwards_follow_up_context_to_application_layer() -> None:
    class ApplicationServiceStub:
        def __init__(self) -> None:
            self.request = None

        async def execute(self, request, *, generation_allowed):
            self.request = request
            return SearchResponse(query=request.query)

    request = SearchRequest(
        query="第一个14741的主要内容是什么",
        use_generation=True,
        follow_up_context=FollowUpContext(
            target_document_id="14741",
            candidate_documents=[],
            resolution_source="explicit_text",
        ),
    )
    application_service = ApplicationServiceStub()

    response = await search_documents(
        request,
        application_service=application_service,
    )

    assert response.query == request.query
    assert application_service.request.follow_up_context.target_document_id == "14741"


@pytest.mark.asyncio
async def test_search_documents_does_not_resolve_missing_follow_up_target_in_route() -> None:
    class ApplicationServiceStub:
        def __init__(self) -> None:
            self.request = None

        async def execute(self, request, *, generation_allowed):
            self.request = request
            return SearchResponse(query=request.query)

    request = SearchRequest(
        query="14741的主要内容是什么",
        use_generation=True,
        follow_up_context=FollowUpContext(
            target_document_id="14741",
            candidate_documents=[],
            resolution_source="explicit_text",
        ),
    )
    application_service = ApplicationServiceStub()

    await search_documents(
        request,
        application_service=application_service,
    )

    assert application_service.request.follow_up_context.target_document_id == "14741"


@pytest.mark.asyncio
async def test_search_documents_does_not_extract_document_id_semantics_in_route() -> None:
    class ApplicationServiceStub:
        def __init__(self) -> None:
            self.request = None

        async def execute(self, request, *, generation_allowed):
            self.request = request
            return SearchResponse(query=request.query)

    request = SearchRequest(
        query="7873的主要内容是什么？",
        use_generation=True,
    )
    application_service = ApplicationServiceStub()

    await search_documents(
        request,
        application_service=application_service,
    )

    assert application_service.request.follow_up_context is None


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
