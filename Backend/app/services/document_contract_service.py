"""Document contract persistence helpers."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import logging
from typing import Any, Dict, Iterable, Optional
from uuid import uuid4

from sqlalchemy import bindparam, text

from app.core.database import db_manager
from app.models.document_models import (
    DocumentBatchRequest,
    DocumentBatchResponse,
    DocumentBatchResult,
    DocumentUpdateRequest,
)
from app.models.search_models import DocumentResult

logger = logging.getLogger(__name__)


class DocumentContractService:
    """Persist document overrides and contract-level document operations."""

    async def get_deleted_document_ids(self, doc_ids: list[str]) -> set[str]:
        if not doc_ids or not db_manager.postgres_sessionmaker:
            return set()

        sql = text(
            """
            SELECT doc_id
            FROM document_overrides
            WHERE deleted_at IS NOT NULL
              AND doc_id IN :doc_ids
            """
        ).bindparams(bindparam("doc_ids", expanding=True))

        async with db_manager.get_postgres_session() as session:
            result = await session.execute(sql, {"doc_ids": tuple(doc_ids)})
            rows = result.fetchall()

        return {str(row[0]) for row in rows}

    async def filter_deleted_results(self, results: Iterable[DocumentResult]) -> list[DocumentResult]:
        result_list = list(results)
        doc_ids = [str(result.id) for result in result_list]
        deleted_ids = await self.get_deleted_document_ids(doc_ids)
        if not deleted_ids:
            return result_list
        return [result for result in result_list if str(result.id) not in deleted_ids]

    async def is_document_deleted(self, doc_id: str) -> bool:
        return doc_id in await self.get_deleted_document_ids([doc_id])

    async def get_document_override(self, doc_id: str) -> Optional[Dict[str, Any]]:
        if not db_manager.postgres_sessionmaker:
            return None

        sql = text(
            """
            SELECT metadata_override, spatial_metadata_override, deleted_at
            FROM document_overrides
            WHERE doc_id = :doc_id
            LIMIT 1
            """
        )
        async with db_manager.get_postgres_session() as session:
            result = await session.execute(sql, {"doc_id": doc_id})
            row = result.mappings().first()

        if not row:
            return None
        return {
            "metadata_override": self._coerce_json(row.get("metadata_override")) or {},
            "spatial_metadata_override": self._coerce_json(row.get("spatial_metadata_override")),
            "deleted_at": row.get("deleted_at"),
        }

    async def apply_document_overrides(self, doc_id: str, detail: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        override = await self.get_document_override(doc_id)
        if not override:
            return detail
        if override.get("deleted_at") is not None:
            return None

        merged = deepcopy(detail)
        metadata_override = override.get("metadata_override") or {}
        if metadata_override:
            merged["metadata"] = self._merge_metadata(
                dict(merged.get("metadata") or {}),
                metadata_override,
            )

        spatial_override = override.get("spatial_metadata_override")
        if spatial_override is not None:
            merged["spatial_info"] = spatial_override

        return merged

    async def store_document_override(
        self,
        doc_id: str,
        update_request: DocumentUpdateRequest,
        requested_by: str,
    ) -> None:
        if not db_manager.postgres_sessionmaker:
            raise RuntimeError("PostgreSQL connection is not initialized")

        metadata_override = json.dumps(update_request.metadata or {}, ensure_ascii=False)
        spatial_override = (
            json.dumps(update_request.spatial_metadata, ensure_ascii=False)
            if update_request.spatial_metadata is not None
            else None
        )
        sql = text(
            """
            INSERT INTO document_overrides (
                doc_id,
                metadata_override,
                spatial_metadata_override,
                updated_by,
                updated_at
            )
            VALUES (
                :doc_id,
                CAST(:metadata_override AS jsonb),
                CAST(:spatial_metadata_override AS jsonb),
                :updated_by,
                NOW()
            )
            ON CONFLICT (doc_id) DO UPDATE SET
                metadata_override = COALESCE(document_overrides.metadata_override, '{}'::jsonb)
                    || EXCLUDED.metadata_override,
                spatial_metadata_override = COALESCE(
                    EXCLUDED.spatial_metadata_override,
                    document_overrides.spatial_metadata_override
                ),
                updated_by = EXCLUDED.updated_by,
                updated_at = NOW()
            """
        )
        async with db_manager.get_postgres_session() as session:
            await session.execute(
                sql,
                {
                    "doc_id": doc_id,
                    "metadata_override": metadata_override,
                    "spatial_metadata_override": spatial_override,
                    "updated_by": requested_by,
                },
            )

    async def update_document_metadata(
        self,
        doc_id: str,
        current_detail: Dict[str, Any],
        update_request: DocumentUpdateRequest,
        requested_by: str,
    ) -> Optional[Dict[str, Any]]:
        await self.store_document_override(doc_id, update_request, requested_by)
        return await self.apply_document_overrides(doc_id, current_detail)

    async def soft_delete_document(self, doc_id: str, requested_by: str) -> bool:
        if not db_manager.postgres_sessionmaker:
            raise RuntimeError("PostgreSQL connection is not initialized")

        sql = text(
            """
            INSERT INTO document_overrides (
                doc_id,
                metadata_override,
                deleted_at,
                deleted_by,
                updated_by,
                updated_at
            )
            VALUES (:doc_id, '{}'::jsonb, NOW(), :deleted_by, :deleted_by, NOW())
            ON CONFLICT (doc_id) DO UPDATE SET
                deleted_at = COALESCE(document_overrides.deleted_at, NOW()),
                deleted_by = EXCLUDED.deleted_by,
                updated_by = EXCLUDED.updated_by,
                updated_at = NOW()
            """
        )
        async with db_manager.get_postgres_session() as session:
            await session.execute(sql, {"doc_id": doc_id, "deleted_by": requested_by})
        return True

    async def queue_reindex_job(self, doc_id: str, requested_by: str) -> str:
        if not db_manager.postgres_sessionmaker:
            raise RuntimeError("PostgreSQL connection is not initialized")

        job_id = str(uuid4())
        sql = text(
            """
            INSERT INTO document_reindex_jobs (id, doc_id, status, requested_by, created_at)
            VALUES (CAST(:job_id AS uuid), :doc_id, 'queued', :requested_by, NOW())
            """
        )
        async with db_manager.get_postgres_session() as session:
            await session.execute(
                sql,
                {"job_id": job_id, "doc_id": doc_id, "requested_by": requested_by},
            )
        return job_id

    async def batch_operation(
        self,
        request: DocumentBatchRequest,
        requested_by: str,
    ) -> DocumentBatchResponse:
        results: list[DocumentBatchResult] = []

        for doc_id in request.document_ids:
            try:
                if request.operation == "delete":
                    ok = await self.soft_delete_document(doc_id, requested_by)
                    results.append(
                        DocumentBatchResult(
                            document_id=doc_id,
                            success=ok,
                            status="deleted" if ok else "failed",
                            message="Document soft-deleted." if ok else "Document delete failed.",
                        )
                    )
                else:
                    job_id = await self.queue_reindex_job(doc_id, requested_by)
                    results.append(
                        DocumentBatchResult(
                            document_id=doc_id,
                            success=True,
                            status="queued",
                            message="Document reindex queued.",
                            job_id=job_id,
                        )
                    )
            except Exception as exc:  # pragma: no cover - exercised through route-level failures
                logger.error("Batch %s failed for document %s: %s", request.operation, doc_id, exc)
                results.append(
                    DocumentBatchResult(
                        document_id=doc_id,
                        success=False,
                        status="failed",
                        message=str(exc),
                    )
                )

        success_count = sum(1 for item in results if item.success)
        return DocumentBatchResponse(
            operation=request.operation,
            total=len(results),
            success=success_count,
            failed=len(results) - success_count,
            results=results,
        )

    @staticmethod
    def _merge_metadata(current: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(current)
        for key, value in patch.items():
            if key == "custom_fields" and isinstance(value, dict):
                existing = merged.get("custom_fields")
                merged["custom_fields"] = {
                    **(existing if isinstance(existing, dict) else {}),
                    **value,
                }
            else:
                merged[key] = value
        return merged

    @staticmethod
    def _coerce_json(value: Any) -> Any:
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return None
        return value
