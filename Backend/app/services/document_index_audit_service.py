"""Corpus & Chunk Health Audit Service for uploaded-document lifecycle (M-08 / K-08).

Performs read-only integrity checks on documents, versions, chunks, and index jobs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import text
from app.core.database import db_manager


@dataclass(frozen=True, slots=True)
class AuditIssue:
    category: str
    severity: str  # "ERROR" | "WARNING"
    entity_id: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CorpusAuditReport:
    is_healthy: bool
    checked_at: str
    total_documents: int
    total_chunks: int
    total_jobs: int
    issue_counts: dict[str, int]
    issues: list[AuditIssue]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DocumentIndexAuditService:
    """Read-only health and consistency audit service for document lifecycle."""

    def __init__(self, session_factory: Any | None = None) -> None:
        self.session_factory = session_factory or db_manager.get_postgres_session

    async def audit_corpus(self, *, stuck_threshold_minutes: int = 30) -> CorpusAuditReport:
        now_str = datetime.now(timezone.utc).isoformat()
        issues: list[AuditIssue] = []

        async with self.session_factory() as session:
            # 1. Total counts
            counts_sql = text(
                """
                SELECT
                    (SELECT COUNT(*) FROM documents WHERE deleted_at IS NULL)::int AS total_docs,
                    (SELECT COUNT(*) FROM document_chunks)::int AS total_chunks,
                    (SELECT COUNT(*) FROM index_jobs)::int AS total_jobs
                """
            )
            count_res = await session.execute(counts_sql)
            count_row = count_res.mappings().first() or {}
            total_docs = int(count_row.get("total_docs") or 0)
            total_chunks = int(count_row.get("total_chunks") or 0)
            total_jobs = int(count_row.get("total_jobs") or 0)

            # 2. Check indexed documents without chunks (ERROR)
            no_chunks_sql = text(
                """
                SELECT d.id::text AS document_id, d.title, d.index_status
                FROM documents d
                LEFT JOIN document_chunks c ON c.document_id = d.id
                WHERE d.deleted_at IS NULL AND d.index_status = 'indexed'
                GROUP BY d.id, d.title, d.index_status
                HAVING COUNT(c.id) = 0
                """
            )
            for row in (await session.execute(no_chunks_sql)).mappings().all():
                issues.append(
                    AuditIssue(
                        category="indexed_documents_without_chunks",
                        severity="ERROR",
                        entity_id=row["document_id"],
                        details={"title": row.get("title"), "index_status": row.get("index_status")},
                    )
                )

            # 3. Check stale version chunks (ERROR)
            stale_chunks_sql = text(
                """
                SELECT c.id::text AS chunk_id, c.document_id::text AS document_id,
                       c.version_id::text AS chunk_version_id,
                       d.current_version_id::text AS current_version_id
                FROM document_chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE d.deleted_at IS NULL
                  AND d.current_version_id IS NOT NULL
                  AND c.version_id != d.current_version_id
                """
            )
            for row in (await session.execute(stale_chunks_sql)).mappings().all():
                issues.append(
                    AuditIssue(
                        category="stale_version_chunks",
                        severity="ERROR",
                        entity_id=row["chunk_id"],
                        details={
                            "document_id": row["document_id"],
                            "chunk_version_id": row["chunk_version_id"],
                            "current_version_id": row["current_version_id"],
                        },
                    )
                )

            # 4. Check deleted documents still carrying chunks (ERROR)
            deleted_docs_sql = text(
                """
                SELECT c.id::text AS chunk_id, c.document_id::text AS document_id,
                       d.deleted_at::text AS deleted_at
                FROM document_chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE d.deleted_at IS NOT NULL
                """
            )
            for row in (await session.execute(deleted_docs_sql)).mappings().all():
                issues.append(
                    AuditIssue(
                        category="deleted_documents_with_chunks",
                        severity="ERROR",
                        entity_id=row["chunk_id"],
                        details={"document_id": row["document_id"], "deleted_at": row["deleted_at"]},
                    )
                )

            # 5. Check duplicate chunk_uids (ERROR)
            duplicate_uids_sql = text(
                """
                SELECT id::text AS chunk_uid, COUNT(*)::int AS count
                FROM document_chunks
                GROUP BY id
                HAVING COUNT(*) > 1
                """
            )
            for row in (await session.execute(duplicate_uids_sql)).mappings().all():
                issues.append(
                    AuditIssue(
                        category="duplicate_chunk_uids",
                        severity="ERROR",
                        entity_id=row["chunk_uid"],
                        details={"duplicate_count": row["count"]},
                    )
                )

            # 6. Check embedding dimension anomalies (ERROR)
            embedding_anomalies_sql = text(
                """
                SELECT id::text AS chunk_id, document_id::text AS document_id,
                       CASE WHEN embedding IS NULL THEN 'null_embedding'
                            WHEN vector_dims(embedding) != 2048 THEN 'dimension_mismatch'
                            ELSE 'ok' END AS anomaly_type
                FROM document_chunks
                WHERE embedding IS NULL OR vector_dims(embedding) != 2048
                """
            )
            for row in (await session.execute(embedding_anomalies_sql)).mappings().all():
                issues.append(
                    AuditIssue(
                        category="embedding_dimension_mismatch",
                        severity="ERROR",
                        entity_id=row["chunk_id"],
                        details={"document_id": row["document_id"], "anomaly_type": row["anomaly_type"]},
                    )
                )

            # 7. Check stuck jobs (WARNING / ERROR)
            stuck_jobs_sql = text(
                """
                SELECT id::text AS job_id, document_id::text AS document_id,
                       status, stage, attempts, updated_at::text AS updated_at
                FROM index_jobs
                WHERE status IN ('queued', 'running')
                  AND updated_at < NOW() - (CAST(:minutes AS text) || ' minutes')::interval
                """
            )
            for row in (await session.execute(stuck_jobs_sql, {"minutes": str(stuck_threshold_minutes)})).mappings().all():
                issues.append(
                    AuditIssue(
                        category="stuck_jobs",
                        severity="WARNING",
                        entity_id=row["job_id"],
                        details={
                            "document_id": row["document_id"],
                            "status": row["status"],
                            "stage": row["stage"],
                            "updated_at": row["updated_at"],
                        },
                    )
                )

            # 8. Check document status vs latest job status conflict (ERROR)
            conflicts_sql = text(
                """
                SELECT d.id::text AS document_id, d.index_status AS doc_status,
                       j.status AS job_status, j.id::text AS job_id
                FROM documents d
                JOIN LATERAL (
                    SELECT id, status
                    FROM index_jobs
                    WHERE document_id = d.id
                    ORDER BY created_at DESC
                    LIMIT 1
                ) j ON true
                WHERE d.deleted_at IS NULL
                  AND (
                      (d.index_status = 'indexed' AND j.status = 'failed')
                      OR (d.index_status = 'failed' AND j.status = 'succeeded')
                  )
                """
            )
            for row in (await session.execute(conflicts_sql)).mappings().all():
                issues.append(
                    AuditIssue(
                        category="status_conflicts",
                        severity="ERROR",
                        entity_id=row["document_id"],
                        details={
                            "job_id": row["job_id"],
                            "doc_status": row["doc_status"],
                            "job_status": row["job_status"],
                        },
                    )
                )

            # 9. Chunk length anomalies (WARNING)
            length_anomalies_sql = text(
                """
                SELECT id::text AS chunk_id, document_id::text AS document_id,
                       LENGTH(content)::int AS length
                FROM document_chunks
                WHERE LENGTH(content) < 5 OR LENGTH(content) > 3000
                """
            )
            for row in (await session.execute(length_anomalies_sql)).mappings().all():
                issues.append(
                    AuditIssue(
                        category="chunk_length_anomalies",
                        severity="WARNING",
                        entity_id=row["chunk_id"],
                        details={"document_id": row["document_id"], "length": row["length"]},
                    )
                )

        issue_counts: dict[str, int] = {}
        error_count = 0
        for issue in issues:
            issue_counts[issue.category] = issue_counts.get(issue.category, 0) + 1
            if issue.severity == "ERROR":
                error_count += 1

        is_healthy = error_count == 0

        return CorpusAuditReport(
            is_healthy=is_healthy,
            checked_at=now_str,
            total_documents=total_docs,
            total_chunks=total_chunks,
            total_jobs=total_jobs,
            issue_counts=issue_counts,
            issues=issues,
            summary={
                "error_count": error_count,
                "warning_count": len(issues) - error_count,
                "total_issues": len(issues),
            },
        )
