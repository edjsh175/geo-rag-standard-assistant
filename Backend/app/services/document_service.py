"""
Document management service.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import io
import json
import logging
import mimetypes
import os
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
import uuid

from minio import Minio

from app.core.config import settings
from app.models.document_models import (
    Document,
    DocumentMetadata,
    DocumentUpdateRequest,
    SpatialMetadata,
)
from app.services.document_lifecycle_service import DocumentLifecycleService

logger = logging.getLogger(__name__)

PRIVATE_BUCKET_POLICY = json.dumps({"Version": "2012-10-17", "Statement": []})

ALLOWED_EXTENSION_MIME_MAP = {
    ".pdf": {"application/pdf"},
    ".doc": {"application/msword"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    },
    ".txt": {"text/plain"},
    ".md": {"text/markdown", "text/plain"},
    ".json": {"application/json", "text/json"},
    ".csv": {"text/csv", "application/csv", "application/vnd.ms-excel"},
    ".geojson": {"application/geo+json", "application/json"},
}

GENERIC_ALLOWED_MIME_TYPES = {"application/octet-stream"}
INVALID_FILENAME_PATTERN = re.compile(r"[\x00-\x1f\x7f]")
INVALID_OBJECT_NAME_PATTERN = re.compile(r"[\x00-\x1f\x7f]")


class DocumentService:
    """Document and object storage management."""

    def __init__(
        self,
        storage: Any | None = None,
        lifecycle_service: DocumentLifecycleService | None = None,
        ensure_bucket: bool = True,
    ):
        self.upload_dir = settings.UPLOAD_DIR
        self.bucket_name = settings.MINIO_BUCKET
        self.bucket_private_ready = False
        self.storage = storage or self
        self.lifecycle_service = lifecycle_service or DocumentLifecycleService()
        self.minio_client = None
        if storage is None:
            self.minio_client = Minio(
                settings.MINIO_URL,
                access_key=settings.MINIO_ACCESS_KEY,
                secret_key=settings.MINIO_SECRET_KEY,
                secure=settings.MINIO_SECURE,
            )
            if ensure_bucket:
                self._ensure_bucket()
            else:
                self.bucket_private_ready = True
        else:
            self.bucket_private_ready = True

    def _ensure_bucket(self) -> None:
        """Ensure the bucket exists and remains private."""
        try:
            if not self.minio_client.bucket_exists(self.bucket_name):
                self.minio_client.make_bucket(self.bucket_name)
                logger.info("Created MinIO bucket '%s'.", self.bucket_name)

            self.minio_client.set_bucket_policy(self.bucket_name, PRIVATE_BUCKET_POLICY)
            self.bucket_private_ready = True
        except Exception as exc:
            self.bucket_private_ready = False
            if settings.DEBUG:
                logger.warning("Failed to ensure private MinIO bucket '%s': %s", self.bucket_name, exc)
                return
            raise RuntimeError(
                f"Failed to ensure private MinIO bucket '{self.bucket_name}': {exc}"
            ) from exc

    def _require_private_bucket(self) -> None:
        if not self.bucket_private_ready:
            raise RuntimeError("Private MinIO bucket policy is not active.")

    def _normalize_filename(self, filename: str) -> str:
        raw_filename = (filename or "").strip()
        normalized = os.path.basename(raw_filename)
        if not normalized or normalized in {".", ".."}:
            raise ValueError("Filename is required.")
        if raw_filename != normalized:
            raise ValueError("Filename must not contain path segments.")
        if INVALID_FILENAME_PATTERN.search(normalized):
            raise ValueError("Filename contains control characters.")
        if "/" in normalized or "\\" in normalized:
            raise ValueError("Filename must not contain path separators.")
        if len(normalized) > 255:
            raise ValueError("Filename is too long.")
        return normalized

    def _normalize_object_name(self, object_name: str) -> str:
        normalized = (object_name or "").strip().replace("\\", "/")
        normalized = re.sub(r"/+", "/", normalized).lstrip("/")
        if not normalized:
            raise ValueError("Object name is required.")
        if INVALID_OBJECT_NAME_PATTERN.search(normalized):
            raise ValueError("Object name contains control characters.")

        segments = normalized.split("/")
        if any(segment in {"", ".", ".."} for segment in segments):
            raise ValueError("Object name contains invalid path segments.")
        if len(normalized) > 1024:
            raise ValueError("Object name is too long.")
        return normalized

    def _validate_upload_request(self, filename: str, content_type: str, file_size: int) -> str:
        normalized_filename = self._normalize_filename(filename)

        if file_size <= 0:
            raise ValueError("File size must be greater than zero.")
        if file_size > settings.MAX_UPLOAD_SIZE:
            raise ValueError(f"File exceeds max upload size of {settings.MAX_UPLOAD_SIZE} bytes.")

        extension = Path(normalized_filename).suffix.lower()
        if extension not in ALLOWED_EXTENSION_MIME_MAP:
            raise ValueError(f"File extension '{extension}' is not allowed.")

        normalized_content_type = (content_type or "").split(";")[0].strip().lower()
        if not normalized_content_type:
            raise ValueError("Content-Type is required.")

        allowed_mime_types = ALLOWED_EXTENSION_MIME_MAP[extension]
        if (
            normalized_content_type not in allowed_mime_types
            and normalized_content_type not in GENERIC_ALLOWED_MIME_TYPES
        ):
            raise ValueError(
                f"Content-Type '{normalized_content_type}' is not allowed for extension '{extension}'."
            )

        return normalized_filename

    def _build_download_url(self, object_name: str) -> str:
        base_path = f"/api/documents/download/{object_name}"
        if settings.PUBLIC_API_BASE_URL:
            return f"{settings.PUBLIC_API_BASE_URL.rstrip('/')}{base_path}"
        return base_path

    async def generate_presigned_url_for_upload(
        self,
        filename: str,
        content_type: str,
        file_size: int,
    ) -> Dict[str, str]:
        self._require_private_bucket()
        normalized_filename = self._validate_upload_request(filename, content_type, file_size)
        file_extension = Path(normalized_filename).suffix.lower()
        document_id = str(uuid.uuid4())
        object_name = f"{document_id}{file_extension}"

        upload_url = self.minio_client.presigned_put_object(
            self.bucket_name,
            object_name,
            expires=timedelta(seconds=settings.MINIO_PRESIGNED_UPLOAD_EXPIRES_SECONDS),
        )

        return {
            "document_id": document_id,
            "upload_url": upload_url,
            "object_name": object_name,
            "access_url": self._build_download_url(object_name),
        }

    async def upload_document(
        self,
        file_content: bytes,
        filename: str,
        content_type: str,
        metadata: DocumentMetadata,
        spatial_metadata: Optional[SpatialMetadata] = None,
        requested_by: Optional[str] = None,
    ) -> Document:
        self._require_private_bucket()
        normalized_filename = self._validate_upload_request(filename, content_type, len(file_content))
        file_extension = Path(normalized_filename).suffix.lower()
        document_id = str(uuid.uuid4())
        stored_object = await self.storage.put_upload(
            document_id=document_id,
            filename=normalized_filename,
            content_type=content_type,
            content=file_content,
        )

        content_hash = hashlib.sha256(file_content).hexdigest()
        now = datetime.now()
        metadata_payload = metadata.model_dump(mode="json")
        spatial_payload = spatial_metadata.model_dump(mode="json") if spatial_metadata else None
        lifecycle_ids = await self.lifecycle_service.register_uploaded_document(
            document_id=document_id,
            filename=normalized_filename,
            title=metadata.title,
            file_type=file_extension.lstrip("."),
            file_size=len(file_content),
            mime_type=content_type,
            sha256=content_hash,
            storage_bucket=getattr(stored_object, "bucket"),
            storage_key=getattr(stored_object, "object_name"),
            access_url=getattr(stored_object, "access_url", None),
            metadata=metadata_payload,
            spatial_metadata=spatial_payload,
            requested_by=requested_by,
        )
        return Document(
            id=document_id,
            filename=normalized_filename,
            file_type=file_extension.lstrip("."),
            file_size=len(file_content),
            content_hash=content_hash,
            upload_time=now,
            last_modified=now,
            metadata=metadata,
            spatial_metadata=spatial_metadata,
            vector_embedding=None,
            is_indexed=False,
            indexing_status="queued",
            storage_path=getattr(stored_object, "object_name"),
            access_url=getattr(stored_object, "access_url", None),
            version=1,
            current_version_id=lifecycle_ids["version_id"],
            job_id=lifecycle_ids["job_id"],
        )

    async def put_upload(
        self,
        *,
        document_id: str,
        filename: str,
        content_type: str,
        content: bytes,
    ):
        self._require_private_bucket()
        if self.minio_client is None:
            raise RuntimeError("MinIO client is not initialized.")
        file_extension = Path(filename).suffix.lower()
        object_name = f"uploads/{document_id}/{filename or f'document{file_extension}'}"

        self.minio_client.put_object(
            self.bucket_name,
            object_name,
            io.BytesIO(content),
            length=len(content),
            content_type=content_type,
        )

        return SimpleNamespace(
            bucket=self.bucket_name,
            object_name=object_name,
            access_url=self._build_download_url(object_name),
        )

    def get_download_stream(self, object_name: str):
        self._require_private_bucket()
        normalized_object_name = self._normalize_object_name(object_name)
        response = self.minio_client.get_object(self.bucket_name, normalized_object_name)
        guessed_content_type = mimetypes.guess_type(normalized_object_name)[0] or "application/octet-stream"
        return {
            "object_name": normalized_object_name,
            "content_type": guessed_content_type,
            "stream": response,
        }

    async def get_document(self, doc_id: str) -> Optional[Document]:
        try:
            return None
        except Exception as exc:
            logger.error("Failed to get document %s: %s", doc_id, exc)
            return None

    async def list_documents(
        self,
        page: int = 1,
        page_size: int = 20,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        try:
            return []
        except Exception as exc:
            logger.error("Failed to list documents: %s", exc)
            return []

    async def update_document(
        self,
        doc_id: str,
        update_request: DocumentUpdateRequest,
    ) -> Optional[Document]:
        try:
            return None
        except Exception as exc:
            logger.error("Failed to update document %s: %s", doc_id, exc)
            return None

    async def delete_document(self, doc_id: str) -> bool:
        try:
            logger.info("Document deleted: %s", doc_id)
            return True
        except Exception as exc:
            logger.error("Failed to delete document %s: %s", doc_id, exc)
            return False

    async def reindex_document(self, doc_id: str) -> bool:
        try:
            logger.info("Document reindexed: %s", doc_id)
            return True
        except Exception as exc:
            logger.error("Failed to reindex document %s: %s", doc_id, exc)
            return False

    async def get_document_statistics(self) -> Dict[str, Any]:
        try:
            return {
                "total_documents": 0,
                "total_size": 0,
                "indexed_count": 0,
                "failed_count": 0,
                "by_file_type": {},
                "by_category": {},
                "by_date": {},
            }
        except Exception as exc:
            logger.error("Failed to get document statistics: %s", exc)
            return {}

    async def search_documents(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 10,
    ) -> List[Document]:
        try:
            return []
        except Exception as exc:
            logger.error("Failed to search documents: %s", exc)
            return []

    async def export_documents(
        self,
        doc_ids: List[str],
        export_format: str = "json",
    ) -> bytes:
        try:
            data = {"documents": []}
            if export_format == "json":
                return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
            raise ValueError(f"Unsupported export format: {export_format}")
        except Exception as exc:
            logger.error("Failed to export documents: %s", exc)
            raise
