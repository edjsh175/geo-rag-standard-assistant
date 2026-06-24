"""Document lifecycle orchestration for upload, indexing, and audit state."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any, Protocol
from uuid import uuid4

from app.core.config import settings

logger = logging.getLogger(__name__)


class DocumentLifecycleRepository(Protocol):
    async def create_upload_record(self, **payload: Any) -> None: ...

    async def create_index_job(self, **payload: Any) -> None: ...

    async def append_event(self, **payload: Any) -> None: ...

    async def queue_reindex_job(self, doc_id: str, requested_by: str | None) -> str | None: ...


class DocumentIndexDispatcher(Protocol):
    def dispatch_index_job(self, job_id: str) -> None: ...


class CeleryDocumentIndexDispatcher:
    """Dispatch index jobs to Celery while keeping DB as the source of truth."""

    def dispatch_index_job(self, job_id: str) -> None:
        try:
            from app.worker.document_tasks import index_document_job

            index_document_job.delay(job_id)
        except Exception as exc:
            logger.warning("Document index job dispatch failed for %s: %s", job_id, exc)


class DocumentLifecycleService:
    """Coordinate persistent document lifecycle records and async indexing."""

    def __init__(
        self,
        repository: DocumentLifecycleRepository | None = None,
        dispatcher: DocumentIndexDispatcher | None = None,
    ) -> None:
        if repository is None:
            from app.services.document_repository import DocumentRepository

            repository = DocumentRepository()
        self.repository = repository
        self.dispatcher = dispatcher or CeleryDocumentIndexDispatcher()

    async def register_uploaded_document(
        self,
        *,
        document_id: str,
        filename: str,
        title: str,
        file_type: str,
        file_size: int,
        mime_type: str,
        sha256: str,
        storage_bucket: str,
        storage_key: str,
        access_url: str | None,
        metadata: dict[str, Any],
        spatial_metadata: dict[str, Any] | None,
        requested_by: str | None,
    ) -> dict[str, str]:
        version_id = str(uuid4())
        job_id = str(uuid4())
        now = datetime.utcnow()
        max_attempts = max(1, settings.DOCUMENT_INDEX_MAX_RETRIES + 1)

        await self.repository.create_upload_record(
            document_id=document_id,
            version_id=version_id,
            title=title,
            filename=filename,
            file_type=file_type,
            file_size=file_size,
            mime_type=mime_type,
            sha256=sha256,
            storage_bucket=storage_bucket,
            storage_key=storage_key,
            access_url=access_url,
            metadata=metadata,
            spatial_metadata=spatial_metadata,
            index_status="queued",
            created_by=requested_by,
            created_at=now,
            updated_at=now,
        )
        await self.repository.create_index_job(
            job_id=job_id,
            document_id=document_id,
            version_id=version_id,
            status="queued",
            attempts=0,
            max_attempts=max_attempts,
            stage="queued",
            requested_by=requested_by,
            created_at=now,
            updated_at=now,
        )
        await self.repository.append_event(
            document_id=document_id,
            version_id=version_id,
            job_id=job_id,
            event_type="uploaded",
            actor=requested_by,
            payload={"filename": filename, "file_size": file_size, "mime_type": mime_type},
            created_at=now,
        )
        self.dispatcher.dispatch_index_job(job_id)
        return {"version_id": version_id, "job_id": job_id}

    async def queue_reindex_job(self, doc_id: str, requested_by: str | None) -> str | None:
        job_id = await self.repository.queue_reindex_job(doc_id, requested_by)
        if job_id:
            self.dispatcher.dispatch_index_job(job_id)
        return job_id
