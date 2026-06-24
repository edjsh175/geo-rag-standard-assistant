from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from app.services.document_indexing_service import DocumentIndexingService
from app.services.document_text_extractor import ExtractedDocumentText, UnsupportedDocumentParser


@dataclass
class FakeStorage:
    local_path: Path

    async def download_version_to_temp(self, payload: dict[str, Any]) -> Path:
        assert payload["storage_key"] == "uploads/doc-1/planning.md"
        return self.local_path


class FakeExtractor:
    def extract(self, path: Path, content_type: str):
        assert path.name == "planning.md"
        assert content_type == "text/markdown"
        return ExtractedDocumentText(text="# 第一章\n\n规划文本需要进入检索。")


class FakeUnsupportedExtractor:
    def extract(self, path: Path, content_type: str):
        raise UnsupportedDocumentParser("Legacy .doc parsing is not supported.")


class FakeEmbeddings:
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        assert texts
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeRepository:
    def __init__(self) -> None:
        self.stages: list[str] = []
        self.chunks: list[dict[str, Any]] = []
        self.failures: list[dict[str, Any]] = []
        self.succeeded = False

    async def get_indexing_payload(self, job_id: str) -> dict[str, Any]:
        assert job_id == "job-1"
        return {
            "job_id": "job-1",
            "document_id": "doc-1",
            "version_id": "version-1",
            "title": "规划文本",
            "filename": "planning.md",
            "file_type": "md",
            "mime_type": "text/markdown",
            "storage_key": "uploads/doc-1/planning.md",
            "metadata": {"title": "规划文本"},
            "spatial_metadata": None,
            "deleted_at": None,
        }

    async def mark_job_running(self, job_id: str, stage: str) -> None:
        self.stages.append(stage)

    async def update_job_stage(self, job_id: str, stage: str) -> None:
        self.stages.append(stage)

    async def replace_chunks(self, **payload: Any) -> None:
        self.chunks = payload["chunks"]

    async def mark_job_succeeded(self, job_id: str) -> None:
        self.succeeded = True

    async def mark_job_failed(self, job_id: str, error: str, retrying: bool = False) -> None:
        self.failures.append({"job_id": job_id, "error": error, "retrying": retrying})


@pytest.mark.asyncio
async def test_indexing_service_extracts_chunks_embeds_and_marks_success(tmp_path) -> None:
    local_path = tmp_path / "planning.md"
    local_path.write_text("# 第一章\n\n规划文本需要进入检索。", encoding="utf-8")
    repository = FakeRepository()
    service = DocumentIndexingService(
        repository=repository,
        storage=FakeStorage(local_path),
        extractor=FakeExtractor(),
        embedding_provider=FakeEmbeddings(),
    )

    await service.run_job("job-1")

    assert repository.stages == ["parsing", "chunking", "embedding"]
    assert repository.succeeded is True
    assert repository.chunks
    assert repository.chunks[0]["content"] == "# 第一章\n\n规划文本需要进入检索。"
    assert repository.chunks[0]["metadata"]["title"] == "规划文本"
    assert repository.chunks[0]["embedding"] == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_indexing_service_does_not_retry_unsupported_parser(tmp_path) -> None:
    local_path = tmp_path / "planning.doc"
    local_path.write_bytes(b"legacy doc")
    repository = FakeRepository()
    service = DocumentIndexingService(
        repository=repository,
        storage=FakeStorage(local_path),
        extractor=FakeUnsupportedExtractor(),
        embedding_provider=FakeEmbeddings(),
    )

    with pytest.raises(UnsupportedDocumentParser):
        await service.run_job("job-1", retrying_on_error=True)

    assert repository.failures == [
        {
            "job_id": "job-1",
            "error": "Legacy .doc parsing is not supported.",
            "retrying": False,
        }
    ]
