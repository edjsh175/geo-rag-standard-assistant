"""Storage-neutral retrieval contracts used by deterministic search and Agent tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence

from app.models.search_models import DocumentResult, MetadataFilter, SpatialFilter


@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    query_text: str
    top_k: int = 10
    threshold: float = 0.7
    search_mode: str = "hybrid"
    use_rerank: bool = True
    metadata_filter: MetadataFilter | None = None
    spatial_filter: SpatialFilter | None = None

    @property
    def mode(self) -> str:
        normalized = (self.search_mode or "hybrid").strip().lower()
        aliases = {
            "vector": "semantic",
            "semantic": "semantic",
            "keyword": "keyword",
            "exact": "exact",
            "hybrid": "hybrid",
        }
        return aliases.get(normalized, "hybrid")


@dataclass(frozen=True, slots=True)
class RetrievalProvenance:
    source: str
    match_type: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RetrievalCandidate:
    chunk_id: str
    document_id: str | None
    text: str
    title: str
    score: float
    metadata: dict[str, Any]
    provenance: RetrievalProvenance
    source_result: DocumentResult

    @classmethod
    def from_document_result(cls, result: DocumentResult) -> "RetrievalCandidate":
        metadata = dict(result.metadata or {})
        raw_chunk_id = metadata.get("chunk_id") or result.id
        raw_document_id = metadata.get("document_id")

        return cls(
            chunk_id=str(raw_chunk_id),
            document_id=str(raw_document_id) if raw_document_id is not None else None,
            text=result.content or "",
            title=result.title or "",
            score=float(result.similarity),
            metadata=metadata,
            provenance=RetrievalProvenance(
                source="postgres",
                match_type=str(metadata.get("match_type") or "unknown"),
                metadata={
                    "standard_code": metadata.get("standard_code"),
                    "document_name": metadata.get("document_name"),
                },
            ),
            source_result=result,
        )


@dataclass(frozen=True, slots=True)
class RetrievalDiagnostics:
    exact_count: int = 0
    keyword_count: int = 0
    vector_count: int = 0


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    candidates: tuple[RetrievalCandidate, ...]
    embedding_available: bool
    diagnostics: RetrievalDiagnostics = field(default_factory=RetrievalDiagnostics)


class RetrievalPort(Protocol):
    async def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        """Retrieve evidence candidates without exposing storage implementation details."""

    async def fetch_chunks(self, chunk_ids: Sequence[str]) -> list[RetrievalCandidate]:
        """Fetch known chunks by stable chunk identity."""
