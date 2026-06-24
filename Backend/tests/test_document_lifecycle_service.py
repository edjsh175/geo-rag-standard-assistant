from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pytest

from app.models.document_models import DocumentMetadata
from app.services.document_lifecycle_service import DocumentLifecycleService
from app.services.document_service import DocumentService


@dataclass
class StoredObject:
    bucket: str
    object_name: str
    access_url: str


class FakeStorage:
    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []

    async def put_upload(self, document_id: str, filename: str, content_type: str, content: bytes) -> StoredObject:
        self.saved.append(
            {
                "document_id": document_id,
                "filename": filename,
                "content_type": content_type,
                "content": content,
            }
        )
        return StoredObject(
            bucket="geoai-assets",
            object_name=f"uploads/{document_id}/{filename}",
            access_url=f"/api/documents/{document_id}/download",
        )


class FakeRepository:
    def __init__(self) -> None:
        self.upload_record: dict[str, Any] | None = None
        self.job_record: dict[str, Any] | None = None
        self.events: list[dict[str, Any]] = []

    async def create_upload_record(self, **payload: Any) -> None:
        self.upload_record = payload

    async def create_index_job(self, **payload: Any) -> None:
        self.job_record = payload

    async def append_event(self, **payload: Any) -> None:
        self.events.append(payload)


class FakeDispatcher:
    def __init__(self) -> None:
        self.dispatched: list[str] = []

    def dispatch_index_job(self, job_id: str) -> None:
        self.dispatched.append(job_id)


@pytest.mark.asyncio
async def test_document_upload_persists_version_job_and_dispatches_indexing() -> None:
    storage = FakeStorage()
    repository = FakeRepository()
    dispatcher = FakeDispatcher()
    lifecycle = DocumentLifecycleService(repository=repository, dispatcher=dispatcher)
    service = DocumentService(storage=storage, lifecycle_service=lifecycle, ensure_bucket=False)

    document = await service.upload_document(
        file_content="# 规划文本\n\n需要进入检索。".encode("utf-8"),
        filename="planning.md",
        content_type="text/markdown",
        metadata=DocumentMetadata(title="规划文本", source="upload", category="规划"),
        requested_by="admin",
    )

    assert repository.upload_record is not None
    assert repository.upload_record["document_id"] == document.id
    assert repository.upload_record["version_id"] == document.current_version_id
    assert repository.upload_record["sha256"]
    assert repository.upload_record["storage_bucket"] == "geoai-assets"
    assert repository.upload_record["storage_key"].endswith("/planning.md")
    assert repository.upload_record["index_status"] == "queued"
    assert repository.upload_record["metadata"]["title"] == "规划文本"

    assert repository.job_record is not None
    assert repository.job_record["document_id"] == document.id
    assert repository.job_record["version_id"] == document.current_version_id
    assert repository.job_record["status"] == "queued"
    assert dispatcher.dispatched == [repository.job_record["job_id"]]
    assert any(event["event_type"] == "uploaded" for event in repository.events)
    assert document.indexing_status == "queued"
    assert document.version == 1
    assert datetime.fromisoformat(document.upload_time.isoformat())
