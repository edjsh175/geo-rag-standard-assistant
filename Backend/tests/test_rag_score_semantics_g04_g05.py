"""Comprehensive tests for G-04 (Retrieval score semantics) and G-05 (Reranker configuration and wiring)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest

from app.core.config import settings
from app.models.search_models import DocumentResult
from app.services.rag.contracts import RetrievalCandidate, RetrievalQuery
from app.services.rag.fusion import rrf_fuse
from app.services.rag.postgres_adapter import PostgresRetrievalAdapter
from app.services.rag.reranker import (
    RagReranker,
    RemoteHttpReranker,
    create_reranker,
)


def _make_doc(
    doc_id: str,
    title: str,
    similarity: float = 0.8,
    standard_code: str | None = None,
    content: str = "标准正文片段",
    metadata: dict | None = None,
) -> DocumentResult:
    meta = dict(metadata or {})
    meta["chunk_id"] = doc_id
    meta["document_name"] = title
    if standard_code:
        meta["standard_code"] = standard_code
    return DocumentResult(
        id=doc_id,
        title=title,
        content=content,
        similarity=similarity,
        metadata=meta,
        spatial_info=None,
        file_type="pdf",
        file_size=1024,
        upload_time=datetime.now(timezone.utc).replace(tzinfo=None),
        source_url=None,
    )


# ============================================================================
# G-04: Retrieval Score Contract & Semantics Tests
# ============================================================================

def test_g04_document_result_score_model_defaults_and_explicit_fields() -> None:
    # 1. Default fallback: only similarity given
    doc = _make_doc("d1", "测试文档1", similarity=0.82)
    assert doc.similarity == 0.82
    assert doc.final_rank_score == 0.82
    assert doc.score_kind == "similarity"
    assert doc.vector_similarity is None
    assert doc.rrf_score is None
    assert doc.rerank_score is None

    # 2. Explicit score fields provided
    doc2 = DocumentResult(
        id="d2",
        title="测试文档2",
        content="内容",
        similarity=0.75,
        vector_similarity=0.75,
        keyword_score=0.60,
        rrf_score=0.032,
        rerank_score=1.45,
        final_rank_score=1.45,
        score_kind="rerank",
        metadata={},
        file_type="pdf",
        file_size=100,
        upload_time=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    assert doc2.vector_similarity == 0.75
    assert doc2.keyword_score == 0.60
    assert doc2.rrf_score == 0.032
    assert doc2.rerank_score == 1.45
    assert doc2.final_rank_score == 1.45
    assert doc2.score_kind == "rerank"

    # 3. Synchronize from metadata if metadata contains score keys
    doc3 = _make_doc("d3", "测试文档3", similarity=0.016, metadata={"rrf_score": 0.01639})
    assert doc3.rrf_score == 0.01639
    assert doc3.final_rank_score == 0.01639
    assert doc3.score_kind == "rrf"


def test_g04_rrf_fuse_populates_canonical_score_fields() -> None:
    doc_v = _make_doc("v1", "向量文档", similarity=0.91)
    doc_k = _make_doc("k1", "关键字文档", similarity=0.70)

    fused = rrf_fuse(
        [[doc_v], [doc_k]],
        rrf_k=60,
        top_k=2,
        channel_labels=["vector", "keyword"],
    )

    assert len(fused) == 2
    for doc in fused:
        assert doc.score_kind == "rrf"
        assert doc.rrf_score is not None
        assert doc.final_rank_score == doc.rrf_score
        assert doc.metadata["score_kind"] == "rrf"
        assert doc.metadata["final_rank_score"] == doc.rrf_score

    # Vector doc should preserve its original vector similarity
    fused_v = next(d for d in fused if d.id == "v1")
    assert fused_v.vector_similarity == 0.91


def test_g04_rag_reranker_updates_final_rank_score_without_corrupting_similarity() -> None:
    reranker = RagReranker()
    doc_match = _make_doc("target", "规划标准", similarity=0.72, standard_code="GB 50180-2018")
    doc_noise = _make_doc("noise", "噪音标准", similarity=0.95, standard_code="GB 99999-2020")

    results = reranker.rerank("GB 50180-2018", [doc_noise, doc_match], top_k=2)

    assert results[0].id == "target"
    # Similarity preserved
    assert results[0].similarity == 0.72
    # Rerank score elevated and recorded in canonical fields
    assert results[0].score_kind == "rerank"
    assert results[0].rerank_score is not None
    assert results[0].rerank_score > 1.5  # 0.72 + 1.0 exact match bonus
    assert results[0].final_rank_score == results[0].rerank_score


def test_g04_retrieval_candidate_maps_canonical_scores() -> None:
    doc = DocumentResult(
        id="chunk-123",
        title="空间规划总则",
        content="总则条款内容...",
        similarity=0.65,
        vector_similarity=0.65,
        keyword_score=0.45,
        rrf_score=0.025,
        rerank_score=1.65,
        final_rank_score=1.65,
        score_kind="rerank",
        metadata={"chunk_id": "chunk-123", "document_name": "空间规划总则"},
        file_type="pdf",
        file_size=2048,
        upload_time=datetime.now(timezone.utc).replace(tzinfo=None),
    )

    candidate = RetrievalCandidate.from_document_result(doc)

    assert candidate.chunk_id == "chunk-123"
    # Authoritative ranking score must be final_rank_score, NOT raw similarity
    assert candidate.score == 1.65
    assert candidate.score_kind == "rerank"
    assert candidate.vector_similarity == 0.65
    assert candidate.keyword_score == 0.45
    assert candidate.rrf_score == 0.025
    assert candidate.rerank_score == 1.65


# ============================================================================
# G-05: Reranker Configuration & Factory Wiring Tests
# ============================================================================

def test_g05_default_reranker_wiring_is_local_rag_reranker() -> None:
    adapter = PostgresRetrievalAdapter()
    assert isinstance(adapter.reranker, RagReranker)


def test_g05_settings_driven_reranker_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    # 1. Default local configuration
    monkeypatch.setattr(settings, "RERANKER_TYPE", "local")
    local_reranker = create_reranker()
    assert isinstance(local_reranker, RagReranker)

    # 2. Remote configuration
    monkeypatch.setattr(settings, "RERANKER_TYPE", "remote")
    monkeypatch.setattr(settings, "RERANKER_BASE_URL", "http://reranker-svc:8080")
    remote_reranker = create_reranker("remote", base_url="http://reranker-svc:8080")
    assert isinstance(remote_reranker, RemoteHttpReranker)
    assert remote_reranker.base_url == "http://reranker-svc:8080"
    assert isinstance(remote_reranker.fallback_reranker, RagReranker)

    # 3. Adapter picks up remote reranker when configured
    with patch("app.services.rag.postgres_adapter.settings") as mock_settings:
        mock_settings.RERANKER_TYPE = "remote"
        mock_settings.RERANKER_BASE_URL = "http://reranker-svc:8080"
        mock_settings.RERANKER_TIMEOUT_SECONDS = 5.0
        mock_settings.RERANKER_MODEL_NAME = "bge-reranker-large"

        adapter = PostgresRetrievalAdapter()
        assert isinstance(adapter.reranker, RemoteHttpReranker)
        assert adapter.reranker.base_url == "http://reranker-svc:8080"


def test_g05_remote_reranker_network_failure_gracefully_falls_back_to_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote_reranker = RemoteHttpReranker(
        base_url="http://invalid-reranker-host:9999",
        timeout=0.5,
    )

    doc1 = _make_doc("d1", "文档1", similarity=0.6, standard_code="GB 50180-2018")
    doc2 = _make_doc("d2", "文档2", similarity=0.8, standard_code="DB 11111-2020")

    # Call rerank with failing remote host; must gracefully fall back to RagReranker
    reranked = remote_reranker.rerank("GB 50180-2018", [doc2, doc1], top_k=2)

    assert len(reranked) == 2
    # Local fallback boosted exact standard code match for d1
    assert reranked[0].id == "d1"
    assert reranked[0].score_kind == "rerank"
    assert "standard_code_exact" in reranked[0].metadata["rerank_reasons"]
