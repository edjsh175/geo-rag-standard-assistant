from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from app.services.search_service import SearchService


def test_uploaded_chunk_result_uses_document_id_and_exposes_chunk_id() -> None:
    service = SearchService()
    row = SimpleNamespace(
        chunk_id="chunk-1",
        document_id="doc-1",
        title="规划文档",
        filename="planning.md",
        file_type="md",
        file_size=128,
        created_at=datetime(2026, 6, 18),
        content="规划文本片段",
        metadata={"category": "规划"},
        spatial_metadata={"province": "重庆市"},
        download_url="/api/documents/doc-1/download",
    )

    result = service._build_uploaded_chunk_result(row, similarity=0.82, match_type="uploaded_keyword")

    assert result.id == "doc-1"
    assert result.title == "规划文档"
    assert result.metadata["chunk_id"] == "chunk-1"
    assert result.metadata["document_type"] == "上传文档"
    assert result.download_available is True
    assert result.download_url == "/api/documents/doc-1/download"
