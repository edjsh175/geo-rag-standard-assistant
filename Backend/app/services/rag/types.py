"""Internal RAG orchestration types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.models.search_models import DocumentResult, MetadataFilter, SpatialFilter


@dataclass(frozen=True)
class SearchContext:
    """Immutable context for one retrieval request."""

    query: str
    top_k: int = 10
    threshold: float = 0.7
    search_mode: str = "hybrid"
    use_rerank: bool = True
    spatial_filter: Optional[SpatialFilter] = None
    metadata_filter: Optional[MetadataFilter] = None

    @property
    def mode(self) -> str:
        normalized = (self.search_mode or "hybrid").strip().lower()
        if normalized in {"semantic", "vector"}:
            return "semantic"
        if normalized in {"keyword", "exact"}:
            return normalized
        return "hybrid"


@dataclass(frozen=True)
class RetrievalResultSet:
    """Results plus diagnostics emitted by retrievers."""

    results: list[DocumentResult]
    embedding_available: bool
    exact_count: int = 0
    keyword_count: int = 0
    vector_count: int = 0
