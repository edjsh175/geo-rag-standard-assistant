"""PostgreSQL persistence for uploaded document lifecycle state."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from app.core.config import settings
from app.core.database import db_manager


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


class DocumentRepository:
    """Persist uploaded documents, versions, chunks, jobs, and events."""

    async def create_upload_record(self, **payload: Any) -> None:
        sql_document = text(
            """
            INSERT INTO documents (
                id, title, filename, file_type, file_size, mime_type, sha256,
                metadata, spatial_metadata, index_status, current_version_id,
                created_by, created_at, updated_at
            )
            VALUES (
                CAST(:document_id AS uuid), :title, :filename, :file_type, :file_size,
                :mime_type, :sha256, CAST(:metadata AS jsonb),
                CAST(:spatial_metadata AS jsonb), :index_status, CAST(:version_id AS uuid),
                :created_by, :created_at, :updated_at
            )
            """
        )
        sql_version = text(
            """
            INSERT INTO document_versions (
                id, document_id, version_number, filename, file_type, file_size,
                mime_type, sha256, storage_bucket, storage_key, access_url,
                created_by, created_at
            )
            VALUES (
                CAST(:version_id AS uuid), CAST(:document_id AS uuid), 1, :filename,
                :file_type, :file_size, :mime_type, :sha256, :storage_bucket,
                :storage_key, :access_url, :created_by, :created_at
            )
            """
        )
        params = {
            **payload,
            "metadata": _json(payload.get("metadata")),
            "spatial_metadata": _json(payload.get("spatial_metadata")) if payload.get("spatial_metadata") is not None else None,
        }
        async with db_manager.get_postgres_session() as session:
            await session.execute(sql_document, params)
            await session.execute(sql_version, params)

    async def create_index_job(self, **payload: Any) -> None:
        sql = text(
            """
            INSERT INTO index_jobs (
                id, document_id, version_id, status, attempts, max_attempts,
                stage, requested_by, created_at, updated_at
            )
            VALUES (
                CAST(:job_id AS uuid), CAST(:document_id AS uuid), CAST(:version_id AS uuid),
                :status, :attempts, :max_attempts, :stage, :requested_by,
                :created_at, :updated_at
            )
            """
        )
        async with db_manager.get_postgres_session() as session:
            await session.execute(sql, payload)

    async def append_event(self, **payload: Any) -> None:
        sql = text(
            """
            INSERT INTO document_events (
                document_id, version_id, job_id, event_type, actor, payload, created_at
            )
            VALUES (
                CAST(:document_id AS uuid),
                CAST(:version_id AS uuid),
                CAST(:job_id AS uuid),
                :event_type,
                :actor,
                CAST(:payload AS jsonb),
                :created_at
            )
            """
        )
        params = {**payload, "payload": _json(payload.get("payload"))}
        async with db_manager.get_postgres_session() as session:
            await session.execute(sql, params)

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        sql = text(
            """
            SELECT
                id::text AS job_id,
                document_id::text AS document_id,
                version_id::text AS version_id,
                status,
                attempts,
                max_attempts,
                stage,
                error,
                created_at,
                updated_at,
                started_at,
                finished_at
            FROM index_jobs
            WHERE id = CAST(:job_id AS uuid)
            LIMIT 1
            """
        )
        async with db_manager.get_postgres_session() as session:
            result = await session.execute(sql, {"job_id": job_id})
            row = result.mappings().first()
        return dict(row) if row else None

    async def list_documents(
        self,
        *,
        page: int,
        page_size: int,
        file_type: str | None = None,
    ) -> dict[str, Any]:
        offset = (page - 1) * page_size
        conditions = ["d.deleted_at IS NULL"]
        params: dict[str, Any] = {"limit": page_size, "offset": offset}
        if file_type:
            conditions.append("d.file_type = :file_type")
            params["file_type"] = file_type.lower().lstrip(".")
        where_clause = " AND ".join(conditions)

        count_sql = text(f"SELECT COUNT(*) FROM documents d WHERE {where_clause}")
        list_sql = text(
            f"""
            SELECT
                d.id::text AS id,
                d.title,
                d.filename,
                d.file_type,
                d.file_size,
                d.mime_type,
                d.sha256,
                d.index_status,
                d.last_error,
                d.metadata,
                d.created_at,
                d.updated_at,
                v.access_url AS download_url,
                COUNT(c.id)::int AS chunk_count
            FROM documents d
            LEFT JOIN document_versions v ON v.id = d.current_version_id
            LEFT JOIN document_chunks c ON c.document_id = d.id
            WHERE {where_clause}
            GROUP BY d.id, v.access_url
            ORDER BY d.updated_at DESC, d.created_at DESC
            LIMIT :limit OFFSET :offset
            """
        )
        async with db_manager.get_postgres_session() as session:
            total_result = await session.execute(count_sql, params)
            total = int(total_result.scalar_one())
            result = await session.execute(list_sql, params)
            rows = [dict(row) for row in result.mappings().all()]
        return {"total": total, "documents": rows}

    async def get_uploaded_document_detail(self, doc_id: str) -> dict[str, Any] | None:
        sql = text(
            """
            SELECT
                d.id::text AS id,
                d.title,
                d.filename,
                d.file_type,
                d.file_size,
                d.mime_type,
                d.metadata,
                d.spatial_metadata,
                d.index_status,
                d.created_at,
                d.updated_at,
                d.last_error,
                v.access_url AS download_url,
                COALESCE(
                    (
                        SELECT string_agg(content, E'\n\n' ORDER BY chunk_index)
                        FROM (
                            SELECT content, chunk_index
                            FROM document_chunks
                            WHERE document_id = d.id
                            ORDER BY chunk_index
                            LIMIT 3
                        ) preview
                    ),
                    ''
                ) AS content_preview,
                COUNT(c.id)::int AS chunk_count
            FROM documents d
            LEFT JOIN document_versions v ON v.id = d.current_version_id
            LEFT JOIN document_chunks c ON c.document_id = d.id
            WHERE d.id = CAST(:doc_id AS uuid)
              AND d.deleted_at IS NULL
            GROUP BY d.id, v.access_url
            LIMIT 1
            """
        )
        async with db_manager.get_postgres_session() as session:
            result = await session.execute(sql, {"doc_id": doc_id})
            row = result.mappings().first()
        return dict(row) if row else None

    async def get_download_target(self, doc_id: str) -> dict[str, Any] | None:
        sql = text(
            """
            SELECT
                d.id::text AS document_id,
                v.storage_bucket,
                v.storage_key AS object_name,
                v.filename,
                v.mime_type AS content_type
            FROM documents d
            JOIN document_versions v ON v.id = d.current_version_id
            WHERE d.id = CAST(:doc_id AS uuid)
              AND d.deleted_at IS NULL
            LIMIT 1
            """
        )
        async with db_manager.get_postgres_session() as session:
            result = await session.execute(sql, {"doc_id": doc_id})
            row = result.mappings().first()
        return dict(row) if row else None

    async def get_indexing_payload(self, job_id: str) -> dict[str, Any] | None:
        sql = text(
            """
            SELECT
                j.id::text AS job_id,
                j.document_id::text AS document_id,
                j.version_id::text AS version_id,
                j.attempts,
                j.max_attempts,
                d.title,
                d.metadata,
                d.spatial_metadata,
                d.deleted_at,
                v.filename,
                v.file_type,
                v.mime_type,
                v.storage_bucket,
                v.storage_key
            FROM index_jobs j
            JOIN documents d ON d.id = j.document_id
            JOIN document_versions v ON v.id = j.version_id
            WHERE j.id = CAST(:job_id AS uuid)
            LIMIT 1
            """
        )
        async with db_manager.get_postgres_session() as session:
            result = await session.execute(sql, {"job_id": job_id})
            row = result.mappings().first()
        return dict(row) if row else None

    async def mark_job_running(self, job_id: str, stage: str) -> None:
        await self._update_job_and_document(job_id, job_status="running", doc_status=stage, stage=stage, started=True)

    async def update_job_stage(self, job_id: str, stage: str) -> None:
        await self._update_job_and_document(job_id, job_status="running", doc_status=stage, stage=stage)

    async def replace_chunks(
        self,
        *,
        document_id: str,
        version_id: str,
        chunks: list[dict[str, Any]],
    ) -> None:
        delete_sql = text("DELETE FROM document_chunks WHERE document_id = CAST(:document_id AS uuid)")
        insert_sql = text(
            """
            INSERT INTO document_chunks (
                id, document_id, version_id, chunk_index, header_path,
                page_number, content, metadata, embedding, created_at
            )
            VALUES (
                CAST(:id AS uuid),
                CAST(:document_id AS uuid),
                CAST(:version_id AS uuid),
                :chunk_index,
                :header_path,
                :page_number,
                :content,
                CAST(:metadata AS jsonb),
                CAST(:embedding AS vector),
                :created_at
            )
            """
        )
        now = datetime.utcnow()
        async with db_manager.get_postgres_session() as session:
            await session.execute(delete_sql, {"document_id": document_id})
            for chunk in chunks:
                embedding = chunk.get("embedding")
                await session.execute(
                    insert_sql,
                    {
                        "id": str(uuid4()),
                        "document_id": document_id,
                        "version_id": version_id,
                        "chunk_index": chunk["chunk_index"],
                        "header_path": chunk.get("header_path"),
                        "page_number": chunk.get("page_number"),
                        "content": chunk["content"],
                        "metadata": _json(chunk.get("metadata")),
                        "embedding": str(embedding) if embedding is not None else None,
                        "created_at": now,
                    },
                )

    async def mark_job_succeeded(self, job_id: str) -> None:
        await self._update_job_and_document(
            job_id,
            job_status="succeeded",
            doc_status="indexed",
            stage="indexed",
            finished=True,
            clear_error=True,
        )

    async def mark_job_failed(self, job_id: str, error: str, retrying: bool = False) -> None:
        job_status = "retrying" if retrying else "failed"
        doc_status = "queued" if retrying else "failed"
        await self._update_job_and_document(
            job_id,
            job_status=job_status,
            doc_status=doc_status,
            stage=job_status,
            error=error[:4000],
            finished=not retrying,
            increment_attempts=True,
        )

    async def update_metadata(self, doc_id: str, metadata_patch: dict[str, Any]) -> bool:
        sql = text(
            """
            UPDATE documents
            SET metadata = COALESCE(metadata, '{}'::jsonb) || CAST(:metadata_patch AS jsonb),
                updated_at = NOW()
            WHERE id = CAST(:doc_id AS uuid)
              AND deleted_at IS NULL
            """
        )
        async with db_manager.get_postgres_session() as session:
            result = await session.execute(sql, {"doc_id": doc_id, "metadata_patch": _json(metadata_patch)})
        return bool(result.rowcount)

    async def queue_reindex_job(self, doc_id: str, requested_by: str | None) -> str | None:
        detail = await self.get_uploaded_document_detail(doc_id)
        if not detail:
            return None

        version_sql = text("SELECT current_version_id::text FROM documents WHERE id = CAST(:doc_id AS uuid)")
        async with db_manager.get_postgres_session() as session:
            result = await session.execute(version_sql, {"doc_id": doc_id})
            version_id = result.scalar_one_or_none()
        if not version_id:
            return None

        job_id = str(uuid4())
        now = datetime.utcnow()
        await self.create_index_job(
            job_id=job_id,
            document_id=doc_id,
            version_id=version_id,
            status="queued",
            attempts=0,
            max_attempts=max(1, settings.DOCUMENT_INDEX_MAX_RETRIES + 1),
            stage="queued",
            requested_by=requested_by,
            created_at=now,
            updated_at=now,
        )
        await self.append_event(
            document_id=doc_id,
            version_id=version_id,
            job_id=job_id,
            event_type="reindex_queued",
            actor=requested_by,
            payload={},
            created_at=now,
        )
        return job_id

    async def soft_delete(self, doc_id: str, requested_by: str | None) -> bool:
        sql = text(
            """
            UPDATE documents
            SET index_status = 'deleted',
                deleted_at = COALESCE(deleted_at, NOW()),
                deleted_by = :deleted_by,
                updated_at = NOW()
            WHERE id = CAST(:doc_id AS uuid)
              AND deleted_at IS NULL
            """
        )
        async with db_manager.get_postgres_session() as session:
            result = await session.execute(sql, {"doc_id": doc_id, "deleted_by": requested_by})
        if result.rowcount:
            await self.append_event(
                document_id=doc_id,
                version_id=None,
                job_id=None,
                event_type="deleted",
                actor=requested_by,
                payload={},
                created_at=datetime.utcnow(),
            )
        return bool(result.rowcount)

    async def statistics(self) -> dict[str, Any]:
        sql = text(
            """
            SELECT
                COUNT(*)::int AS total_documents,
                COALESCE(SUM(file_size), 0)::bigint AS total_size,
                COUNT(*) FILTER (WHERE index_status = 'indexed')::int AS indexed_count,
                COUNT(*) FILTER (WHERE index_status = 'failed')::int AS failed_count,
                COALESCE(jsonb_object_agg(file_type, type_count), '{}'::jsonb) AS by_file_type
            FROM (
                SELECT
                    file_type,
                    index_status,
                    file_size,
                    COUNT(*) OVER (PARTITION BY file_type) AS type_count
                FROM documents
                WHERE deleted_at IS NULL
            ) docs
            """
        )
        async with db_manager.get_postgres_session() as session:
            result = await session.execute(sql)
            row = result.mappings().first()
        if not row:
            return {}
        payload = dict(row)
        payload["by_category"] = {}
        payload["by_date"] = {}
        return payload

    async def _update_job_and_document(
        self,
        job_id: str,
        *,
        job_status: str,
        doc_status: str,
        stage: str,
        error: str | None = None,
        started: bool = False,
        finished: bool = False,
        increment_attempts: bool = False,
        clear_error: bool = False,
    ) -> None:
        job_sql = text(
            f"""
            UPDATE index_jobs
            SET status = :job_status,
                stage = :stage,
                error = :error,
                attempts = attempts + :attempt_delta,
                updated_at = NOW(),
                started_at = {'COALESCE(started_at, NOW())' if started else 'started_at'},
                finished_at = {'NOW()' if finished else 'finished_at'}
            WHERE id = CAST(:job_id AS uuid)
            RETURNING document_id::text
            """
        )
        doc_sql = text(
            """
            UPDATE documents
            SET index_status = :doc_status,
                last_error = :last_error,
                updated_at = NOW()
            WHERE id = CAST(:document_id AS uuid)
            """
        )
        async with db_manager.get_postgres_session() as session:
            result = await session.execute(
                job_sql,
                {
                    "job_id": job_id,
                    "job_status": job_status,
                    "stage": stage,
                    "error": error,
                    "attempt_delta": 1 if increment_attempts else 0,
                },
            )
            document_id = result.scalar_one_or_none()
            if document_id:
                await session.execute(
                    doc_sql,
                    {
                        "document_id": document_id,
                        "doc_status": doc_status,
                        "last_error": None if clear_error else error,
                    },
                )
