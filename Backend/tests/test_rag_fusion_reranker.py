"""Tests for RAG candidate fusion, QueryPlanner, Reranker contracts, and evaluation metrics."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch
import pytest

from app.models.search_models import DocumentResult
from app.services.rag.contracts import RetrievalQuery
from app.services.rag.fusion import rrf_fuse
from app.services.rag.metrics import (
    evaluate_retrieval_batch,
    hit_rate_at_k,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)
from app.services.rag.postgres_adapter import PostgresRetrievalAdapter
from app.services.rag.query_planner import QueryPlanner
from app.services.rag.reranker import (
    BaseReranker,
    RagReranker,
    RemoteHttpReranker,
    create_reranker,
)


def make_doc(doc_id: str, title: str, similarity: float = 0.5, content: str = "") -> DocumentResult:
    return DocumentResult(
        id=doc_id,
        title=title,
        content=content or f"Content for {title}",
        similarity=similarity,
        metadata={"chunk_id": doc_id, "document_name": title},
        spatial_info=None,
        file_type="pdf",
        file_size=1024,
        upload_time=datetime.now(),
        source_url=None,
    )


# ==================== 1. RRF Fusion Tests ====================

def test_rrf_fuse_ranking_and_telemetry():
    doc_a = make_doc("doc_a", "文档A")
    doc_b = make_doc("doc_b", "文档B")
    doc_c = make_doc("doc_c", "文档C")

    # Channel 1: [A, B] with weight 2.0
    # Channel 2: [B, C] with weight 1.0
    list_1 = [doc_a, doc_b]
    list_2 = [doc_b, doc_c]

    fused = rrf_fuse(
        [list_1, list_2],
        rrf_k=60,
        top_k=3,
        weights=[2.0, 1.0],
        channel_labels=["exact", "keyword"],
    )

    assert len(fused) == 3
    # Scores:
    # A: 2.0 / (60 + 1) = 2.0 / 61 ≈ 0.032787
    # B: 2.0 / (60 + 2) + 1.0 / (60 + 1) = 2/62 + 1/61 ≈ 0.032258 + 0.016393 ≈ 0.048651
    # C: 1.0 / (60 + 2) = 1/62 ≈ 0.016129
    # B has highest combined score, followed by A, then C
    assert fused[0].id == "doc_b"
    assert fused[1].id == "doc_a"
    assert fused[2].id == "doc_c"

    # Telemetry
    assert fused[0].metadata["matched_channels"] == ["exact", "keyword"]
    assert fused[1].metadata["matched_channels"] == ["exact"]
    assert fused[2].metadata["matched_channels"] == ["keyword"]
    assert "rrf_score" in fused[0].metadata
    assert fused[0].similarity == fused[0].metadata["rrf_score"]


def test_rrf_fuse_tie_breaking_and_limits():
    doc_1 = make_doc("doc_1", "文档1")
    doc_2 = make_doc("doc_2", "文档2")

    # Equal weights and single list: top_k limit
    fused = rrf_fuse([[doc_1, doc_2]], top_k=1)
    assert len(fused) == 1
    assert fused[0].id == "doc_1"


# ==================== 2. Query Planner Tests ====================

def test_query_planner_standard_code():
    planner = QueryPlanner()
    query = RetrievalQuery(query_text="请查阅 GB 50016-2014 建筑设计防火规范", top_k=5)
    plan = planner.plan(query)

    assert plan.intent == "standard_code"
    assert plan.top_k == 5
    assert plan.candidate_k >= 15
    assert plan.channel_weights["exact"] > plan.channel_weights["vector"]


def test_query_planner_spatial_intent():
    planner = QueryPlanner()
    query = RetrievalQuery(query_text="查询青羊区规划红线范围内的控制指标", top_k=4)
    plan = planner.plan(query)

    assert plan.intent == "spatial"
    assert plan.candidate_k >= 16
    assert plan.channel_weights["vector"] >= 1.5


def test_query_planner_comparative_intent():
    planner = QueryPlanner()
    query = RetrievalQuery(query_text="商业用地与住宅用地的建筑密度有什么区别和对比？", top_k=5)
    plan = planner.plan(query)

    assert plan.intent == "comparative"
    assert plan.candidate_k >= 15


# ==================== 3. Reranker Contracts & Fallbacks ====================

def test_local_rag_reranker():
    reranker = RagReranker()
    doc_std = make_doc("d1", "GB 50016-2014 建筑设计防火规范", content="防火分区规定")
    doc_std.metadata["standard_code"] = "GB 50016-2014"
    doc_gen = make_doc("d2", "通用规划设计指南", content="一般建筑设计")

    results = reranker.rerank(
        query="GB 50016-2014",
        results=[doc_gen, doc_std],
        top_k=2,
    )
    # Exact standard code match must boost d1 to top
    assert results[0].id == "d1"
    assert results[0].metadata.get("standard_code_match_type") == "exact"


def test_remote_http_reranker_success():
    remote = RemoteHttpReranker(base_url="http://mock-reranker.internal", timeout=5.0)
    doc_1 = make_doc("d1", "标题1", content="文本内容1")
    doc_2 = make_doc("d2", "标题2", content="文本内容2")

    mock_resp_data = [{"index": 1, "score": 0.98}, {"index": 0, "score": 0.45}]

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json_bytes(mock_resp_data)
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        reranked = remote.rerank("测试查询", [doc_1, doc_2], top_k=2)

        assert len(reranked) == 2
        assert reranked[0].id == "d2"
        assert reranked[0].metadata["remote_rerank_score"] == 0.98
        assert reranked[1].id == "d1"


def test_remote_http_reranker_fallback_on_network_error():
    remote = RemoteHttpReranker(base_url="http://unavailable-reranker:9999", timeout=1.0)
    doc_1 = make_doc("d1", "GB 50016-2014", content="标准条文")
    doc_1.metadata["standard_code"] = "GB 50016-2014"
    doc_2 = make_doc("d2", "其他文档", content="一般内容")

    with patch("urllib.request.urlopen", side_effect=OSError("Connection refused")):
        # Must not raise error; must fall back to local RagReranker
        reranked = remote.rerank("GB 50016-2014", [doc_2, doc_1], top_k=2)
        assert len(reranked) == 2
        assert reranked[0].id == "d1"


def test_create_reranker_factory():
    local_reranker = create_reranker("local")
    assert isinstance(local_reranker, RagReranker)

    remote_reranker = create_reranker("remote", base_url="http://rerank.internal:8000")
    assert isinstance(remote_reranker, RemoteHttpReranker)


# ==================== 4. Retrieval Evaluation Metrics Tests ====================

def test_retrieval_metrics_exact_calculations():
    retrieved = ["doc1", "doc2", "doc3", "doc4", "doc5"]
    relevant = {"doc2", "doc5", "doc7"}

    # Recall@3: in top 3 ['doc1', 'doc2', 'doc3'], hits={'doc2'} (1/3)
    assert pytest.approx(recall_at_k(retrieved, relevant, 3), rel=1e-3) == 1.0 / 3.0
    # Recall@5: in top 5, hits={'doc2', 'doc5'} (2/3)
    assert pytest.approx(recall_at_k(retrieved, relevant, 5), rel=1e-3) == 2.0 / 3.0

    # Precision@3: 1 hit in 3 retrieved = 1/3
    assert pytest.approx(precision_at_k(retrieved, relevant, 3), rel=1e-3) == 1.0 / 3.0
    # Precision@5: 2 hits in 5 retrieved = 2/5 = 0.4
    assert pytest.approx(precision_at_k(retrieved, relevant, 5), rel=1e-3) == 0.4

    # MRR: first hit is doc2 at rank 2 -> MRR = 0.5
    assert pytest.approx(mrr(retrieved, relevant), rel=1e-3) == 0.5

    # HitRate@1 = 0, HitRate@2 = 1.0
    assert hit_rate_at_k(retrieved, relevant, 1) == 0.0
    assert hit_rate_at_k(retrieved, relevant, 2) == 1.0

    # NDCG@3: DCG = 1 / log2(2 + 1) = 1 / log2(3) ≈ 0.6309
    # Ideal hits in 3 = min(3, 3) = 3 items at ranks 1, 2, 3 -> IDCG = 1/log2(2) + 1/log2(3) + 1/log2(4) = 1 + 0.6309 + 0.5 = 2.1309
    assert ndcg_at_k(retrieved, relevant, 3) > 0.0


def test_evaluate_retrieval_batch():
    batch = {
        "q1": ["docA", "docB", "docC"],
        "q2": ["docX", "docY", "docZ"],
    }
    ground_truth = {
        "q1": ["docA"],  # rank 1 hit
        "q2": ["docY"],  # rank 2 hit
    }
    results = evaluate_retrieval_batch(batch, ground_truth, ks=(1, 3))
    # MRR for q1 = 1.0, for q2 = 0.5 -> average = 0.75
    assert pytest.approx(results["mrr"], rel=1e-3) == 0.75
    assert "recall@3" in results
    assert "hit_rate@1" in results


def json_bytes(obj) -> bytes:
    import json
    return json.dumps(obj).encode("utf-8")
