"""Retrieval evaluation metrics: Recall@K, Precision@K, MRR, HitRate@K, NDCG@K."""

from __future__ import annotations

import math
from typing import Sequence, Set


def recall_at_k(
    retrieved: Sequence[str],
    relevant: Sequence[str] | Set[str],
    k: int,
) -> float:
    """Calculate Recall@K: proportion of relevant items retrieved in top-k."""
    rel_set = set(relevant)
    if not rel_set:
        return 1.0
    top_k = retrieved[:k]
    hits = sum(1 for item in top_k if item in rel_set)
    return hits / len(rel_set)


def precision_at_k(
    retrieved: Sequence[str],
    relevant: Sequence[str] | Set[str],
    k: int,
) -> float:
    """Calculate Precision@K: proportion of top-k retrieved items that are relevant."""
    if k <= 0:
        return 0.0
    rel_set = set(relevant)
    top_k = retrieved[:k]
    hits = sum(1 for item in top_k if item in rel_set)
    return hits / k


def mrr(
    retrieved: Sequence[str],
    relevant: Sequence[str] | Set[str],
) -> float:
    """Calculate Mean Reciprocal Rank (MRR) for a single query."""
    rel_set = set(relevant)
    if not rel_set:
        return 0.0
    for rank, item in enumerate(retrieved, start=1):
        if item in rel_set:
            return 1.0 / rank
    return 0.0


def hit_rate_at_k(
    retrieved: Sequence[str],
    relevant: Sequence[str] | Set[str],
    k: int,
) -> float:
    """Calculate Hit Rate@K (1.0 if any relevant item is in top-k, else 0.0)."""
    rel_set = set(relevant)
    if not rel_set:
        return 0.0
    top_k = retrieved[:k]
    return 1.0 if any(item in rel_set for item in top_k) else 0.0


def ndcg_at_k(
    retrieved: Sequence[str],
    relevant: Sequence[str] | Set[str],
    k: int,
) -> float:
    """Calculate Normalized Discounted Cumulative Gain at K (binary relevance)."""
    rel_set = set(relevant)
    if not rel_set or k <= 0:
        return 0.0

    dcg = 0.0
    for i, item in enumerate(retrieved[:k], start=1):
        if item in rel_set:
            dcg += 1.0 / math.log2(i + 1)

    # Ideal DCG with all relevant items placed at the top
    ideal_hits = min(k, len(rel_set))
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))

    return dcg / idcg if idcg > 0.0 else 0.0


def evaluate_retrieval_batch(
    queries_retrieved: dict[str, Sequence[str]],
    ground_truth: dict[str, Sequence[str] | Set[str]],
    ks: tuple[int, ...] = (3, 5, 10),
) -> dict[str, float]:
    """Compute aggregate retrieval metrics across a batch of test queries."""
    if not queries_retrieved:
        return {}

    num_queries = len(queries_retrieved)
    total_mrr = 0.0
    total_recalls = {k: 0.0 for k in ks}
    total_precisions = {k: 0.0 for k in ks}
    total_hit_rates = {k: 0.0 for k in ks}
    total_ndcgs = {k: 0.0 for k in ks}

    for query_id, retrieved in queries_retrieved.items():
        relevant = ground_truth.get(query_id, ())
        total_mrr += mrr(retrieved, relevant)
        for k in ks:
            total_recalls[k] += recall_at_k(retrieved, relevant, k)
            total_precisions[k] += precision_at_k(retrieved, relevant, k)
            total_hit_rates[k] += hit_rate_at_k(retrieved, relevant, k)
            total_ndcgs[k] += ndcg_at_k(retrieved, relevant, k)

    results: dict[str, float] = {
        "mrr": round(total_mrr / num_queries, 4),
    }
    for k in ks:
        results[f"recall@{k}"] = round(total_recalls[k] / num_queries, 4)
        results[f"precision@{k}"] = round(total_precisions[k] / num_queries, 4)
        results[f"hit_rate@{k}"] = round(total_hit_rates[k] / num_queries, 4)
        results[f"ndcg@{k}"] = round(total_ndcgs[k] / num_queries, 4)

    return results
