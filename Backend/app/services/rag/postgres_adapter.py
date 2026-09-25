"""PostgreSQL/pgvector retrieval adapter.

This module owns retrieval orchestration. Storage-specific query implementations are
migrated here from ``SearchService`` in the same refactor so Agent code depends only
on :mod:`app.services.rag.contracts`.
"""

from __future__ import annotations

from datetime import datetime
import json
import logging
import re
from typing import Any

from sqlalchemy import text

from app.core.database import db_manager
from app.core.llm_config import llm_config
from app.models.search_models import DocumentResult
from app.services.document_asset_service import DocumentAssetService
from app.services.rag.contracts import (
    RetrievalCandidate,
    RetrievalChannelDiagnostic,
    RetrievalDiagnostics,
    RetrievalQuery,
    RetrievalResult,
)
from app.services.rag.filters import RagFilterEngine
from app.services.rag.fusion import rrf_fuse
from app.services.rag.query_planner import QueryPlanner
from app.services.rag.reranker import BaseReranker, RagReranker

logger = logging.getLogger(__name__)

PROVINCE_STANDARD_PREFIXES = {
    "北京市": "DB11",
    "天津市": "DB12",
    "河北省": "DB13",
    "山西省": "DB14",
    "内蒙古自治区": "DB15",
    "辽宁省": "DB21",
    "吉林省": "DB22",
    "黑龙江省": "DB23",
    "上海市": "DB31",
    "江苏省": "DB32",
    "浙江省": "DB33",
    "安徽省": "DB34",
    "福建省": "DB35",
    "江西省": "DB36",
    "山东省": "DB37",
    "河南省": "DB41",
    "湖北省": "DB42",
    "湖南省": "DB43",
    "广东省": "DB44",
    "广西壮族自治区": "DB45",
    "海南省": "DB46",
    "重庆市": "DB50",
    "四川省": "DB51",
    "贵州省": "DB52",
    "云南省": "DB53",
    "西藏自治区": "DB54",
    "陕西省": "DB61",
    "甘肃省": "DB62",
    "青海省": "DB63",
    "宁夏回族自治区": "DB64",
    "新疆维吾尔自治区": "DB65",
}

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
    "？",
    "?",
    "和",
    "与",
}

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


def _region_aliases(name: str) -> list[str]:
    aliases = {
        name,
        name.removesuffix("省"),
        name.removesuffix("市"),
        name.removesuffix("特别行政区"),
        name.removesuffix("壮族自治区"),
        name.removesuffix("回族自治区"),
        name.removesuffix("维吾尔自治区"),
        name.removesuffix("自治区"),
    }
    return [alias for alias in aliases if alias]


class PostgresRetrievalAdapter:
    """Compose exact, keyword and pgvector retrieval behind one storage port."""

    def __init__(self, reranker: BaseReranker | None = None) -> None:
        self.filter_engine = RagFilterEngine()
        self.reranker = reranker or RagReranker()
        self.query_planner = QueryPlanner()

    async def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        plan = self.query_planner.plan(query)
        mode = plan.search_mode
        expanded_top_k = plan.candidate_k

        exact_results: list[DocumentResult] = []
        keyword_results: list[DocumentResult] = []
        vector_results: list[DocumentResult] = []
        embedding_available = False
        channels: list[RetrievalChannelDiagnostic] = []

        if mode in {"hybrid", "keyword", "exact"}:
            try:
                exact_results = await self._exact_standard_code_search(
                    query.query_text,
                    expanded_top_k,
                )
                channels.append(
                    RetrievalChannelDiagnostic(channel="exact", state="succeeded")
                )
            except Exception as exc:
                logger.warning("Exact retrieval unavailable: %s", exc, exc_info=True)
                channels.append(
                    RetrievalChannelDiagnostic(
                        channel="exact",
                        state="unavailable",
                        detail=type(exc).__name__,
                    )
                )

        if mode in {"hybrid", "keyword"}:
            try:
                keyword_results = await self._keyword_search(
                    query.query_text,
                    expanded_top_k,
                )
                channels.append(
                    RetrievalChannelDiagnostic(channel="keyword", state="succeeded")
                )
            except Exception as exc:
                logger.warning("Keyword retrieval unavailable: %s", exc, exc_info=True)
                channels.append(
                    RetrievalChannelDiagnostic(
                        channel="keyword",
                        state="unavailable",
                        detail=type(exc).__name__,
                    )
                )

        if mode in {"hybrid", "semantic"}:
            try:
                query_embedding = await self._get_query_embedding(query.query_text)
            except Exception as exc:
                logger.warning(
                    "Embedding unavailable; continuing with exact/keyword retrieval: %s",
                    exc,
                )
                query_embedding = []
                channels.append(
                    RetrievalChannelDiagnostic(
                        channel="vector",
                        state="unavailable",
                        detail=type(exc).__name__,
                    )
                )

            if query_embedding:
                embedding_available = True
                try:
                    vector_results = await self._vector_search(
                        query_embedding=query_embedding,
                        top_k=expanded_top_k,
                        threshold=query.threshold,
                    )
                    channels.append(
                        RetrievalChannelDiagnostic(channel="vector", state="succeeded")
                    )
                except Exception as exc:
                    logger.warning("Vector retrieval unavailable: %s", exc, exc_info=True)
                    channels.append(
                        RetrievalChannelDiagnostic(
                            channel="vector",
                            state="unavailable",
                            detail=type(exc).__name__,
                        )
                    )

        candidate_results = rrf_fuse(
            [exact_results, keyword_results, vector_results],
            rrf_k=60,
            top_k=plan.candidate_k,
            weights=[
                plan.channel_weights.get("exact", 1.5),
                plan.channel_weights.get("keyword", 1.0),
                plan.channel_weights.get("vector", 1.0),
            ],
            channel_labels=["exact", "keyword", "vector"],
        )

        if query.spatial_filter:
            candidate_results = await self.filter_engine.apply_spatial_filter(
                candidate_results,
                query.spatial_filter,
            )

        if query.metadata_filter:
            candidate_results = self.filter_engine.apply_metadata_filter(
                candidate_results,
                query.metadata_filter,
            )

        if query.use_rerank:
            final_results = self.reranker.rerank(
                plan.query_text,
                candidate_results,
                top_k=plan.top_k,
                metadata_filter=query.metadata_filter,
                spatial_filter=query.spatial_filter,
            )
        else:
            final_results = candidate_results[: plan.top_k]

        return RetrievalResult(
            candidates=tuple(
                RetrievalCandidate.from_document_result(item) for item in final_results
            ),
            embedding_available=embedding_available,
            diagnostics=RetrievalDiagnostics(
                exact_count=len(exact_results),
                keyword_count=len(keyword_results),
                vector_count=len(vector_results),
                channels=tuple(channels),
            ),
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

    def _merge_source_results(
        self,
        primary_results: list[DocumentResult],
        secondary_results: list[DocumentResult],
        top_k: int,
    ) -> list[DocumentResult]:
        merged: dict[str, DocumentResult] = {}
        for result in [*primary_results, *secondary_results]:
            key = str(result.metadata.get("document_name") or result.title or result.id)
            existing = merged.get(key)
            if existing is None or result.similarity > existing.similarity:
                merged[key] = result
        return sorted(
            merged.values(),
            key=lambda item: item.similarity,
            reverse=True,
        )[:top_k]

    def _extract_keyword_terms(self, query: str) -> list[str]:
        compact_query = re.sub(r"\s+", "", query)
        terms: list[str] = []

        for region_name, standard_prefix in PROVINCE_STANDARD_PREFIXES.items():
            matched_aliases = [
                alias for alias in _region_aliases(region_name) if alias in compact_query
            ]
            if matched_aliases:
                terms.extend([*matched_aliases, standard_prefix])

        cleaned = compact_query
        for word in QUERY_STOP_WORDS:
            cleaned = cleaned.replace(word, "")

        for token in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}", cleaned):
            if token and token not in QUERY_STOP_WORDS:
                terms.append(token)

        spaced_cleaned = query
        for word in QUERY_STOP_WORDS:
            spaced_cleaned = spaced_cleaned.replace(word, " ")

        for token in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}", spaced_cleaned):
            if token and token not in QUERY_STOP_WORDS:
                terms.append(token)

        deduped_terms: list[str] = []
        for term in terms:
            if term not in deduped_terms:
                deduped_terms.append(term)
        return deduped_terms[:6]

    @staticmethod
    def _infer_file_type(document_name: str | None) -> str:
        if not document_name or "." not in document_name:
            return "unknown"
        suffix = document_name.rsplit(".", 1)[-1].strip().lower()
        return suffix or "unknown"

    def _build_policy_chunk_result(
        self,
        row: Any,
        similarity: float,
        match_type: str,
        extra_metadata: dict[str, Any] | None = None,
    ) -> DocumentResult:
        document_name = row.document_name
        metadata: dict[str, Any] = {
            "standard_code": row.standard_code,
            "document_name": document_name,
            "document_type": "标准规范",
            "match_type": match_type,
        }
        for key in (
            "category",
            "keyword",
            "chinese_name",
            "english_name",
            "release_date",
            "implement_date",
            "standard_status",
            "release_unit",
            "charge_unit",
            "draft_unit",
            "application_scope",
        ):
            value = getattr(row, key, None)
            if value is not None:
                metadata[key] = value
        if metadata.get("keyword"):
            metadata["keywords"] = metadata["keyword"]
        if metadata.get("release_unit") and not metadata.get("source"):
            metadata["source"] = metadata["release_unit"]
        if extra_metadata:
            metadata.update(extra_metadata)

        return DocumentResult(
            id=str(row.id),
            title=document_name,
            content=row.content[:500] if row.content else "",
            similarity=float(similarity),
            metadata=metadata,
            spatial_info=None,
            file_type=self._infer_file_type(document_name),
            file_size=0,
            upload_time=datetime.now(),
            source_url=None,
        )

    def _build_uploaded_chunk_result(
        self,
        row: Any,
        similarity: float,
        match_type: str,
    ) -> DocumentResult:
        metadata = self._coerce_json_dict(getattr(row, "metadata", None))
        metadata.update(
            {
                "chunk_id": str(row.chunk_id),
                "document_id": str(row.document_id),
                "document_name": row.title or row.filename,
                "original_filename": row.filename,
                "document_type": "上传文档",
                "match_type": match_type,
            }
        )
        spatial_info = self._coerce_json_dict(
            getattr(row, "spatial_metadata", None)
        ) or None
        download_url = getattr(row, "download_url", None)
        return DocumentResult(
            id=str(row.document_id),
            title=row.title or row.filename,
            content=row.content[:500] if row.content else "",
            similarity=float(similarity),
            metadata=metadata,
            spatial_info=spatial_info,
            file_type=row.file_type or self._infer_file_type(row.filename),
            file_size=int(row.file_size or 0),
            upload_time=row.created_at or datetime.now(),
            source_url=download_url,
            download_available=bool(download_url),
            download_url=download_url,
        )

    @staticmethod
    def _coerce_json_dict(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}

    def _extract_standard_code_query(self, query: str) -> str | None:
        upper_query = (query or "").upper().strip()
        if not upper_query:
            return None
        match = STANDARD_CODE_QUERY_PATTERN.search(upper_query)
        if match:
            normalized = DocumentAssetService.normalize_standard_code(match.group("code"))
            if normalized:
                return normalized
        compact_query = re.sub(r"[^0-9A-Z]+", "", upper_query)
        if (
            COMPACT_STANDARD_CODE_PATTERN.fullmatch(compact_query)
            and compact_query[-4:].isdigit()
        ):
            normalized = DocumentAssetService.normalize_standard_code(compact_query)
            if normalized:
                return normalized
        return None

    async def _rerank_results(
        self,
        query: str,
        results: list[DocumentResult],
        top_k: int,
    ) -> list[DocumentResult]:
        if not results:
            return results
        return self.reranker.rerank(query, results, top_k=top_k)

    async def _exact_standard_code_search(
        self,
        query: str,
        top_k: int,
    ) -> list[DocumentResult]:
        query_standard_code = self._extract_standard_code_query(query)
        if not query_standard_code or not db_manager.postgres_sessionmaker:
            return []

        sql = text(
            """
            SELECT
                id, standard_code, document_name, content,
                category, keyword, chinese_name, english_name,
                release_date, implement_date, standard_status,
                release_unit, charge_unit, draft_unit, application_scope
            FROM policy_chunks
            WHERE REGEXP_REPLACE(LOWER(COALESCE(standard_code, '')), '[^a-z0-9]+', '', 'g') = :standard_code
            ORDER BY document_name, id
            LIMIT :limit
            """
        )
        async with db_manager.get_postgres_session() as session:
            result = await session.execute(
                sql,
                {"standard_code": query_standard_code, "limit": top_k},
            )
            rows = result.fetchall()
        return [
            self._build_policy_chunk_result(
                row,
                similarity=1.0,
                match_type="standard_code_exact",
                extra_metadata={"standard_code_match_type": "exact"},
            )
            for row in rows
        ]

    async def _keyword_search(
        self,
        query: str,
        top_k: int,
    ) -> list[DocumentResult]:
        terms = self._extract_keyword_terms(query)
        if not terms or not db_manager.postgres_sessionmaker:
            return []
        try:
            conditions: list[str] = []
            params: dict[str, Any] = {"limit": top_k}
            score_parts: list[str] = []
            for index, term in enumerate(terms):
                param_name = f"kw_{index}"
                params[param_name] = f"%{term}%"
                conditions.append(
                    f"(standard_code ILIKE :{param_name} OR document_name ILIKE :{param_name} OR content ILIKE :{param_name})"
                )
                score_parts.append(
                    f"(CASE WHEN standard_code ILIKE :{param_name} THEN 0.20 ELSE 0 END)"
                    f" + (CASE WHEN document_name ILIKE :{param_name} THEN 0.12 ELSE 0 END)"
                    f" + (CASE WHEN content ILIKE :{param_name} THEN 0.04 ELSE 0 END)"
                )
            sql = text(
                f"""
                WITH matched AS (
                    SELECT DISTINCT ON (document_name)
                        id, standard_code, document_name, content,
                        category, keyword, chinese_name, english_name,
                        release_date, implement_date, standard_status,
                        release_unit, charge_unit, draft_unit, application_scope,
                        LEAST(0.95, 0.55 + ({' + '.join(score_parts)})) AS similarity
                    FROM policy_chunks
                    WHERE {' OR '.join(conditions)}
                    ORDER BY document_name, similarity DESC, id
                )
                SELECT * FROM matched
                ORDER BY similarity DESC, document_name
                LIMIT :limit
                """
            )
            async with db_manager.get_postgres_session() as session:
                result = await session.execute(sql, params)
                rows = result.fetchall()
            policy_results = [
                self._build_policy_chunk_result(
                    row,
                    similarity=float(row.similarity),
                    match_type="keyword",
                )
                for row in rows
            ]
            try:
                uploaded_results = await self._uploaded_keyword_search(
                    query, top_k, terms
                )
            except RuntimeError as exc:
                logger.warning(
                    "Uploaded-document keyword retrieval unavailable; "
                    "continuing with policy chunks: %s",
                    exc.__cause__ or exc,
                )
                uploaded_results = []
            return self._merge_source_results(policy_results, uploaded_results, top_k)
        except Exception as exc:
            raise RuntimeError("keyword retrieval unavailable") from exc

    async def _uploaded_keyword_search(
        self,
        query: str,
        top_k: int,
        terms: list[str] | None = None,
    ) -> list[DocumentResult]:
        del query
        terms = terms or []
        if not terms or not db_manager.postgres_sessionmaker:
            return []
        try:
            conditions: list[str] = []
            params: dict[str, Any] = {"limit": top_k}
            score_parts: list[str] = []
            for index, term in enumerate(terms):
                param_name = f"uploaded_kw_{index}"
                params[param_name] = f"%{term}%"
                conditions.append(
                    f"(d.title ILIKE :{param_name} OR d.filename ILIKE :{param_name} OR c.content ILIKE :{param_name})"
                )
                score_parts.append(
                    f"(CASE WHEN d.title ILIKE :{param_name} THEN 0.18 ELSE 0 END)"
                    f" + (CASE WHEN d.filename ILIKE :{param_name} THEN 0.12 ELSE 0 END)"
                    f" + (CASE WHEN c.content ILIKE :{param_name} THEN 0.05 ELSE 0 END)"
                )
            sql = text(
                f"""
                WITH matched AS (
                    SELECT DISTINCT ON (d.id)
                        c.id::text AS chunk_id,
                        d.id::text AS document_id,
                        d.title, d.filename, d.file_type, d.file_size, d.created_at,
                        d.metadata, d.spatial_metadata, v.access_url AS download_url,
                        c.content,
                        LEAST(0.95, 0.52 + ({' + '.join(score_parts)})) AS similarity
                    FROM document_chunks c
                    JOIN documents d ON d.id = c.document_id
                    LEFT JOIN document_versions v ON v.id = d.current_version_id
                    WHERE d.deleted_at IS NULL
                      AND d.index_status = 'indexed'
                      AND ({' OR '.join(conditions)})
                    ORDER BY d.id, similarity DESC, c.chunk_index
                )
                SELECT * FROM matched
                ORDER BY similarity DESC, title
                LIMIT :limit
                """
            )
            async with db_manager.get_postgres_session() as session:
                result = await session.execute(sql, params)
                rows = result.fetchall()
            return [
                self._build_uploaded_chunk_result(
                    row,
                    similarity=float(row.similarity),
                    match_type="uploaded_keyword",
                )
                for row in rows
            ]
        except Exception as exc:
            raise RuntimeError("uploaded-document keyword retrieval unavailable") from exc

    async def _get_query_embedding(self, query: str) -> list[float]:
        embeddings = await llm_config.get_embeddings([query])
        return embeddings[0] if embeddings else []

    async def _get_document_embedding(self, doc_id: str) -> list[float] | None:
        # Existing GeoRAG has no canonical document-level embedding record yet.
        # Preserve the legacy endpoint behavior until a real storage contract exists.
        del doc_id
        return None

    async def find_similar_documents(
        self,
        doc_id: str,
        top_k: int = 5,
    ) -> list[DocumentResult]:
        document_embedding = await self._get_document_embedding(doc_id)
        if not document_embedding:
            return []
        results = await self._vector_search(
            query_embedding=document_embedding,
            top_k=top_k + 1,
            exclude_doc_id=doc_id,
        )
        return results[:top_k]

    async def spatial_search(
        self,
        spatial_query: str,
        top_k: int,
    ) -> list[DocumentResult]:
        return await self.filter_engine.spatial_search(spatial_query, top_k)

    async def _vector_search(
        self,
        query_embedding: list[float],
        top_k: int,
        threshold: float = 0.7,
        exclude_doc_id: str | None = None,
    ) -> list[DocumentResult]:
        if not db_manager.postgres_sessionmaker or not query_embedding:
            return []
        try:
            embedding_str = str(query_embedding)
            sql = """
                SELECT
                    id, standard_code, document_name, content,
                    category, keyword, chinese_name, english_name,
                    release_date, implement_date, standard_status,
                    release_unit, charge_unit, draft_unit, application_scope,
                    1 - (embedding <=> CAST(:embedding_str AS vector)) AS similarity
                FROM policy_chunks
            """
            params: dict[str, Any] = {
                "embedding_str": embedding_str,
                "limit": top_k,
            }
            if exclude_doc_id:
                sql += " WHERE id != :exclude_doc_id "
                params["exclude_doc_id"] = exclude_doc_id
            sql += " ORDER BY embedding <=> CAST(:embedding_str AS vector) LIMIT :limit"
            async with db_manager.get_postgres_session() as session:
                result = await session.execute(text(sql), params)
                rows = result.fetchall()

            policy_results = [
                self._build_policy_chunk_result(
                    row,
                    similarity=float(row.similarity),
                    match_type="vector",
                )
                for row in rows
                if float(row.similarity) >= threshold
            ]
            try:
                uploaded_results = await self._uploaded_vector_search(
                    query_embedding=query_embedding,
                    top_k=top_k,
                    threshold=threshold,
                    exclude_doc_id=exclude_doc_id,
                )
            except RuntimeError as exc:
                logger.warning(
                    "Uploaded-document vector retrieval unavailable; "
                    "continuing with policy chunks: %s",
                    exc.__cause__ or exc,
                )
                uploaded_results = []
            return self._merge_source_results(policy_results, uploaded_results, top_k)
        except Exception as exc:
            raise RuntimeError("vector retrieval unavailable") from exc

    async def _uploaded_vector_search(
        self,
        query_embedding: list[float],
        top_k: int,
        threshold: float = 0.7,
        exclude_doc_id: str | None = None,
    ) -> list[DocumentResult]:
        if not db_manager.postgres_sessionmaker or not query_embedding:
            return []
        embedding_str = str(query_embedding)
        params: dict[str, Any] = {"embedding_str": embedding_str, "limit": top_k}
        exclude_clause = ""
        if exclude_doc_id:
            exclude_clause = "AND d.id::text != :exclude_doc_id"
            params["exclude_doc_id"] = str(exclude_doc_id)
        sql = text(
            f"""
            SELECT
                c.id::text AS chunk_id,
                d.id::text AS document_id,
                d.title, d.filename, d.file_type, d.file_size, d.created_at,
                d.metadata, d.spatial_metadata, v.access_url AS download_url,
                c.content,
                1 - (
                    CAST(c.embedding AS halfvec(2048)) <=> CAST(:embedding_str AS halfvec(2048))
                ) AS similarity
            FROM document_chunks c
            JOIN documents d ON d.id = c.document_id
            LEFT JOIN document_versions v ON v.id = d.current_version_id
            WHERE d.deleted_at IS NULL
              AND d.index_status = 'indexed'
              AND c.embedding IS NOT NULL
              {exclude_clause}
            ORDER BY CAST(c.embedding AS halfvec(2048)) <=> CAST(:embedding_str AS halfvec(2048))
            LIMIT :limit
            """
        )
        try:
            async with db_manager.get_postgres_session() as session:
                result = await session.execute(sql, params)
                rows = result.fetchall()
            return [
                self._build_uploaded_chunk_result(
                    row,
                    similarity=float(row.similarity),
                    match_type="uploaded_vector",
                )
                for row in rows
                if float(row.similarity) >= threshold
            ]
        except Exception as exc:
            raise RuntimeError("uploaded-document vector retrieval unavailable") from exc

    async def fetch_chunks(self, chunk_ids: list[str]) -> list[RetrievalCandidate]:
        normalized_ids = [str(chunk_id) for chunk_id in chunk_ids if str(chunk_id).strip()]
        if not normalized_ids or not db_manager.postgres_sessionmaker:
            return []

        # Uploaded document chunks carry UUID-like stable chunk ids. Policy chunks use
        # integer ids. Query them independently so neither storage model is disguised.
        candidates: list[RetrievalCandidate] = []
        numeric_ids = [chunk_id for chunk_id in normalized_ids if chunk_id.isdigit()]
        if numeric_ids:
            sql = text(
                """
                SELECT
                    id, standard_code, document_name, content,
                    category, keyword, chinese_name, english_name,
                    release_date, implement_date, standard_status,
                    release_unit, charge_unit, draft_unit, application_scope
                FROM policy_chunks
                WHERE id = ANY(:chunk_ids)
                """
            )
            async with db_manager.get_postgres_session() as session:
                result = await session.execute(sql, {"chunk_ids": [int(v) for v in numeric_ids]})
                rows = result.fetchall()
            candidates.extend(
                RetrievalCandidate.from_document_result(
                    self._build_policy_chunk_result(
                        row,
                        similarity=1.0,
                        match_type="fetch_chunk",
                    )
                )
                for row in rows
            )

        uploaded_ids = [chunk_id for chunk_id in normalized_ids if not chunk_id.isdigit()]
        if uploaded_ids:
            sql = text(
                """
                SELECT
                    c.id::text AS chunk_id,
                    d.id::text AS document_id,
                    d.title, d.filename, d.file_type, d.file_size, d.created_at,
                    d.metadata, d.spatial_metadata, v.access_url AS download_url,
                    c.content
                FROM document_chunks c
                JOIN documents d ON d.id = c.document_id
                LEFT JOIN document_versions v ON v.id = d.current_version_id
                WHERE c.id::text = ANY(:chunk_ids)
                  AND d.deleted_at IS NULL
                """
            )
            async with db_manager.get_postgres_session() as session:
                result = await session.execute(sql, {"chunk_ids": uploaded_ids})
                rows = result.fetchall()
            candidates.extend(
                RetrievalCandidate.from_document_result(
                    self._build_uploaded_chunk_result(
                        row,
                        similarity=1.0,
                        match_type="fetch_chunk",
                    )
                )
                for row in rows
            )
        by_id = {candidate.chunk_id: candidate for candidate in candidates}
        return [by_id[chunk_id] for chunk_id in normalized_ids if chunk_id in by_id]
