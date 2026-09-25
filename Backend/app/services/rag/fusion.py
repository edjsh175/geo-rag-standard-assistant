"""Reciprocal Rank Fusion (RRF) and candidate rank fusion for multi-channel retrieval."""

from __future__ import annotations

from typing import Any, Sequence
from app.models.search_models import DocumentResult


def rrf_fuse(
    ranked_lists: Sequence[Sequence[DocumentResult]],
    *,
    rrf_k: int = 60,
    top_k: int = 10,
    weights: Sequence[float] | None = None,
    channel_labels: Sequence[str] | None = None,
) -> list[DocumentResult]:
    """Fuse multiple ranked candidate lists using weighted Reciprocal Rank Fusion.

    Formula:
        RRF_Score(d) = sum_{m in M} ( w_m / (rrf_k + rank_m(d)) )

    Args:
        ranked_lists: Ordered lists of DocumentResult from different retrieval branches.
        rrf_k: Constant smoothing parameter, standard default 60.
        top_k: Maximum number of fused results to return.
        weights: Channel weights corresponding to each list in ranked_lists. Defaults to 1.0.
        channel_labels: Channel identifiers (e.g. 'exact', 'keyword', 'vector').

    Returns:
        Fused and sorted list of DocumentResult with rrf_score and matched_channels in metadata.
    """
    if not ranked_lists:
        return []

    effective_weights = (
        list(weights) if weights is not None else [1.0] * len(ranked_lists)
    )
    effective_labels = (
        list(channel_labels)
        if channel_labels is not None
        else [f"channel_{i}" for i in range(len(ranked_lists))]
    )

    scores: dict[str, dict[str, Any]] = {}

    for branch_idx, ranked_docs in enumerate(ranked_lists):
        w = effective_weights[branch_idx] if branch_idx < len(effective_weights) else 1.0
        label = effective_labels[branch_idx] if branch_idx < len(effective_labels) else f"branch_{branch_idx}"

        for rank, doc in enumerate(ranked_docs, start=1):
            key = str(doc.metadata.get("chunk_id") or doc.metadata.get("document_name") or doc.title or doc.id)
            if key not in scores:
                scores[key] = {
                    "doc": doc,
                    "score": 0.0,
                    "best_rank": rank,
                    "labels": set(),
                }
            entry = scores[key]
            entry["score"] += w / (rrf_k + rank)
            if rank < entry["best_rank"]:
                entry["best_rank"] = rank
                # Prefer document instance from higher ranking branch
                entry["doc"] = doc
            entry["labels"].add(label)

    # Sort key: primary descending rrf score, secondary ascending best rank, tertiary stable key
    sorted_items = sorted(
        scores.items(),
        key=lambda item: (-item[1]["score"], item[1]["best_rank"], str(item[0])),
    )

    fused_results: list[DocumentResult] = []
    for key, data in sorted_items[:top_k]:
        doc = data["doc"]
        meta = dict(doc.metadata or {})
        meta["rrf_score"] = round(data["score"], 6)
        meta["matched_channels"] = sorted(list(data["labels"]))
        # Clone doc with updated metadata
        updated_doc = DocumentResult(
            id=doc.id,
            title=doc.title,
            content=doc.content,
            similarity=float(meta["rrf_score"]),
            metadata=meta,
            spatial_info=doc.spatial_info,
            file_type=doc.file_type,
            file_size=doc.file_size,
            upload_time=doc.upload_time,
            source_url=doc.source_url,
            download_available=doc.download_available,
            download_url=doc.download_url,
        )
        fused_results.append(updated_doc)

    return fused_results
