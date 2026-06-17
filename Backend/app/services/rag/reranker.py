"""Deterministic local reranking for RAG candidates."""

from __future__ import annotations

import re
from typing import Any, Optional

from app.models.search_models import DocumentResult, MetadataFilter, SpatialFilter
from app.services.document_asset_service import DocumentAssetService

STANDARD_CODE_QUERY_PATTERN = re.compile(
    r"""
    (?P<code>
        [A-Z]{1,6}\d{0,4}
        (?:\s*[/_]\s*[A-Z])?
        (?:\s*[-_/]?\s*\d+(?:\.\d+)*)+
        \s*[-—]\s*\d{4}
    )
    """,
    re.VERBOSE,
)
COMPACT_STANDARD_CODE_PATTERN = re.compile(r"^[A-Z]{2,10}\d{6,}$")
QUERY_STOP_WORDS = {
    "查一下",
    "查询",
    "检索",
    "有哪些",
    "哪些",
    "相关",
    "标准",
    "规范",
    "一下",
    "请",
    "的",
    "有",
    "吗",
    "和",
    "与",
}


class RagReranker:
    """Rerank candidates with stable local scoring instead of provider calls."""

    def rerank(
        self,
        query: str,
        results: list[DocumentResult],
        top_k: int,
        metadata_filter: Optional[MetadataFilter] = None,
        spatial_filter: Optional[SpatialFilter] = None,
    ) -> list[DocumentResult]:
        query_standard_code = self._extract_standard_code_query(query)
        query_terms = self._extract_query_terms(query)
        scored_results: list[tuple[float, int, DocumentResult]] = []

        for index, result in enumerate(results):
            score = float(result.similarity)
            reasons: list[str] = []

            if query_standard_code:
                match_type = self._get_standard_code_match_type(
                    query_standard_code,
                    self._metadata_value(result.metadata, "standard_code"),
                )
                result.metadata["standard_code_match_type"] = match_type
                if match_type == "exact":
                    score += 1.0
                    reasons.append("standard_code_exact")
                elif match_type == "partial":
                    score += 0.35
                    reasons.append("standard_code_partial")

            term_matches = self._count_query_term_matches(result, query_terms)
            if term_matches:
                score += min(0.4, term_matches * 0.05)
                reasons.append("query_term_match")

            if metadata_filter and result.metadata.get("metadata_filter_match"):
                score += 0.2
                reasons.append("metadata_filter_match")

            if spatial_filter and result.metadata.get("spatial_filter_match"):
                score += 0.2
                reasons.append("spatial_filter_match")

            result.metadata["rerank_score"] = round(score, 6)
            result.metadata["rerank_reasons"] = reasons
            scored_results.append((score, index, result))

        scored_results.sort(key=lambda item: (-item[0], item[1]))
        return [item[2] for item in scored_results[:top_k]]

    def _extract_standard_code_query(self, query: str) -> Optional[str]:
        upper_query = (query or "").upper().strip()
        if not upper_query:
            return None

        match = STANDARD_CODE_QUERY_PATTERN.search(upper_query)
        if match:
            normalized = DocumentAssetService.normalize_standard_code(match.group("code"))
            if normalized:
                return normalized

        compact_query = re.sub(r"[^0-9A-Z]+", "", upper_query)
        if COMPACT_STANDARD_CODE_PATTERN.fullmatch(compact_query) and compact_query[-4:].isdigit():
            normalized = DocumentAssetService.normalize_standard_code(compact_query)
            if normalized:
                return normalized
        return None

    def _get_standard_code_match_type(
        self,
        query_standard_code: Optional[str],
        result_standard_code: Optional[str],
    ) -> str:
        if not query_standard_code or not result_standard_code:
            return "none"
        normalized_result_code = DocumentAssetService.normalize_standard_code(result_standard_code)
        if not normalized_result_code:
            return "none"
        if normalized_result_code == query_standard_code:
            return "exact"
        if query_standard_code in normalized_result_code or normalized_result_code in query_standard_code:
            return "partial"
        return "none"

    def _extract_query_terms(self, query: str) -> list[str]:
        compact_query = re.sub(r"\s+", "", query or "")
        for word in QUERY_STOP_WORDS:
            compact_query = compact_query.replace(word, "")
        terms = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}", compact_query)
        return [term.lower() for term in terms if term and term not in QUERY_STOP_WORDS]

    def _count_query_term_matches(self, result: DocumentResult, query_terms: list[str]) -> int:
        if not query_terms:
            return 0
        haystack = " ".join(
            [
                result.title or "",
                result.content or "",
                " ".join(self._flatten_metadata_values(result.metadata)),
            ]
        ).lower()
        return sum(1 for term in query_terms if term in haystack)

    def _flatten_metadata_values(self, metadata: dict[str, Any]) -> list[str]:
        values: list[str] = []
        for value in metadata.values():
            if isinstance(value, dict):
                values.extend(self._flatten_metadata_values(value))
            elif isinstance(value, (list, tuple, set)):
                values.extend(str(item) for item in value)
            elif value is not None:
                values.append(str(value))
        return values

    def _metadata_value(self, metadata: dict[str, Any], key: str) -> Optional[str]:
        value = metadata.get(key)
        return str(value).strip() if value else None
