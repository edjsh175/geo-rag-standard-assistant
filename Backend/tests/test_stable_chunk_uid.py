from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
import uuid

import pytest

from app.services.document_chunker import (
    DocumentChunk,
    DocumentChunker,
    compute_chunk_uid,
    compute_content_hash,
)
from app.services.document_indexing_service import DocumentIndexingService
from app.services.document_parser import ParsedDocument
from app.services.document_repository import DocumentRepository
from app.services.rag.postgres_adapter import PostgresRetrievalAdapter


def test_compute_content_hash_is_deterministic() -> None:
    text = "空间规划实施监测评估预警标准"
    hash1 = compute_content_hash(text)
    hash2 = compute_content_hash(text)
    assert hash1 == hash2
    assert len(hash1) == 64  # SHA-256 hex digest
    # Whitespace trimming normalization
    assert compute_content_hash(f"  {text}\n") == hash1
    assert compute_content_hash("不同内容") != hash1


def test_compute_chunk_uid_is_valid_rfc4122_uuid_and_deterministic() -> None:
    doc_id = "11111111-2222-3333-4444-555555555555"
    section = "第一章 > 总体要求"
    index = 0
    content = "规划指标应当符合国土空间规划总体要求。"
    content_hash = compute_content_hash(content)

    uid1 = compute_chunk_uid(doc_id, section, index, content_hash)
    uid2 = compute_chunk_uid(doc_id, section, index, content_hash)

    # Determinism
    assert uid1 == uid2

    # Valid UUID format (RFC 4122 UUIDv5)
    parsed_uuid = uuid.UUID(uid1)
    assert parsed_uuid.version == 5

    # Any variance in inputs yields a distinct chunk_uid
    # Content changed
    changed_content_hash = compute_content_hash("规划指标更新为严格控制边界。")
    assert compute_chunk_uid(doc_id, section, index, changed_content_hash) != uid1

    # Section changed
    assert compute_chunk_uid(doc_id, "第二章 > 规划分区", index, content_hash) != uid1

    # Index changed
    assert compute_chunk_uid(doc_id, section, 1, content_hash) != uid1

    # Document ID changed
    other_doc_id = "99999999-8888-7777-6666-555555555555"
    assert compute_chunk_uid(other_doc_id, section, index, content_hash) != uid1


def test_document_chunk_computes_content_hash_in_post_init() -> None:
    chunk = DocumentChunk(content="测试文本内容", header_path="第一节")
    assert chunk.content_hash == compute_content_hash("测试文本内容")

    explicit_hash = "custom_hash_123"
    chunk_explicit = DocumentChunk(content="测试文本内容", header_path="第一节", content_hash=explicit_hash)
    assert chunk_explicit.content_hash == explicit_hash


@pytest.mark.asyncio
async def test_document_indexing_service_produces_stable_chunk_uid(tmp_path: Path) -> None:
    doc_file = tmp_path / "plan.md"
    doc_file.write_text("# 概述\n\n国土空间规划基本原则。", encoding="utf-8")

    captured_chunks: list[dict[str, Any]] = []

    class MockRepository:
        async def get_indexing_payload(self, job_id: str) -> dict[str, Any]:
            return {
                "job_id": job_id,
                "document_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "version_id": "11111111-2222-3333-4444-555555555555",
                "title": "规划原则",
                "filename": "plan.md",
                "file_type": "md",
                "mime_type": "text/markdown",
                "storage_key": "uploads/plan.md",
                "metadata": {},
                "spatial_metadata": None,
                "deleted_at": None,
            }

        async def mark_job_running(self, job_id: str, stage: str) -> None:
            pass

        async def update_job_stage(self, job_id: str, stage: str) -> None:
            pass

        async def replace_chunks(self, **payload: Any) -> None:
            nonlocal captured_chunks
            captured_chunks = payload["chunks"]

        async def mark_job_succeeded(self, job_id: str) -> None:
            pass

        async def mark_job_failed(self, job_id: str, error: str, retrying: bool = False) -> None:
            pass

    class MockStorage:
        async def download_version_to_temp(self, payload: dict[str, Any]) -> Path:
            import shutil
            import tempfile
            temp_file = Path(tempfile.NamedTemporaryFile(delete=False, suffix=".md").name)
            shutil.copy(doc_file, temp_file)
            return temp_file

    class MockEmbeddings:
        async def embed_texts(self, texts: list[str]) -> list[list[float]]:
            return [[0.0] * 2048 for _ in texts]

    service = DocumentIndexingService(
        repository=MockRepository(),
        storage=MockStorage(),
        parser=None,  # default parser parses doc_file
        chunker=DocumentChunker(chunk_size=100, chunk_overlap=10),
        embedding_provider=MockEmbeddings(),
    )

    # First indexing run
    await service.run_job("job-run-1")
    assert len(captured_chunks) > 0
    first_chunk = captured_chunks[0]
    first_chunk_uid = first_chunk["chunk_uid"]
    assert first_chunk["id"] == first_chunk_uid
    assert first_chunk["content_hash"]
    assert first_chunk["metadata"]["chunk_uid"] == first_chunk_uid

    # Second indexing run (reindexing unchanged document)
    await service.run_job("job-run-2")
    second_chunk = captured_chunks[0]
    second_chunk_uid = second_chunk["chunk_uid"]

    # Reindexing logically unchanged chunks retains identical chunk_uid
    assert first_chunk_uid == second_chunk_uid


@pytest.mark.asyncio
async def test_replace_chunks_uses_deterministic_chunk_uid_when_not_provided() -> None:
    """Verify DocumentRepository.replace_chunks does not generate random uuid4 on each run."""
    repo = DocumentRepository()

    doc_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    version_id = "11111111-2222-3333-4444-555555555555"
    chunks_input = [
        {
            "chunk_index": 0,
            "header_path": "章1",
            "page_number": 1,
            "content": "测试持久化不变性内容",
            "metadata": {"title": "测试"},
            "embedding": [0.1] * 2048,
        }
    ]

    executed_inserts: list[dict[str, Any]] = []

    class MockSession:
        async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> Any:
            if params and "id" in params and "chunk_index" in params:
                executed_inserts.append(dict(params))
            return SimpleNamespace(rowcount=1)

    class MockSessionContext:
        async def __aenter__(self):
            return MockSession()

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    from app.core.database import db_manager
    original_get_session = db_manager.get_postgres_session
    db_manager.get_postgres_session = lambda: MockSessionContext()

    try:
        # Run 1
        await repo.replace_chunks(
            document_id=doc_id,
            version_id=version_id,
            chunks=chunks_input,
        )
        assert len(executed_inserts) == 1
        id_run_1 = executed_inserts[0]["id"]
        meta_run_1 = executed_inserts[0]["metadata"]

        # Run 2 with same content
        executed_inserts.clear()
        await repo.replace_chunks(
            document_id=doc_id,
            version_id=version_id,
            chunks=chunks_input,
        )
        assert len(executed_inserts) == 1
        id_run_2 = executed_inserts[0]["id"]

        # Deterministic: same inputs produce identical chunk id
        assert id_run_1 == id_run_2
        assert "chunk_uid" in meta_run_1
        assert id_run_1 == compute_chunk_uid(
            doc_id,
            "章1",
            0,
            compute_content_hash("测试持久化不变性内容"),
        )
    finally:
        db_manager.get_postgres_session = original_get_session


def test_postgres_adapter_uploaded_chunk_result_exposes_chunk_uid() -> None:
    adapter = PostgresRetrievalAdapter()
    stable_uid = str(uuid.uuid4())
    row = SimpleNamespace(
        chunk_id=stable_uid,
        document_id="doc-123",
        title="测试规划",
        filename="test.md",
        file_type="md",
        file_size=512,
        created_at=None,
        content="片段文本",
        metadata={"chunk_uid": stable_uid, "content_hash": "hash123"},
        spatial_metadata=None,
        download_url="/api/doc/download",
    )

    result = adapter._build_uploaded_chunk_result(row, similarity=0.9, match_type="uploaded_keyword")
    assert result.metadata["chunk_id"] == stable_uid
    assert result.metadata["chunk_uid"] == stable_uid
    assert result.metadata["content_hash"] == "hash123"
