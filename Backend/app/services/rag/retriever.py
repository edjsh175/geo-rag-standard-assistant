"""Composable retrieval orchestration for exact, keyword, and vector search."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import logging

from app.models.search_models import DocumentResult
from app.services.rag.types import RetrievalResultSet, SearchContext

logger = logging.getLogger(__name__)

EmbeddingProvider = Callable[[str], Awaitable[list[float]]]
ExactSearch = Callable[[str, int], Awaitable[list[DocumentResult]]]
KeywordSearch = Callable[[str, int], Awaitable[list[DocumentResult]]]
VectorSearch = Callable[..., Awaitable[list[DocumentResult]]]


class RagRetriever:
    """Run independent retrieval paths with graceful embedding degradation."""

    def __init__(
        self,
        get_query_embedding: EmbeddingProvider,
        exact_standard_code_search: ExactSearch,
        keyword_search: KeywordSearch,
        vector_search: VectorSearch,
    ) -> None:
        self._get_query_embedding = get_query_embedding
        self._exact_standard_code_search = exact_standard_code_search
        self._keyword_search = keyword_search
        self._vector_search = vector_search

    async def retrieve(self, context: SearchContext) -> RetrievalResultSet:
        mode = context.mode
        expanded_top_k = max(context.top_k * 2, context.top_k)

        exact_results: list[DocumentResult] = []
        keyword_results: list[DocumentResult] = []
        vector_results: list[DocumentResult] = []
        embedding_available = False

        if mode in {"hybrid", "keyword", "exact"}:
            exact_results = await self._exact_standard_code_search(
                context.query,
                expanded_top_k,
            )

        if mode in {"hybrid", "keyword"}:
            keyword_results = await self._keyword_search(
                context.query,
                expanded_top_k,
            )

        if mode in {"hybrid", "semantic"}:
            try:
                query_embedding = await self._get_query_embedding(context.query)
            except Exception as exc:
                logger.warning(
                    "Embedding unavailable; continuing with exact/keyword retrieval: %s",
                    exc,
                )
                query_embedding = []

            if query_embedding:
                embedding_available = True
                vector_results = await self._vector_search(
                    query_embedding=query_embedding,
                    top_k=expanded_top_k,
                    threshold=context.threshold,
                )

        merged = self._merge_and_dedupe_results(
            exact_results,
            keyword_results,
            vector_results,
            top_k=max(context.top_k * 3, context.top_k),
        )
        return RetrievalResultSet(
            results=merged,
            embedding_available=embedding_available,
            exact_count=len(exact_results),
            keyword_count=len(keyword_results),
            vector_count=len(vector_results),
        )

    def _merge_and_dedupe_results(
        self,
        *result_groups: list[DocumentResult],
        top_k: int,
    ) -> list[DocumentResult]:
        merged: dict[str, DocumentResult] = {}
        ordered_keys: list[str] = []

        for result in [item for group in result_groups for item in group]:
            key = str(result.metadata.get("document_name") or result.title or result.id)
            existing = merged.get(key)
            if existing is None:
                ordered_keys.append(key)
                merged[key] = result
            elif result.similarity > existing.similarity:
                merged[key] = result

        return [merged[key] for key in ordered_keys][:top_k]
