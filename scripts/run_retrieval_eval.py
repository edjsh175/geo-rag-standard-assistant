"""GeoAI RAG synthetic ranking ablation runner (not a live retrieval benchmark).

Evaluates retrieval pipeline quality and ablations across:
- Keyword only
- Vector only
- Hybrid (RRF fusion)
- Hybrid + Heuristic Reranker

Produces metrics: MRR, Recall@K, Precision@K, HitRate@K, NDCG@K, Latency.
Outputs result report to evals/results/retrieval/latest.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

# Add Backend to sys.path so app packages can be imported
REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "Backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.models.search_models import DocumentResult
from app.services.rag.fusion import rrf_fuse
from app.services.rag.metrics import evaluate_retrieval_batch
from app.services.rag.reranker import RagReranker


def simulate_retrieval_channels(
    gold_entries: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, list[str]]]:
    """Simulate retrieval outputs for benchmark ablation when running without live DB.
    
    Returns a dict mapping mode -> (query_id -> list of retrieved doc_ids).
    """
    modes = ["keyword_only", "vector_only", "hybrid_rrf", "hybrid_rrf_rerank"]
    results_by_mode: dict[str, dict[str, list[str]]] = {m: {} for m in modes}

    for item in gold_entries:
        qid = item["query_id"]
        relevant = list(item.get("relevant_doc_ids", []))
        distractors = [f"doc_distractor_{qid}_{i}" for i in range(1, 10)]

        # Keyword channel: exact tokens matched, top-1 or top-2 relevant
        kw_ranked = [relevant[0]] + distractors[:3] + (relevant[1:] if len(relevant) > 1 else []) + distractors[3:]

        # Vector channel: semantic match, sometimes ranks second relevant higher
        if len(relevant) > 1:
            vec_ranked = [distractors[0], relevant[1], relevant[0]] + distractors[1:]
        else:
            vec_ranked = distractors[:1] + [relevant[0]] + distractors[1:]

        results_by_mode["keyword_only"][qid] = kw_ranked[:10]
        results_by_mode["vector_only"][qid] = vec_ranked[:10]

        # Hybrid RRF fusion
        def to_docs(ids: list[str]) -> list[DocumentResult]:
            from datetime import datetime
            return [
                DocumentResult(
                    id=did,
                    title=f"Doc {did}",
                    content=f"Content for {did}",
                    similarity=0.8 if did in relevant else 0.4,
                    metadata={"document_id": did},
                    spatial_info=None,
                    file_type="pdf",
                    file_size=1024,
                    upload_time=datetime.now(),
                    source_url=None,
                )
                for did in ids
            ]

        fused = rrf_fuse([to_docs(kw_ranked), to_docs(vec_ranked)], rrf_k=60, top_k=10)
        results_by_mode["hybrid_rrf"][qid] = [doc.id for doc in fused]

        # Hybrid RRF + Reranker
        reranker = RagReranker()
        reranked = reranker.rerank(query=item["query"], results=fused, top_k=10)
        results_by_mode["hybrid_rrf_rerank"][qid] = [doc.id for doc in reranked]

    return results_by_mode


def run_evaluation(
    gold_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    with open(gold_path, "r", encoding="utf-8") as f:
        gold_entries = json.load(f)

    ground_truth = {
        item["query_id"]: set(item.get("relevant_doc_ids", []))
        for item in gold_entries
    }

    start_time = time.perf_counter()
    retrieved_by_mode = simulate_retrieval_channels(gold_entries)
    elapsed_ms = (time.perf_counter() - start_time) * 1000

    report: dict[str, Any] = {
        "evaluation_kind": "synthetic_ablation",
        "live_retrieval": False,
        "retrieval_source": "simulated_from_gold_labels",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_queries": len(gold_entries),
        "total_time_ms": round(elapsed_ms, 2),
        "modes": {},
    }

    for mode_name, retrieved_dict in retrieved_by_mode.items():
        metrics = evaluate_retrieval_batch(
            queries_retrieved=retrieved_dict,
            ground_truth=ground_truth,
            ks=(3, 5, 10),
        )
        report["modes"][mode_name] = metrics

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run GeoAI RAG retrieval benchmark evaluation.")
    parser.add_argument(
        "--gold",
        type=Path,
        default=REPO_ROOT / "evals" / "retrieval_gold.json",
        help="Path to retrieval gold dataset",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "evals" / "results" / "retrieval" / "latest.json",
        help="Path to output results report",
    )
    args = parser.parse_args()

    print(f"Running retrieval evaluation with gold: {args.gold}")
    report = run_evaluation(args.gold, args.output)
    print("\n--- Synthetic Ranking Ablation (no live database retrieval) ---")
    for mode, metrics in report["modes"].items():
        print(f"\n[{mode}]")
        for k, v in metrics.items():
            print(f"  {k}: {v}")
    print(f"\nReport written to: {args.output}")


if __name__ == "__main__":
    main()
