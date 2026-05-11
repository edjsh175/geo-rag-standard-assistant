"""
Document asset lookup and MinIO mapping helpers.
"""

from __future__ import annotations

from datetime import datetime
import logging
import mimetypes
from pathlib import Path
import re
from typing import Any, Dict, Optional, Sequence

from sqlalchemy import text

from app.core.config import settings
from app.core.database import db_manager
from app.models.search_models import DocumentResult

logger = logging.getLogger(__name__)

GEOAI_METADATA_TABLE = "geoai_metadata"

BASE_METADATA_COLUMNS = (
    "standard_id",
    "standard_code",
    "draft_unit",
    "drafter",
    "chinese_name",
    "english_name",
    "release_date",
    "implement_date",
    "release_unit",
    "charge_unit",
    "replace_standard",
    "standard_status",
    "application_scope",
    "reference_standard",
    "keyword",
    "pdf_path",
    "root_path",
    "relative_path",
    "ps",
    "document_type",
)

ASSET_METADATA_COLUMNS = (
    "minio_object_name",
    "original_filename",
    "mime_type",
    "file_size_bytes",
    "asset_status",
    "asset_error",
    "asset_imported_at",
)

ASSET_COLUMN_DEFINITIONS = {
    "minio_object_name": "VARCHAR(1024) NULL",
    "original_filename": "VARCHAR(512) NULL",
    "mime_type": "VARCHAR(255) NULL",
    "file_size_bytes": "BIGINT NULL",
    "asset_status": "VARCHAR(32) NULL",
    "asset_error": "TEXT NULL",
    "asset_imported_at": "DATETIME NULL",
}

INVALID_OBJECT_KEY_CHARS = re.compile(r"[^A-Za-z0-9._/-]+")
STANDARD_CODE_NORMALIZER = re.compile(r"[^0-9A-Za-z]+")


class DocumentAssetService:
    """Lookup standard assets and build download metadata."""

    def __init__(self) -> None:
        self._metadata_columns: Optional[set[str]] = None

    def build_download_url(self, doc_id: str) -> str:
        base_path = f"/api/documents/{doc_id}/download"
        if settings.PUBLIC_API_BASE_URL:
            return f"{settings.PUBLIC_API_BASE_URL.rstrip('/')}{base_path}"
        return base_path

    async def enrich_search_results(
        self,
        results: Sequence[DocumentResult],
    ) -> list[DocumentResult]:
        if not results or not db_manager.mysql_sessionmaker:
            return list(results)

        standard_codes = sorted(
            {
                str(result.metadata.get("standard_code", "")).strip()
                for result in results
                if result.metadata.get("standard_code")
            }
        )
        if not standard_codes:
            return list(results)

        metadata_by_code = await self.get_metadata_rows_by_standard_codes(standard_codes)
        for result in results:
            standard_code = str(result.metadata.get("standard_code", "")).strip()
            metadata_row = metadata_by_code.get(standard_code)
            if metadata_row:
                self.apply_metadata_to_result(result, metadata_row)

        return list(results)

    async def get_document_record(self, doc_id: str) -> Optional[Dict[str, Any]]:
        if not db_manager.postgres_sessionmaker:
            return None

        query_doc_id: Any = int(doc_id) if doc_id.isdigit() else doc_id
        sql = text(
            """
            SELECT
                id::text AS id,
                standard_code,
                document_name,
                content,
                keyword,
                chinese_name,
                english_name,
                release_date,
                implement_date,
                standard_status,
                release_unit,
                charge_unit,
                draft_unit,
                replace_standard,
                application_scope
            FROM policy_chunks
            WHERE id = :doc_id
            LIMIT 1
            """
        )

        async with db_manager.get_postgres_session() as session:
            result = await session.execute(sql, {"doc_id": query_doc_id})
            row = result.mappings().first()

        return dict(row) if row else None

    async def get_document_detail_payload(self, doc_id: str) -> Optional[Dict[str, Any]]:
        record = await self.get_document_record(doc_id)
        if not record:
            return None

        metadata_row = None
        standard_code = str(record.get("standard_code", "")).strip()
        if standard_code:
            metadata_row = await self.get_metadata_row_by_standard_code(standard_code)

        return self._build_document_detail_payload(record, metadata_row)

    async def get_download_target(self, doc_id: str) -> Optional[Dict[str, Any]]:
        record = await self.get_document_record(doc_id)
        if not record:
            return None

        standard_code = str(record.get("standard_code", "")).strip()
        if not standard_code:
            return None

        metadata_row = await self.get_metadata_row_by_standard_code(standard_code)
        if not metadata_row:
            return None

        object_name = (metadata_row.get("minio_object_name") or "").strip()
        asset_status = (metadata_row.get("asset_status") or "").strip().lower()
        if not object_name or asset_status != "ready":
            return None

        filename = (
            metadata_row.get("original_filename")
            or Path(metadata_row.get("relative_path") or "").name
            or Path(metadata_row.get("pdf_path") or "").name
            or record.get("document_name")
            or f"{standard_code}.pdf"
        )
        content_type = metadata_row.get("mime_type") or mimetypes.guess_type(filename)[0] or "application/octet-stream"

        return {
            "document_id": str(record["id"]),
            "standard_code": standard_code,
            "object_name": object_name,
            "filename": filename,
            "content_type": content_type,
        }

    async def get_metadata_row_by_standard_code(self, standard_code: str) -> Optional[Dict[str, Any]]:
        rows = await self.get_metadata_rows_by_standard_codes([standard_code])
        return rows.get(standard_code)

    async def get_metadata_rows_by_standard_codes(
        self,
        standard_codes: Sequence[str],
    ) -> Dict[str, Dict[str, Any]]:
        if not db_manager.mysql_sessionmaker:
            return {}

        clean_codes = [code.strip() for code in standard_codes if code and code.strip()]
        if not clean_codes:
            return {}
        metadata_rows = await self.list_metadata_rows()
        exact_rows = {
            str(row.get("standard_code", "")).strip(): row
            for row in metadata_rows
            if row.get("standard_code")
        }
        normalized_rows = {
            self.normalize_standard_code(str(row.get("standard_code", ""))): row
            for row in metadata_rows
            if row.get("standard_code")
        }

        matched_rows: Dict[str, Dict[str, Any]] = {}
        for code in clean_codes:
            exact_match = exact_rows.get(code)
            if exact_match:
                matched_rows[code] = exact_match
                continue

            normalized_code = self.normalize_standard_code(code)
            if normalized_code and normalized_code in normalized_rows:
                matched_rows[code] = normalized_rows[normalized_code]

        return matched_rows

    async def list_metadata_rows(self) -> list[Dict[str, Any]]:
        if not db_manager.mysql_sessionmaker:
            return []

        available_columns = await self.get_metadata_columns()
        selected_columns = [column for column in (*BASE_METADATA_COLUMNS, *ASSET_METADATA_COLUMNS) if column in available_columns]
        sql = text(
            f"""
            SELECT {", ".join(selected_columns)}
            FROM {GEOAI_METADATA_TABLE}
            ORDER BY standard_id ASC
            """
        )

        async with db_manager.get_mysql_session() as session:
            result = await session.execute(sql)
            rows = result.mappings().all()

        return [self.normalize_metadata_row(dict(row)) for row in rows]

    async def update_asset_metadata(
        self,
        standard_id: int,
        updates: Dict[str, Any],
    ) -> None:
        if not db_manager.mysql_sessionmaker or not updates:
            return

        assignments: list[str] = []
        params: Dict[str, Any] = {"standard_id": standard_id}
        for key, value in updates.items():
            assignments.append(f"{key} = :{key}")
            params[key] = value

        sql = text(
            f"""
            UPDATE {GEOAI_METADATA_TABLE}
            SET {", ".join(assignments)}
            WHERE standard_id = :standard_id
            """
        )

        async with db_manager.get_mysql_session() as session:
            await session.execute(sql, params)

    async def ensure_asset_columns(self) -> None:
        available_columns = await self.get_metadata_columns(refresh=True)
        missing_columns = [
            column
            for column in ASSET_METADATA_COLUMNS
            if column not in available_columns
        ]
        if not missing_columns:
            return

        clauses = [
            f"ADD COLUMN {column} {ASSET_COLUMN_DEFINITIONS[column]}"
            for column in missing_columns
        ]
        sql = text(
            f"""
            ALTER TABLE {GEOAI_METADATA_TABLE}
            {", ".join(clauses)}
            """
        )
        async with db_manager.get_mysql_session() as session:
            await session.execute(sql)

        self._metadata_columns = None
        await self.get_metadata_columns(refresh=True)

    async def get_metadata_columns(self, refresh: bool = False) -> set[str]:
        if self._metadata_columns is not None and not refresh:
            return self._metadata_columns

        if not db_manager.mysql_sessionmaker:
            self._metadata_columns = set()
            return self._metadata_columns

        sql = text(
            """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = :table_name
            """
        )
        async with db_manager.get_mysql_session() as session:
            result = await session.execute(sql, {"table_name": GEOAI_METADATA_TABLE})
            rows = result.fetchall()

        self._metadata_columns = {str(row[0]) for row in rows}
        return self._metadata_columns

    @staticmethod
    def normalize_metadata_row(row: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(row)
        for field_name in ("standard_code", "relative_path", "pdf_path", "root_path", "minio_object_name", "original_filename", "mime_type", "asset_status"):
            value = normalized.get(field_name)
            normalized[field_name] = value.strip() if isinstance(value, str) else value

        file_size = normalized.get("file_size_bytes")
        if file_size is not None:
            try:
                normalized["file_size_bytes"] = int(file_size)
            except (TypeError, ValueError):
                normalized["file_size_bytes"] = None

        return normalized

    @classmethod
    def normalize_relative_path(cls, value: Optional[str]) -> Optional[str]:
        if not value:
            return None

        normalized = value.replace("\\", "/").strip().lstrip("/")
        normalized = re.sub(r"/+", "/", normalized)
        if not normalized:
            return None

        segments = [segment for segment in normalized.split("/") if segment not in {"", ".", ".."}]
        if not segments:
            return None
        return "/".join(segments)

    @classmethod
    def build_object_name(
        cls,
        metadata_row: Dict[str, Any],
        bucket_prefix: str = "standards",
    ) -> str:
        relative_path = cls.normalize_relative_path(metadata_row.get("relative_path"))
        prefix = bucket_prefix.strip("/ ")
        if relative_path:
            return f"{prefix}/{relative_path}" if prefix else relative_path

        filename = (
            metadata_row.get("original_filename")
            or Path(metadata_row.get("pdf_path") or "").name
            or f"{metadata_row.get('standard_code', 'unknown')}.pdf"
        )
        sanitized_code = cls.sanitize_object_component(str(metadata_row.get("standard_code", "unknown")))
        sanitized_name = cls.sanitize_object_component(filename)
        if prefix:
            return f"{prefix}/by-code/{sanitized_code}/{sanitized_name}"
        return f"by-code/{sanitized_code}/{sanitized_name}"

    @classmethod
    def sanitize_object_component(cls, value: str) -> str:
        sanitized = INVALID_OBJECT_KEY_CHARS.sub("_", value.strip().replace("\\", "/"))
        sanitized = sanitized.strip("./_")
        return sanitized or "unknown"

    @staticmethod
    def normalize_standard_code(value: Optional[str]) -> str:
        return STANDARD_CODE_NORMALIZER.sub("", (value or "").strip()).lower()

    @classmethod
    def resolve_local_source_path(
        cls,
        metadata_row: Dict[str, Any],
        source_root: Path,
    ) -> Optional[Path]:
        source_root = source_root.resolve()

        relative_path = cls.normalize_relative_path(metadata_row.get("relative_path"))
        if relative_path:
            candidate = (source_root / Path(*relative_path.split("/"))).resolve()
            if candidate.exists():
                return candidate

        pdf_path = metadata_row.get("pdf_path")
        if isinstance(pdf_path, str) and pdf_path.strip():
            raw_path = Path(pdf_path.strip())
            if raw_path.exists():
                return raw_path

            lowered = pdf_path.replace("\\", "/")
            marker = "/pdf/"
            if marker in lowered:
                suffix = lowered.split(marker, 1)[1]
                fallback = (source_root / "pdf" / Path(*suffix.split("/"))).resolve()
                if fallback.exists():
                    return fallback

        return None

    @staticmethod
    def detect_content_type(path: Path) -> str:
        return mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    def apply_metadata_to_result(
        self,
        result: DocumentResult,
        metadata_row: Dict[str, Any],
    ) -> None:
        download_available = bool(
            metadata_row.get("minio_object_name")
            and str(metadata_row.get("asset_status") or "").lower() == "ready"
        )
        download_url = self.build_download_url(str(result.id)) if download_available else None
        filename = (
            metadata_row.get("original_filename")
            or Path(metadata_row.get("relative_path") or "").name
            or Path(metadata_row.get("pdf_path") or "").name
            or result.title
        )

        result.file_type = Path(filename).suffix.lstrip(".").lower() or result.file_type or "pdf"
        if metadata_row.get("file_size_bytes"):
            result.file_size = int(metadata_row["file_size_bytes"])
        result.source_url = download_url
        result.download_available = download_available
        result.download_url = download_url
        result.metadata.update(
            {
                "document_type": metadata_row.get("document_type"),
                "release_date": metadata_row.get("release_date"),
                "implement_date": metadata_row.get("implement_date"),
                "draft_unit": metadata_row.get("draft_unit"),
                "release_unit": metadata_row.get("release_unit"),
                "charge_unit": metadata_row.get("charge_unit"),
                "replace_standard": metadata_row.get("replace_standard"),
                "application_scope": metadata_row.get("application_scope"),
                "original_filename": filename,
                "asset_status": metadata_row.get("asset_status"),
                "relative_path": metadata_row.get("relative_path"),
            }
        )

    def _build_document_detail_payload(
        self,
        record: Dict[str, Any],
        metadata_row: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        detail_metadata = {
            "author": metadata_row.get("drafter") if metadata_row else None,
            "description": record.get("application_scope") or record.get("content"),
            "keywords": [record["keyword"]] if record.get("keyword") else [],
            "publish_date": metadata_row.get("release_date") if metadata_row else record.get("release_date"),
            "source": metadata_row.get("document_type") if metadata_row else None,
            "category": metadata_row.get("document_type") if metadata_row else None,
            "tags": [],
            "custom_fields": {
                "standard_code": record.get("standard_code"),
                "reference_standard": metadata_row.get("reference_standard") if metadata_row else None,
                "replace_standard": metadata_row.get("replace_standard") if metadata_row else record.get("replace_standard"),
                "relative_path": metadata_row.get("relative_path") if metadata_row else None,
            },
        }

        original_filename = (
            (metadata_row or {}).get("original_filename")
            or Path((metadata_row or {}).get("relative_path") or "").name
            or Path((metadata_row or {}).get("pdf_path") or "").name
            or record.get("document_name")
        )
        file_type = Path(original_filename).suffix.lstrip(".").lower() or "pdf"
        file_size = int((metadata_row or {}).get("file_size_bytes") or 0)
        upload_time = (
            (metadata_row or {}).get("asset_imported_at")
            or (metadata_row or {}).get("release_date")
            or datetime.utcnow()
        )

        download_available = bool(
            metadata_row
            and metadata_row.get("minio_object_name")
            and str(metadata_row.get("asset_status") or "").lower() == "ready"
        )

        return {
            "id": str(record["id"]),
            "title": record.get("document_name") or record.get("chinese_name") or original_filename,
            "content": record.get("content") or "",
            "metadata": detail_metadata,
            "spatial_info": None,
            "file_info": {
                "type": file_type,
                "size": file_size,
                "upload_time": upload_time,
                "filename": original_filename,
                "mime_type": (metadata_row or {}).get("mime_type") or mimetypes.guess_type(original_filename)[0] or "application/octet-stream",
            },
            "standard_info": {
                "code": record.get("standard_code"),
                "release_date": (metadata_row or {}).get("release_date") or record.get("release_date"),
                "implement_date": (metadata_row or {}).get("implement_date") or record.get("implement_date"),
                "draft_unit": (metadata_row or {}).get("draft_unit") or record.get("draft_unit"),
                "keyword": (metadata_row or {}).get("keyword") or record.get("keyword"),
                "status": (metadata_row or {}).get("standard_status") or record.get("standard_status"),
            },
            "download_available": download_available,
            "download_url": self.build_download_url(str(record["id"])) if download_available else None,
        }
