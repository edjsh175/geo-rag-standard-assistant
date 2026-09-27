from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.document_routes import reindex_document
from app.services.agent.contracts import EvidenceItem
from app.services.agent.evidence import EvidenceLedger
from app.services.document_chunker import DocumentChunk
from app.services.document_contract_service import DocumentContractService
from app.services.document_indexing_service import DocumentIndexingService
from app.services.document_parser import ParsedDocument
from app.services.document_repository import (
    DocumentDeletedConflictError,
    DocumentRepository,
    DocumentVersionConflictError,
)
from app.services.document_text_extractor import UnsupportedDocumentParser
from app.services.rag.contracts import RetrievalCandidate
from app.services.rag.postgres_adapter import PostgresRetrievalAdapter


# ==============================================================================
# G-01 Tests: Legacy Soft-Delete Filtering in Retrieval and Evidence Admission
# ==============================================================================


@pytest.mark.asyncio
async def test_g01_evidence_ledger_rejects_deleted_candidate() -> None:
    ledger = EvidenceLedger(session_id="session-g01")

    from app.models.search_models import DocumentResult

    def make_res(cid: str, title: str, meta: dict[str, Any]) -> DocumentResult:
        return DocumentResult(
            id=cid,
            title=title,
            content="标准条款内容",
            similarity=0.95,
            metadata=meta,
            spatial_info=None,
            file_type="pdf",
            file_size=1024,
            upload_time=datetime.now(),
        )

    valid_candidate = RetrievalCandidate.from_document_result(
        make_res("chunk-1", "有效技术标准", {"domain": "planning"})
    )
    deleted_candidate = RetrievalCandidate.from_document_result(
        make_res("chunk-2", "已废止标准", {"domain": "planning", "deleted_at": "2026-09-27T00:00:00Z"})
    )
    is_deleted_flag_candidate = RetrievalCandidate.from_document_result(
        make_res("chunk-3", "标记删除标准", {"domain": "planning", "is_deleted": True})
    )

    admitted = ledger.add_candidates(
        turn_id="turn-1",
        candidates=[valid_candidate, deleted_candidate, is_deleted_flag_candidate],
    )

    assert len(admitted) == 1
    assert admitted[0].chunk_id == "chunk-1"
    assert admitted[0].title == "有效技术标准"


@pytest.mark.asyncio
async def test_g01_retrieval_sql_filters_legacy_deleted_in_all_modes() -> None:
    adapter = PostgresRetrievalAdapter()

    # Verify SQL query strings contain the NOT EXISTS document_overrides check
    import inspect

    exact_src = inspect.getsource(adapter._exact_standard_code_search)
    assert "NOT EXISTS" in exact_src
    assert "document_overrides" in exact_src
    assert "do.deleted_at IS NOT NULL" in exact_src

    keyword_src = inspect.getsource(adapter._keyword_search)
    assert "NOT EXISTS" in keyword_src
    assert "document_overrides" in keyword_src
    assert "do.deleted_at IS NOT NULL" in keyword_src

    vector_src = inspect.getsource(adapter._vector_search)
    assert "NOT EXISTS" in vector_src
    assert "document_overrides" in vector_src
    assert "do.deleted_at IS NOT NULL" in vector_src

    fetch_src = inspect.getsource(adapter.fetch_chunks)
    assert "NOT EXISTS" in fetch_src
    assert "document_overrides" in fetch_src
    assert "do.deleted_at IS NOT NULL" in fetch_src


# ==============================================================================
# G-03 Tests: Delete-vs-Index TOCTOU Concurrency Guard
# ==============================================================================


@pytest.mark.asyncio
async def test_g03_indexing_aborts_early_if_document_deleted_during_processing(tmp_path: Path) -> None:
    local_path = tmp_path / "test.md"
    local_path.write_text("# 章节\n\n内容", encoding="utf-8")

    class DeletedDuringParsingRepo:
        def __init__(self) -> None:
            self.calls = 0
            self.cancelled = False
            self.cancel_reason = ""
            self.chunks_replaced = False

        async def claim_job(self, job_id: str, execution_token: str) -> bool:
            return True

        async def get_indexing_payload(self, job_id: str) -> dict[str, Any]:
            self.calls += 1
            # First call (start of job): document is active
            # Second call (after parsing): document is marked deleted!
            is_deleted = self.calls >= 2
            return {
                "job_id": job_id,
                "document_id": "doc-deleted-1",
                "version_id": "ver-1",
                "title": "测试文档",
                "filename": "test.md",
                "file_type": "md",
                "mime_type": "text/markdown",
                "storage_key": "uploads/doc/test.md",
                "metadata": {},
                "deleted_at": "2026-09-27T10:00:00Z" if is_deleted else None,
            }

        async def mark_job_running(self, job_id: str, stage: str, execution_token: str | None = None) -> None:
            pass

        async def mark_job_cancelled(self, job_id: str, error: str, execution_token: str | None = None) -> None:
            self.cancelled = True
            self.cancel_reason = error

        async def replace_chunks(self, **kwargs: Any) -> None:
            self.chunks_replaced = True

        async def mark_job_succeeded(self, job_id: str, execution_token: str | None = None) -> None:
            pass

    class Storage:
        async def download_version_to_temp(self, payload: dict[str, Any]) -> Path:
            return local_path

    class Parser:
        def parse(self, path: Path, content_type: str) -> ParsedDocument:
            return ParsedDocument(markdown="# 章节\n\n内容", metadata={})

    class Chunker:
        def chunk(self, document: ParsedDocument) -> list[DocumentChunk]:
            return [DocumentChunk(content="内容", header_path="章节", page_number=1)]

    class Embeddings:
        def __init__(self) -> None:
            self.called = False

        async def embed_texts(self, texts: list[str]) -> list[list[float]]:
            self.called = True
            return [[0.1] * 2048]

    repo = DeletedDuringParsingRepo()
    embeddings = Embeddings()
    service = DocumentIndexingService(
        repository=repo,
        storage=Storage(),
        parser=Parser(),
        chunker=Chunker(),
        embedding_provider=embeddings,
    )

    await service.run_job("job-toctou")

    assert repo.cancelled is True
    assert "deleted during parsing" in repo.cancel_reason
    assert repo.chunks_replaced is False
    assert embeddings.called is False  # Aborted BEFORE expensive embedding!


@pytest.mark.asyncio
async def test_g03_soft_delete_cancels_all_active_indexing_jobs() -> None:
    repo = DocumentRepository()

    # Mock the DB session to inspect SQL executed during soft_delete
    executed_sqls = []

    class FakeSession:
        async def execute(self, statement, params=None):
            sql_text = str(statement)
            executed_sqls.append((sql_text, params))
            mock_res = MagicMock()
            mock_res.rowcount = 1
            return mock_res

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("app.services.document_repository.db_manager.get_postgres_session", return_value=FakeSession()), \
         patch("app.services.document_repository.db_manager.postgres_sessionmaker", True):
        ok = await repo.soft_delete(doc_id="d1111111-1111-1111-1111-111111111111", requested_by="admin")

    assert ok is True
    # Verify that a cancel query was run on index_jobs
    cancel_query = next((sql for sql, params in executed_sqls if "UPDATE index_jobs" in sql and "status = 'cancelled'" in sql), None)
    assert cancel_query is not None
    assert "status IN ('queued', 'running', 'retrying')" in cancel_query


# ==============================================================================
# O-02 Tests: Celery Atomic Claim & Duplicate Delivery Idempotency
# ==============================================================================


@pytest.mark.asyncio
async def test_o02_claim_job_is_atomic_and_rejects_duplicate_worker() -> None:
    repo = DocumentRepository()

    # Simulate: First claim returns the job id (success), second claim returns None (already claimed)
    first_call = True

    class FakeSession:
        async def execute(self, statement, params=None):
            nonlocal first_call
            mock_res = MagicMock()
            if first_call:
                first_call = False
                mock_res.scalar_one_or_none.return_value = "job-uuid-1"
            else:
                mock_res.scalar_one_or_none.return_value = None
            return mock_res

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("app.services.document_repository.db_manager.get_postgres_session", return_value=FakeSession()), \
         patch("app.services.document_repository.db_manager.postgres_sessionmaker", True):
        # Worker A claims
        claimed_a = await repo.claim_job("job-uuid-1", execution_token="token-a")
        # Worker B tries to claim duplicate delivery
        claimed_b = await repo.claim_job("job-uuid-1", execution_token="token-b")

    assert claimed_a is True
    assert claimed_b is False


@pytest.mark.asyncio
async def test_o02_run_job_skips_when_claim_fails() -> None:
    mock_repo = MagicMock()
    mock_repo.claim_job = AsyncMock(return_value=False)  # Already claimed by another worker
    mock_repo.get_indexing_payload = AsyncMock()

    service = DocumentIndexingService(repository=mock_repo)
    await service.run_job("job-dup-1")

    # Should exit immediately after failing to claim
    mock_repo.claim_job.assert_awaited_once()
    mock_repo.get_indexing_payload.assert_not_called()


# ==============================================================================
# O-03 Tests: Suppress Duplicate Concurrent Reindex Jobs
# ==============================================================================


@pytest.mark.asyncio
async def test_o03_queue_reindex_job_returns_existing_active_job() -> None:
    repo = DocumentRepository()

    doc_id = "d3333333-3333-3333-3333-333333333333"
    existing_job_id = "j3333333-3333-3333-3333-333333333333"

    async def fake_detail(doc_id: str):
        return {"id": doc_id, "title": "重复索引测试"}

    create_called = False

    class FakeSession:
        def __init__(self):
            self.step = 0

        async def execute(self, statement, params=None):
            sql_text = str(statement)
            mock_res = MagicMock()
            if "current_version_id::text FROM documents" in sql_text:
                mock_res.scalar_one_or_none.return_value = "v3333333-3333-3333-3333-333333333333"
            elif "FROM index_jobs" in sql_text and "status IN ('queued', 'running', 'retrying')" in sql_text:
                # Returns existing active job!
                mock_res.scalar_one_or_none.return_value = existing_job_id
            return mock_res

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    async def fake_create_job(*args, **kwargs):
        nonlocal create_called
        create_called = True

    with patch.object(repo, "get_uploaded_document_detail", fake_detail), \
         patch("app.services.document_repository.db_manager.get_postgres_session", return_value=FakeSession()), \
         patch.object(repo, "create_index_job", fake_create_job):
        returned_job_id = await repo.queue_reindex_job(doc_id, requested_by="user-1")

    assert returned_job_id == existing_job_id
    assert create_called is False  # No new duplicate job was created!


# ==============================================================================
# G-02 Tests: Legacy Reindex API Returns 501 Not Implemented
# ==============================================================================


@pytest.mark.asyncio
async def test_g02_legacy_reindex_raises_501_not_implemented() -> None:
    legacy_doc_id = "12345"  # Non-UUID legacy document id

    with pytest.raises(HTTPException) as exc_info:
        await reindex_document(
            doc_id=legacy_doc_id,
            contract_service=MagicMock(),
            lifecycle_service=MagicMock(),
            actor="admin",
        )

    assert exc_info.value.status_code == 501
    assert "Reindexing legacy standard policy documents is not supported" in exc_info.value.detail
