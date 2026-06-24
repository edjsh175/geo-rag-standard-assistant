from __future__ import annotations

from datetime import datetime

import pytest

from app.models.document_models import DocumentBatchRequest, DocumentUpdateRequest
from app.models.search_models import DocumentResult
from app.services.document_contract_service import DocumentContractService


def make_result(doc_id: str) -> DocumentResult:
    return DocumentResult(
        id=doc_id,
        title=f"文档 {doc_id}",
        content="摘要",
        similarity=0.9,
        metadata={},
        spatial_info=None,
        file_type="pdf",
        file_size=0,
        upload_time=datetime.now(),
    )


@pytest.mark.asyncio
async def test_filter_deleted_results_removes_soft_deleted_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    service = DocumentContractService()

    async def fake_deleted_ids(doc_ids: list[str]) -> set[str]:
        assert doc_ids == ["1", "2", "3"]
        return {"2"}

    monkeypatch.setattr(service, "get_deleted_document_ids", fake_deleted_ids)

    filtered = await service.filter_deleted_results([make_result("1"), make_result("2"), make_result("3")])

    assert [result.id for result in filtered] == ["1", "3"]


@pytest.mark.asyncio
async def test_apply_document_overrides_merges_metadata_without_losing_existing_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = DocumentContractService()

    async def fake_override(doc_id: str):
        assert doc_id == "42"
        return {
            "metadata_override": {
                "description": "人工修订说明",
                "custom_fields": {"reviewed": True},
            },
            "spatial_metadata_override": {"province": "山东省"},
            "deleted_at": None,
        }

    monkeypatch.setattr(service, "get_document_override", fake_override)

    detail = {
        "id": "42",
        "metadata": {
            "description": "原说明",
            "keywords": ["土地"],
            "custom_fields": {"standard_code": "DB37_T 4798-2024"},
        },
        "spatial_info": None,
    }

    merged = await service.apply_document_overrides("42", detail)

    assert merged["metadata"]["description"] == "人工修订说明"
    assert merged["metadata"]["keywords"] == ["土地"]
    assert merged["metadata"]["custom_fields"] == {
        "standard_code": "DB37_T 4798-2024",
        "reviewed": True,
    }
    assert merged["spatial_info"] == {"province": "山东省"}


@pytest.mark.asyncio
async def test_batch_delete_returns_per_document_results(monkeypatch: pytest.MonkeyPatch) -> None:
    service = DocumentContractService()

    async def fake_soft_delete(doc_id: str, requested_by: str) -> bool:
        assert requested_by == "admin"
        return doc_id != "missing"

    monkeypatch.setattr(service, "soft_delete_document", fake_soft_delete)

    response = await service.batch_operation(
        DocumentBatchRequest(operation="delete", document_ids=["1", "missing"]),
        requested_by="admin",
    )

    assert response.operation == "delete"
    assert response.total == 2
    assert response.success == 1
    assert response.failed == 1
    assert [item.success for item in response.results] == [True, False]


@pytest.mark.asyncio
async def test_update_document_metadata_returns_merged_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    service = DocumentContractService()

    async def fake_store_override(doc_id: str, update_request: DocumentUpdateRequest, requested_by: str) -> None:
        assert doc_id == "42"
        assert requested_by == "admin"
        assert update_request.metadata == {"description": "人工修订说明"}

    async def fake_apply(doc_id: str, detail: dict):
        assert doc_id == "42"
        updated = dict(detail)
        updated["metadata"] = {**detail["metadata"], "description": "人工修订说明"}
        return updated

    monkeypatch.setattr(service, "store_document_override", fake_store_override)
    monkeypatch.setattr(service, "apply_document_overrides", fake_apply)

    merged = await service.update_document_metadata(
        doc_id="42",
        current_detail={"id": "42", "metadata": {"description": "原说明"}},
        update_request=DocumentUpdateRequest(metadata={"description": "人工修订说明"}),
        requested_by="admin",
    )

    assert merged["metadata"]["description"] == "人工修订说明"
