"""
智能检索服务
"""

import logging
import inspect
import re
import string
from typing import List, Optional, Dict, Any
from datetime import datetime

from app.core.llm_config import llm_config
from app.core.database import db_manager
from app.services.document_asset_service import DocumentAssetService
from sqlalchemy import text
from app.models.search_models import (
    DocumentResult, FollowUpContext, MetadataFilter, SpatialFilter
)
from app.services.rag.filters import RagFilterEngine
from app.services.rag.reranker import RagReranker
from app.services.rag.retriever import RagRetriever
from app.services.rag.search_logger import RagSearchLogger
from app.services.rag.types import SearchContext

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
    "查一下", "查询", "检索", "有哪些", "哪些", "相关", "标准", "规范",
    "一下", "请", "的", "有", "吗", "？", "?", "和", "与",
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
DOCUMENT_FOLLOW_UP_SUMMARY_HINTS = (
    "主要内容",
    "讲了什么",
    "主要讲",
    "核心要求",
    "主要要求",
    "适用范围",
    "总结",
    "概述",
    "摘要",
    "重点",
    "说了什么",
)


COMMON_GREETING_QUERIES = {
    "你好", "您好", "hello", "hi", "hey", "嗨",
    "早上好", "下午好", "晚上好", "晚安",
    "在吗", "有人吗", "你好呀", "您好呀",
    "hello there", "hi there", "哈喽", "哈啰", "嘿",
}

DIALOG_MANAGEMENT_HINTS = (
    "上一个问题",
    "上一条",
    "上一轮",
    "刚才的问题",
    "刚才的回答",
    "重复一下",
    "总结一下我们刚才",
    "我们刚才在讨论什么",
    "我刚刚问了什么",
)

CASUAL_CHAT_HINTS = (
    "闲聊",
    "聊天",
    "聊聊",
    "随便聊",
    "你是谁",
    "介绍一下你自己",
    "你能做什么",
    "你会什么",
    "讲个笑话",
    "今天天气",
    "天气怎么样",
    "现在几点",
)

PLACEHOLDER_SUMMARY_VALUES = {
    "",
    "无",
    "暂无",
    "未提供",
    "none",
    "null",
    "n/a",
    "-",
    "/",
}


def _normalize_query_text(query: str) -> str:
    cleaned_query = query.strip().lower()
    punct_set = set("。，！？；：、“”‘’、（）【】《》,.!?;:\"'`~!@#$%^&*()-_=+[]{}|\\/<>")
    for punct in punct_set:
        cleaned_query = cleaned_query.replace(punct, "")
    return cleaned_query


def _region_aliases(name: str) -> List[str]:
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


class SearchService:
    """智能检索服务

    企业级韧性装甲特性：
    1. Token爆炸防御：自动截断历史记录，防止上下文窗口溢出
    2. 意图识别：区分搜索、闲聊、对话管理等不同意图
    3. 混合意图支持：支持在单一查询中同时处理检索和历史查询

    未来优化方向：
    - Agent工具调用架构：从硬编码意图路由转向大模型自主决策的工具调用
    - 会话状态持久化：使用Redis/PostgreSQL存储会话历史，实现高可用
    - 上下文优化：动态调整滑动窗口大小，平衡记忆深度和Token消耗
    """

    def __init__(self):
        self.vector_service = None  # 将在后面初始化
        self.spatial_service = None  # 将在后面初始化
        self.postgres_available = False
        self.rag_filter_engine = RagFilterEngine()
        self.rag_reranker = RagReranker()
        self.rag_search_logger = RagSearchLogger()

        # 检查数据库连接状态
        self._check_database_status()

    def _get_rag_filter_engine(self) -> RagFilterEngine:
        if not hasattr(self, "rag_filter_engine"):
            self.rag_filter_engine = RagFilterEngine()
        return self.rag_filter_engine

    def _get_rag_reranker(self) -> RagReranker:
        if not hasattr(self, "rag_reranker"):
            self.rag_reranker = RagReranker()
        return self.rag_reranker

    def _get_rag_search_logger(self) -> RagSearchLogger:
        if not hasattr(self, "rag_search_logger"):
            self.rag_search_logger = RagSearchLogger()
        return self.rag_search_logger

    def _get_rag_retriever(self) -> RagRetriever:
        return RagRetriever(
            get_query_embedding=self._get_query_embedding,
            exact_standard_code_search=self._exact_standard_code_search,
            keyword_search=self._keyword_search,
            vector_search=self._vector_search,
        )

    def _check_database_status(self):
        """检查数据库连接状态"""
        try:
            # 检查PostgreSQL连接是否已初始化
            if hasattr(db_manager, 'postgres_sessionmaker') and db_manager.postgres_sessionmaker:
                self.postgres_available = True
                logger.info("PostgreSQL 连接可用")
            else:
                logger.warning("PostgreSQL 连接未初始化，向量搜索功能将受限")
                logger.warning("要启用完整功能，请确保：")
                logger.warning("1. PostgreSQL 服务正在运行")
                logger.warning("2. 数据库 'geoai_db' 已创建")
                logger.warning("3. .env 中的 DATABASE_URL 配置正确")
                logger.warning("4. PostgreSQL 已安装 pgvector 和 postgis 扩展")
        except Exception as e:
            logger.error(f"检查数据库状态失败: {e}")

    async def search(
        self,
        query: str,
        top_k: int = 10,
        threshold: float = 0.7,
        spatial_filter: Optional[SpatialFilter] = None,
        metadata_filter: Optional[MetadataFilter] = None,
        search_mode: str = "hybrid",
        use_rerank: bool = True,
    ) -> List[DocumentResult]:
        """
        智能检索文档

        Args:
            query: 查询语句
            top_k: 返回结果数量
            threshold: 相似度阈值
            spatial_filter: 空间过滤器
            metadata_filter: 元数据过滤器

        Returns:
            检索结果列表
        """
        try:
            start_time = datetime.now()
            logger.info(f"开始搜索: query='{query}', top_k={top_k}, threshold={threshold}")

            # 防御性检查：如果查询是明显的闲聊/问候语，直接返回空结果
            # 这是最后一道防线，防止路由层短路失效时仍然执行向量检索
            common_greetings = {
                "你好", "您好", "hello", "hi", "hey", "嗨",
                "早上好", "下午好", "晚上好", "晚安",
                "在吗", "在吗？", "有人吗", "有人吗？", "你好啊",
                "您好啊", "hello there", "hi there",
                "喂", "喂？", "哈喽", "嘿"
            }
            cleaned_query = query.strip().lower()
            # 移除常见标点符号
            import string
            punct_set = set("。，！？；：“”‘’、（）【】《》" + string.punctuation)
            for punct in punct_set:
                cleaned_query = cleaned_query.replace(punct, '')

            if cleaned_query in common_greetings:
                logger.error(
                    f"安全防护触发：闲聊查询 '{query}' 试图执行向量检索！"
                    f"这表明路由层意图短路可能失效，请立即检查。"
                )
                # 绝对禁止执行向量检索，直接返回空结果
                return []

            context = SearchContext(
                query=query,
                top_k=top_k,
                threshold=threshold,
                search_mode=search_mode,
                use_rerank=use_rerank,
                spatial_filter=spatial_filter,
                metadata_filter=metadata_filter,
            )

            retrieved = await self._get_rag_retriever().retrieve(context)
            candidate_results = retrieved.results

            # 3. 应用空间过滤器
            if spatial_filter:
                candidate_results = await self._apply_spatial_filter(
                    results=candidate_results,
                    spatial_filter=spatial_filter
                )

            # 4. 应用元数据过滤器
            if metadata_filter:
                candidate_results = await self._apply_metadata_filter(
                    results=candidate_results,
                    metadata_filter=metadata_filter
                )

            # 5. 重排序和截断
            if use_rerank:
                final_results = await self._rerank_results(
                    query=query,
                    results=candidate_results,
                    top_k=top_k,
                    metadata_filter=metadata_filter,
                    spatial_filter=spatial_filter,
                )
            else:
                final_results = candidate_results[:top_k]

            # 6. 记录搜索日志
            log_result = self._log_search(
                query=query,
                results_count=len(final_results),
                search_time=(datetime.now() - start_time).total_seconds(),
                search_mode=context.mode,
                top_k=top_k,
                threshold=threshold,
                metadata_filter=metadata_filter,
                spatial_filter=spatial_filter,
                used_rerank=use_rerank,
                embedding_available=retrieved.embedding_available,
            )
            if inspect.isawaitable(log_result):
                await log_result

            return final_results

        except Exception as e:
            logger.error(f"检索失败: {e}", exc_info=True)
            raise

    def _extract_keyword_terms(self, query: str) -> List[str]:
        """从自然语言查询中提取适合数据库 LIKE 检索的关键词。"""
        compact_query = re.sub(r"\s+", "", query)
        terms: List[str] = []

        for region_name, standard_prefix in PROVINCE_STANDARD_PREFIXES.items():
            matched_aliases = [alias for alias in _region_aliases(region_name) if alias in compact_query]
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

        deduped_terms: List[str] = []
        for term in terms:
            if term not in deduped_terms:
                deduped_terms.append(term)
        return deduped_terms[:6]

    def _infer_file_type(self, document_name: Optional[str]) -> str:
        if not document_name or "." not in document_name:
            return "unknown"
        suffix = document_name.rsplit(".", 1)[-1].strip().lower()
        return suffix or "unknown"

    def _build_policy_chunk_result(
        self,
        row,
        similarity: float,
        match_type: str,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> DocumentResult:
        document_name = row.document_name
        metadata: Dict[str, Any] = {
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

        file_type = self._infer_file_type(document_name)
        return DocumentResult(
            id=row.id,
            title=document_name,
            content=row.content[:500] if row.content else "",
            similarity=float(similarity),
            metadata=metadata,
            spatial_info=None,
            file_type=file_type,
            file_size=0,
            upload_time=datetime.now(),
            source_url=None,
        )

    async def _keyword_search(self, query: str, top_k: int) -> List[DocumentResult]:
        """关键词兜底检索，用于地区编号和明确主题词。"""
        terms = self._extract_keyword_terms(query)
        if not terms or not db_manager.postgres_sessionmaker:
            return []

        try:
            conditions = []
            params: Dict[str, Any] = {"limit": top_k}
            score_parts = []

            for i, term in enumerate(terms):
                param_name = f"kw_{i}"
                params[param_name] = f"%{term}%"
                conditions.append(
                    f"(standard_code ILIKE :{param_name} OR document_name ILIKE :{param_name} OR content ILIKE :{param_name})"
                )
                score_parts.append(
                    f"(CASE WHEN standard_code ILIKE :{param_name} THEN 0.20 ELSE 0 END)"
                    f" + (CASE WHEN document_name ILIKE :{param_name} THEN 0.12 ELSE 0 END)"
                    f" + (CASE WHEN content ILIKE :{param_name} THEN 0.04 ELSE 0 END)"
                )

            sql = f"""
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
                SELECT
                    id, standard_code, document_name, content,
                    category, keyword, chinese_name, english_name,
                    release_date, implement_date, standard_status,
                    release_unit, charge_unit, draft_unit, application_scope,
                    similarity
                FROM matched
                ORDER BY similarity DESC, document_name
                LIMIT :limit
            """

            async with db_manager.get_postgres_session() as session:
                result = await session.execute(text(sql), params)
                rows = result.fetchall()

            keyword_results = []
            for row in rows:
                keyword_results.append(
                    self._build_policy_chunk_result(
                        row,
                        similarity=float(row.similarity),
                        match_type="keyword",
                    )
                )

            logger.info("关键词检索命中 %s 条: query='%s', terms=%s", len(keyword_results), query, terms)
            return keyword_results
        except Exception as e:
            logger.warning("关键词检索失败，回退到向量检索结果: %s", e, exc_info=True)
            return []

    def _merge_and_dedupe_results(
        self,
        primary_results: List[DocumentResult],
        secondary_results: List[DocumentResult],
        top_k: int,
    ) -> List[DocumentResult]:
        """合并多路检索结果，并按文档名去重。"""
        merged: Dict[str, DocumentResult] = {}

        for result in [*primary_results, *secondary_results]:
            key = result.metadata.get("document_name") or result.title or result.id
            existing = merged.get(key)
            if not existing or result.similarity > existing.similarity:
                merged[key] = result

        return sorted(merged.values(), key=lambda item: item.similarity, reverse=True)[:top_k]

    def _extract_standard_code_query(self, query: str) -> Optional[str]:
        """Extract and normalize a standard-code-like query when present."""
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

        if (
            query_standard_code in normalized_result_code
            or normalized_result_code in query_standard_code
        ):
            return "partial"

        return "none"

    def _prioritize_exact_standard_code_matches(
        self,
        query: str,
        results: List[DocumentResult],
    ) -> List[DocumentResult]:
        query_standard_code = self._extract_standard_code_query(query)
        if not query_standard_code:
            return results

        exact_matches: List[DocumentResult] = []
        other_results: List[DocumentResult] = []

        for result in results:
            standard_code = result.metadata.get("standard_code")
            match_type = self._get_standard_code_match_type(
                query_standard_code,
                str(standard_code).strip() if standard_code else None,
            )
            result.metadata["standard_code_match_type"] = match_type

            if match_type == "exact":
                exact_matches.append(result)
            else:
                other_results.append(result)

        if not exact_matches:
            return results

        logger.info(
            "Prioritized %s exact standard-code matches for query=%r",
            len(exact_matches),
            query,
        )
        return [*exact_matches, *other_results]

    async def _exact_standard_code_search(
        self,
        query: str,
        top_k: int,
    ) -> List[DocumentResult]:
        query_standard_code = self._extract_standard_code_query(query)
        if not query_standard_code or not db_manager.postgres_sessionmaker:
            return []

        sql = text(
            """
            SELECT
                id,
                standard_code,
                document_name,
                content,
                category,
                keyword,
                chinese_name,
                english_name,
                release_date,
                implement_date,
                standard_status,
                release_unit,
                charge_unit,
                draft_unit,
                application_scope
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

        exact_results = [
            self._build_policy_chunk_result(
                row,
                similarity=1.0,
                match_type="standard_code_exact",
                extra_metadata={"standard_code_match_type": "exact"},
            )
            for row in rows
        ]

        if exact_results:
            logger.info(
                "Exact standard-code search matched %s rows for query=%r",
                len(exact_results),
                query,
            )

        return exact_results

    async def hybrid_search(
        self,
        text_query: str,
        spatial_query: Optional[str] = None,
        top_k: int = 10
    ) -> List[DocumentResult]:
        """
        混合检索（文本 + 空间）

        Args:
            text_query: 文本查询
            spatial_query: 空间查询（地址或坐标）
            top_k: 返回结果数量

        Returns:
            混合检索结果
        """
        try:
            # 1. 文本向量搜索
            text_results = await self.search(
                query=text_query,
                top_k=top_k
            )

            # 2. 如果提供了空间查询，进行空间搜索
            if spatial_query:
                # 地理编码
                spatial_results = await self._spatial_search(spatial_query, top_k)

                # 3. 合并和重排序结果
                combined_results = await self._combine_results(
                    text_results=text_results,
                    spatial_results=spatial_results,
                    top_k=top_k
                )

                return combined_results

            return text_results

        except Exception as e:
            logger.error(f"混合检索失败: {e}", exc_info=True)
            raise

    async def find_similar_documents(
        self,
        doc_id: str,
        top_k: int = 5
    ) -> List[DocumentResult]:
        """
        查找相似文档

        Args:
            doc_id: 文档ID
            top_k: 相似文档数量

        Returns:
            相似文档列表
        """
        try:
            # 1. 获取文档的向量嵌入
            doc_embedding = await self._get_document_embedding(doc_id)

            if not doc_embedding:
                return []

            # 2. 向量相似度搜索
            similar_docs = await self._vector_search(
                query_embedding=doc_embedding,
                top_k=top_k + 1,  # 包含自身
                exclude_doc_id=doc_id
            )

            return similar_docs[:top_k]

        except Exception as e:
            logger.error(f"查找相似文档失败: {e}", exc_info=True)
            raise

    async def _get_query_embedding(self, query: str) -> List[float]:
        """获取查询的向量嵌入"""
        try:
            embeddings = await llm_config.get_embeddings([query])
            if embeddings:
                logger.debug(f"查询嵌入获取成功，维度: {len(embeddings[0])}")
                return embeddings[0]
            else:
                logger.warning("查询嵌入返回空列表")
                return []
        except Exception as e:
            logger.error(f"获取查询嵌入失败: {e}", exc_info=True)
            raise

    async def _get_document_embedding(self, doc_id: str) -> Optional[List[float]]:
        """获取文档的向量嵌入"""
        try:
            # TODO: 从向量数据库获取文档嵌入
            return None
        except Exception as e:
            logger.error(f"获取文档嵌入失败: {e}")
            return None

    async def _vector_search(
        self,
        query_embedding: List[float],
        top_k: int,
        threshold: float = 0.7,
        exclude_doc_id: Optional[str] = None
    ) -> List[DocumentResult]:
        """向量相似度搜索"""
        try:
            # 检查 PostgreSQL 连接是否已初始化
            if not db_manager.postgres_sessionmaker:
                logger.error("PostgreSQL 连接未初始化，向量搜索功能不可用。请检查数据库服务及 .env 配置。")
                return []

            if not query_embedding:
                logger.warning("查询嵌入为空，返回空结果")
                return []

            # 将嵌入列表转换为字符串表示
            embedding_str = str(query_embedding)
            logger.debug(f"查询嵌入维度: {len(query_embedding)}, 字符串表示前100字符: {embedding_str[:100]}...")

            async with db_manager.get_postgres_session() as session:
                # 构建SQL查询
                sql = """
                    SELECT
                        id, standard_code, document_name, content,
                        category, keyword, chinese_name, english_name,
                        release_date, implement_date, standard_status,
                        release_unit, charge_unit, draft_unit, application_scope,
                        1 - (embedding <=> CAST(:embedding_str AS vector)) AS similarity
                    FROM policy_chunks
                """
                params = {"embedding_str": embedding_str, "limit": top_k}
                logger.debug(f"SQL查询参数: embedding_str长度={len(embedding_str)}, limit={top_k}")

                # 添加排除条件
                if exclude_doc_id:
                    sql += " WHERE id != :exclude_doc_id "
                    params["exclude_doc_id"] = exclude_doc_id

                # 排序和限制
                sql += " ORDER BY embedding <=> CAST(:embedding_str AS vector) LIMIT :limit"

                # 执行查询
                logger.debug(f"执行SQL查询: {sql[:200]}...")
                result = await session.execute(text(sql), params)
                rows = result.fetchall()
                logger.debug(f"数据库返回 {len(rows)} 行数据")

                # 转换为DocumentResult对象
                results = []
                logger.debug(f"查询返回 {len(rows)} 行数据，阈值: {threshold}")

                for i, row in enumerate(rows):
                    # 过滤阈值
                    similarity = row.similarity
                    logger.debug(f"行 {i+1}: 相似度 = {similarity:.6f}, 标准号: {row.standard_code}, 文档名: {row.document_name}")
                    # 向量搜索命中日志（调试级别，生产环境不显示）
                    logger.debug(f"[VectorSearch] 命中 | doc={row.document_name} | score={similarity:.4f}")

                    if similarity < threshold:
                        logger.debug(f"  低于阈值 {threshold}，跳过")
                        continue


                    doc_result = self._build_policy_chunk_result(
                        row,
                        similarity=float(similarity),
                        match_type="vector",
                    )
                    results.append(doc_result)

                logger.debug(f"向量搜索返回 {len(results)} 条结果")
                return results

        except Exception as e:
            logger.error(f"向量搜索失败: {e}", exc_info=True)
            return []

    async def _apply_spatial_filter(
        self,
        results: List[DocumentResult],
        spatial_filter: SpatialFilter
    ) -> List[DocumentResult]:
        """应用空间过滤器"""
        try:
            return await self._get_rag_filter_engine().apply_spatial_filter(
                results,
                spatial_filter,
            )
        except Exception as e:
            logger.error(f"空间过滤失败: {e}")
            return []

    async def _apply_metadata_filter(
        self,
        results: List[DocumentResult],
        metadata_filter: MetadataFilter
    ) -> List[DocumentResult]:
        """应用元数据过滤器"""
        try:
            return self._get_rag_filter_engine().apply_metadata_filter(
                results,
                metadata_filter,
            )
        except Exception as e:
            logger.error(f"元数据过滤失败: {e}")
            return []

    def _matches_metadata_filter(
        self,
        metadata: Dict[str, Any],
        filter_: MetadataFilter
    ) -> bool:
        """检查文档是否匹配元数据过滤器"""
        return self._get_rag_filter_engine().matches_metadata_filter(metadata, filter_)

    async def _spatial_search(
        self,
        spatial_query: str,
        top_k: int
    ) -> List[DocumentResult]:
        """空间搜索"""
        try:
            return await self._get_rag_filter_engine().spatial_search(spatial_query, top_k)
        except Exception as e:
            logger.error(f"空间搜索失败: {e}")
            return []

    async def _combine_results(
        self,
        text_results: List[DocumentResult],
        spatial_results: List[DocumentResult],
        top_k: int
    ) -> List[DocumentResult]:
        """合并文本和空间搜索结果"""
        try:
            # 简单的合并策略：取文本结果，用空间结果补充
            combined = []

            # 添加文本结果
            for result in text_results[:top_k]:
                combined.append(result)

            # 添加空间结果（如果不在已添加的结果中）
            spatial_ids = {r.id for r in combined}
            for result in spatial_results:
                if result.id not in spatial_ids and len(combined) < top_k:
                    combined.append(result)
                    spatial_ids.add(result.id)

            return combined[:top_k]

        except Exception as e:
            logger.error(f"合并结果失败: {e}")
            return text_results[:top_k]

    async def _rerank_results(
        self,
        query: str,
        results: List[DocumentResult],
        top_k: int,
        metadata_filter: Optional[MetadataFilter] = None,
        spatial_filter: Optional[SpatialFilter] = None,
    ) -> List[DocumentResult]:
        """使用大模型对结果进行重排序"""
        try:
            if not results:
                return results

            prioritized_results = self._get_rag_reranker().rerank(
                query,
                results,
                top_k=top_k,
                metadata_filter=metadata_filter,
                spatial_filter=spatial_filter,
            )
            return prioritized_results

        except Exception as e:
            logger.error(f"重排序失败: {e}")
            return results[:top_k]

    async def _log_search(
        self,
        query: str,
        results_count: int,
        search_time: float,
        search_mode: str = "hybrid",
        top_k: int = 10,
        threshold: float = 0.7,
        metadata_filter: Optional[MetadataFilter] = None,
        spatial_filter: Optional[SpatialFilter] = None,
        used_rerank: bool = True,
        embedding_available: Optional[bool] = None,
    ):
        """记录搜索日志"""
        try:
            context = SearchContext(
                query=query,
                top_k=top_k,
                threshold=threshold,
                search_mode=search_mode,
                use_rerank=used_rerank,
                metadata_filter=metadata_filter,
                spatial_filter=spatial_filter,
            )
            await self._get_rag_search_logger().log_search(
                context,
                results_count=results_count,
                duration_seconds=search_time,
                used_rerank=used_rerank,
                embedding_available=embedding_available,
            )
            logger.info(
                f"搜索日志 - 查询: {query}, 结果数: {results_count}, "
                f"耗时: {search_time:.2f}秒"
            )
        except Exception as e:
            logger.error(f"记录搜索日志失败: {e}")

    async def detect_intent(self, query: str) -> str:
        """
        检测用户意图

        Args:
            query: 用户查询

        Returns:
            意图类别: "search" (搜索文档), "greeting" (打招呼), "clarification" (澄清/追问), "dialog_management" (对话管理), "other" (其他)

        TODO: 未来可演进为Agent工具调用架构，让大模型自主决定何时调用检索工具
              而非硬编码意图路由，以解决混合意图边界模糊问题
        """
        try:
            # 硬编码常见问候语，提高准确性和响应速度
            common_greetings = {
                "你好", "您好", "hello", "hi", "hey", "嗨",
                "早上好", "下午好", "晚上好", "晚安",
                "在吗", "在吗？", "有人吗", "有人吗？", "你好啊",
                "您好啊", "hello there", "hi there",
                "喂", "喂？", "哈喽", "嘿"
            }

            # 清理查询：去除首尾空格，转换为小写，去除标点
            cleaned_query = query.strip().lower()
            # 去除常见标点
            for punct in "。，！？；：“”‘’、（）【】《》.,!?;:\"'":
                cleaned_query = cleaned_query.replace(punct, '')

            if cleaned_query in common_greetings:
                logger.info(f"检测到硬编码问候语: query='{query}' -> intent='greeting'")
                return "greeting"

            system_prompt = """
            你是一个意图分类器，负责判断用户输入的意图。
            请将用户输入分类为以下五种意图之一：
            1. "search" - 用户想要搜索或查询地理信息、测绘、国土空间规划相关的标准、规范、文档、政策等
            2. "greeting" - 用户只是在打招呼、问候、闲聊，如"你好"、"早上好"、"在吗"等
            3. "clarification" - 用户在对之前的对话进行追问、澄清、细化，如"能再说清楚点吗"、"还有其他的吗"、"具体一点"
            4. "dialog_management" - 用户在询问对话本身，如"我的上一个问题是什么？"、"总结一下我们刚才的对话"、"重复一下刚才的回答"、"我们刚才在讨论什么"
            5. "other" - 其他意图，如提问系统功能、技术支持、无关问题等

            注意：如果输入只是简单的问候语，没有具体问题，请务必归类为"greeting"。

            示例：
            - "你好" -> "greeting"
            - "在吗" -> "greeting"
            - "四川省国土空间规划标准" -> "search"
            - "我的上一个问题是什么" -> "dialog_management"
            - "今天天气怎么样" -> "other"

            只返回意图类别字符串，不要有任何解释或额外文本。
            """

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query}
            ]

            # 使用低温度确保确定性输出
            intent = await llm_config.chat_completion(
                messages=messages,
                temperature=0.1,
                max_tokens=20
            )

            # 清理可能的空格和换行
            intent = intent.strip().lower()

            # 验证意图是否有效
            valid_intents = {"search", "greeting", "clarification", "dialog_management", "other"}
            if intent in valid_intents:
                logger.info(f"意图检测: query='{query}', intent='{intent}'")
                return intent
            else:
                # 如果模型返回了无效意图，默认为"search"
                logger.warning(f"模型返回了无效意图: '{intent}'，默认为'search'")
                return "search"

        except Exception as e:
            logger.error(f"意图检测失败: {e}")
            # 默认返回search以保证向后兼容
            return "search"

    async def load_follow_up_document_result(
        self,
        follow_up_context: Optional[FollowUpContext],
        asset_service: DocumentAssetService,
    ) -> tuple[Optional[Dict[str, Any]], Optional[DocumentResult]]:
        """Load the resolved follow-up document and convert it to a single-document result."""
        if not follow_up_context or not follow_up_context.target_document_id:
            return None, None

        detail = await asset_service.get_document_detail_payload(follow_up_context.target_document_id)
        if not detail:
            logger.info(
                "Follow-up target document was not found: %s",
                follow_up_context.target_document_id,
            )
            return None, None

        content = str(detail.get("content") or "").strip()
        if not content:
            logger.info(
                "Follow-up target document has no usable content: %s",
                follow_up_context.target_document_id,
            )
            return None, None

        file_info = detail.get("file_info") or {}
        metadata = dict(detail.get("metadata") or {})
        standard_info = detail.get("standard_info") or {}
        custom_fields = dict(metadata.get("custom_fields") or {})
        if standard_info.get("code"):
            metadata["standard_code"] = standard_info["code"]
            custom_fields.setdefault("standard_code", standard_info["code"])
        metadata["custom_fields"] = custom_fields
        metadata["follow_up_resolution_source"] = follow_up_context.resolution_source

        result = DocumentResult(
            id=str(detail["id"]),
            title=str(detail.get("title") or detail["id"]),
            content=content[:2000],
            similarity=1.0,
            metadata=metadata,
            spatial_info=detail.get("spatial_info"),
            file_type=str(file_info.get("type") or "pdf"),
            file_size=int(file_info.get("size") or 0),
            upload_time=file_info.get("upload_time") or datetime.now(),
            source_url=detail.get("download_url"),
            download_available=bool(detail.get("download_available")),
            download_url=detail.get("download_url"),
        )
        return detail, result

    def _is_document_summary_query(self, query: str) -> bool:
        compact_query = re.sub(r"\s+", "", query or "")
        return any(hint in compact_query for hint in DOCUMENT_FOLLOW_UP_SUMMARY_HINTS)

    def extract_explicit_document_id(self, query: str) -> Optional[str]:
        compact_query = re.sub(r"\s+", "", query or "")
        match = re.search(r"(\d{4,})(?=的|讲|说|内容|标准|文档)|\b(\d{4,})\b", compact_query)
        if not match:
            return None
        return match.group(1) or match.group(2)

    def _build_follow_up_document_context(self, document_detail: Dict[str, Any]) -> str:
        metadata = document_detail.get("metadata") or {}
        standard_info = document_detail.get("standard_info") or {}
        file_info = document_detail.get("file_info") or {}
        custom_fields = metadata.get("custom_fields") or {}

        content = str(document_detail.get("content") or "").strip()
        content_excerpt = content[:6000]

        context_lines = [
            f"文档标题: {document_detail.get('title') or ''}",
            f"文档ID: {document_detail.get('id') or ''}",
            f"标准编号: {standard_info.get('code') or custom_fields.get('standard_code') or ''}",
            f"关键词: {', '.join(metadata.get('keywords') or [])}",
            f"适用范围: {metadata.get('description') or ''}",
            f"文件类型: {file_info.get('type') or ''}",
            "",
            "文档内容:",
            content_excerpt,
        ]
        return "\n".join(context_lines).strip()

    def _extract_content_evidence(self, content: str, limit: int = 3) -> List[str]:
        normalized = re.sub(r"\s+", " ", content or "").strip()
        if not normalized:
            return []

        parts = re.split(r"(?<=[。；！？!?])\s+|(?<=\.)\s+", normalized)
        evidences: List[str] = []
        for part in parts:
            cleaned = part.strip(" \t\r\n-")
            if len(cleaned) < 12:
                continue
            evidences.append(cleaned[:120])
            if len(evidences) >= limit:
                break

        if evidences:
            return evidences

        return [normalized[:120]]

    def _normalize_evidence_blockquotes(self, answer: str) -> str:
        """Render evidence lines as Markdown blockquotes for softer citation styling."""
        if not answer:
            return answer

        normalized_lines: List[str] = []
        for raw_line in answer.splitlines():
            stripped = raw_line.strip()
            if not stripped:
                normalized_lines.append(raw_line)
                continue

            if re.match(r"^>?\s*依据\d+[：:]", stripped):
                quote_body = re.sub(r"^>?\s*", "", stripped, count=1)
                normalized_lines.append(f"> {quote_body}")
                continue

            normalized_lines.append(raw_line)

        return "\n".join(normalized_lines)

    def build_document_follow_up_fallback_answer(
        self,
        query: str,
        document_detail: Dict[str, Any],
    ) -> str:
        title = str(document_detail.get("title") or document_detail.get("id") or "该文档")
        metadata = document_detail.get("metadata") or {}
        standard_info = document_detail.get("standard_info") or {}
        content = str(document_detail.get("content") or "").strip()
        evidence_lines = self._extract_content_evidence(content)
        raw_summary_source = metadata.get("description")
        summary_source = re.sub(r"\s+", " ", str(raw_summary_source or "")).strip()
        if summary_source.lower() in PLACEHOLDER_SUMMARY_VALUES:
            summary_source = ""
        if not summary_source and content:
            summary_source = content[:160]
        summary_source = re.sub(r"\s+", " ", str(summary_source)).strip()
        summary_source = summary_source[:180] if summary_source else "该文档内容中可提取的信息有限。"

        header = f"《{title}》的主要内容可概括为：{summary_source}"
        if standard_info.get("code"):
            header += f"\n标准编号：{standard_info['code']}"

        if not evidence_lines:
            return header

        evidence_text = "\n".join(
            f"依据{i}：{evidence}"
            for i, evidence in enumerate(evidence_lines, start=1)
        )
        return self._normalize_evidence_blockquotes(f"{header}\n{evidence_text}")

    async def generate_document_follow_up_answer(
        self,
        query: str,
        document_detail: Dict[str, Any],
        history: Optional[List[Dict[str, str]]] = None,
    ) -> tuple[str, float]:
        """Generate a direct answer grounded in a single resolved document."""
        start_time = datetime.now()
        truncated_history = self._truncate_history(history)
        is_summary_query = self._is_document_summary_query(query)
        document_context = self._build_follow_up_document_context(document_detail)

        system_prompt = f"""
你是一个专业的空间规划与标准文档助手。现在用户正在追问一份已经锁定的单篇文档。

回答要求:
1. 只能依据下面提供的这份文档内容回答，不能扩展到其他文档，也不能重新检索。
2. 如果文档内容不足以支持回答，明确说明“该文档内容中未找到足够依据回答这个问题”。
3. 如果用户在问“主要内容/讲了什么/适用范围/核心要求/总结”等概要类问题，先给出直接摘要，再补充 1 到 3 条依据。
4. 回答保持简洁、直接，不要输出“已检索到相关标准，请查看下方参考文档”。
5. 若引用依据，使用“依据1 / 依据2 / 依据3”形式，每条只概括文档中的关键信息。

当前问题是否为概要类问题: {"是" if is_summary_query else "否"}

目标文档:
{document_context}
"""
        system_prompt += (
            "\nAdditional formatting rule:\n"
            "- Format every evidence line as a Markdown blockquote, for example `> 依据1：……`.\n"
            "- Do not write evidence lines as normal body paragraphs.\n"
        )

        messages = [{"role": "system", "content": system_prompt}]
        if truncated_history:
            messages.extend(truncated_history)
        messages.append({"role": "user", "content": query})

        try:
            answer = await llm_config.chat_completion(
                messages=messages,
                temperature=0.2,
                max_tokens=900,
            )
            generation_time = (datetime.now() - start_time).total_seconds()
            return self._normalize_evidence_blockquotes(answer), generation_time
        except Exception as exc:
            logger.warning(
                "Document follow-up answer generation failed, using deterministic fallback: %s",
                exc,
            )
            answer = self.build_document_follow_up_fallback_answer(query, document_detail)
            generation_time = (datetime.now() - start_time).total_seconds()
            return self._normalize_evidence_blockquotes(answer), generation_time

    async def generate_answer(
        self,
        query: str,
        results: List[DocumentResult],
        top_context_docs: int = 5,
        history: Optional[List[Dict[str, str]]] = None
    ) -> tuple[str, float]:
        """
        使用大模型生成答案

        Args:
            query: 用户查询
            results: 检索结果列表
            top_context_docs: 用于生成答案的top N文档

        Returns:
            tuple: (生成的答案, 生成耗时秒数)
        """
        try:
            start_time = datetime.now()
            logger.info(f"开始生成答案: query='{query}', 可用结果数={len(results)}, top_context_docs={top_context_docs}")

            # 0. 截断历史记录，防止Token爆炸和上下文窗口溢出
            truncated_history = self._truncate_history(history)
            if history and len(history) > len(truncated_history):
                logger.warning(f"生成答案时历史记录过长，已从 {len(history)} 条消息截断至 {len(truncated_history)} 条")

            # 1. 构建上下文
            context_text = self._build_context(results, top_context_docs)

            # 2. 构建系统提示词
            system_prompt = f"""
你是一个专业的地理信息与测绘政策助手。请基于以下提供的【参考标准片段】和【对话历史】来回答用户的【问题】。
要求：
1. 你的回答必须客观、严谨，直接引用标准中的规定。
2. 如果【参考标准片段】中没有包含问题的答案，请诚实地回答“未在库中检索到相关标准规定”，绝不允许编造或产生幻觉。
3. 请尽可能给出具体的标准编号（如 DB51_T...、GB_T...）。
4. 如果用户询问对话历史（如“上一个问题是什么”、“我们刚才在讨论什么”），请基于【对话历史】回答。

【参考标准片段】：
{context_text}

【空间信息提取任务】
请分析你的回答中涉及的最核心的省级或市级行政区划。如果有，请务必在回答的最末尾，严格以如下 Markdown 代码块的格式输出其行政区划代码 (adcode) 和中文全称 (name)。如果没有涉及具体区域，请不要输出该代码块。
示例格式：
```json
{{"adcode": "510000", "name": "四川省"}}
```"""

            # 3. 构建消息
            messages = [
                {"role": "system", "content": system_prompt}
            ]
            # 把历史对话拼接进来（使用截断后的历史）
            if truncated_history:
                messages.extend(truncated_history)
            # 最后加上当前的问题
            messages.append({"role": "user", "content": query})

            # 4. 调用大模型
            logger.info(f"调用大模型生成答案，上下文长度={len(context_text)}字符")
            answer = await llm_config.chat_completion(
                messages=messages,
                temperature=0.3,  # 较低温度以保证准确性
                max_tokens=1000
            )

            generation_time = (datetime.now() - start_time).total_seconds()
            logger.info(f"答案生成成功，耗时={generation_time:.2f}秒，答案长度={len(answer)}字符")
            return answer, generation_time

        except Exception as e:
            logger.error(f"生成答案失败: {e}", exc_info=True)
            raise

    async def generate_stream_answer(
        self,
        query: str,
        results: List[DocumentResult],
        top_context_docs: int = 5,
        history: Optional[List[Dict[str, str]]] = None
    ):
        """流式生成答案 (SSE Generator)"""
        import json
        import re

        # 0. 截断历史记录
        truncated_history = self._truncate_history(history)
        # 1. 构建上下文
        context_text = self._build_context(results, top_context_docs)
        # 2. 构建系统提示词
        system_prompt = f"""
你是一个专业的地理信息与测绘政策助手。请基于以下提供的【参考标准片段】和【对话历史】来回答用户的【问题】。
要求：
1. 你的回答必须客观、严谨，直接引用标准中的规定。
2. 如果【参考标准片段】中没有包含问题的答案，请诚实地回答“未在库中检索到相关标准规定”，绝不允许编造或产生幻觉。
3. 请尽可能给出具体的标准编号（如 DB51_T...、GB_T...）。
4. 如果用户询问对话历史，请基于【对话历史】回答。

【参考标准片段】：
{context_text}

【空间信息提取任务】
请分析你的回答中涉及的最核心的省级或市级行政区划。如果有，请务必在回答的最末尾，严格以如下 Markdown 代码块的格式输出其行政区划代码 (adcode) 和中文全称 (name)。如果没有涉及具体区域，请不要输出该代码块。
示例格式：
```json
{{"adcode": "510000", "name": "四川省"}}
```"""
        messages = [{"role": "system", "content": system_prompt}]
        if truncated_history:
            messages.extend(truncated_history)
        messages.append({"role": "user", "content": query})

        full_answer = ""
        try:
            # 流式获取并转发文本
            stream = llm_config.stream_chat_completion(
                messages=messages,
                temperature=0.3,
                max_tokens=1000
            )
            async for chunk in stream:
                full_answer += chunk
                # 构造 SSE message 事件数据
                payload = json.dumps({"content": chunk}, ensure_ascii=False)
                yield f"event: message\ndata: {payload}\n\n"

            # 抓取末尾的 JSON map_action
            match = re.search(r'```json\s*(\{.*?\})\s*```', full_answer, re.DOTALL)
            if match:
                map_action_str = match.group(1)
                try:
                    # 验证是个合法 JSON
                    json.loads(map_action_str)
                    # 发送特殊的 map_action 事件
                    yield f"event: map_action\ndata: {map_action_str}\n\n"
                    logger.info(f"解析并下发 map_action 成功: {map_action_str}")
                except Exception as e:
                    logger.error(f"解析 map_action 失败: {e}")

            # 结束标志
            yield f"event: done\ndata: [DONE]\n\n"

        except Exception as e:
            logger.error(f"流式生成答案失败: {e}", exc_info=True)
            error_payload = json.dumps({"error": str(e)}, ensure_ascii=False)
            yield f"event: error\ndata: {error_payload}\n\n"
            yield f"event: done\ndata: [DONE]\n\n"

    def _build_context(self, results: List[DocumentResult], top_n: int = 5) -> str:
        """构建上下文文本"""
        # 取相似度最高的top_n个结果
        top_results = sorted(results, key=lambda x: x.similarity, reverse=True)[:top_n]

        context_parts = []
        for i, doc in enumerate(top_results):
            # 获取文档标题和内容
            title = doc.title
            content = doc.content[:2000] if doc.content else ""  # 限制内容长度
            similarity = doc.similarity

            # 构建格式化的上下文片段
            context_part = f"【参考标准 {i+1}】\n"
            context_part += f"标准编号/标题: {title}\n"
            context_part += f"相似度分数: {similarity:.4f}\n"
            context_part += f"内容摘要: {content}\n"
            context_part += "-" * 50

            context_parts.append(context_part)

        return "\n\n".join(context_parts)

    def _truncate_history(self, history: Optional[List[Dict[str, str]]], max_messages: int = 6) -> List[Dict[str, str]]:
        """
        截断历史记录，只保留最近的 max_messages 条消息

        Args:
            history: 原始历史记录
            max_messages: 最大消息数（默认6条，即3轮对话）

        Returns:
            截断后的历史记录
        """
        if not history:
            return []

        # 只保留最近的 max_messages 条消息，并转换为 LLM client 需要的普通 dict。
        truncated = []
        for message in history[-max_messages:]:
            if hasattr(message, "model_dump"):
                payload = message.model_dump()
            else:
                payload = dict(message)
            truncated.append(
                {
                    "role": str(payload.get("role", "")),
                    "content": str(payload.get("content", "")),
                }
            )

        original_len = len(history)
        truncated_len = len(truncated)

        if original_len > truncated_len:
            logger.warning(f"历史记录过长，已从 {original_len} 条消息截断至 {truncated_len} 条")

        return truncated

    async def handle_dialog_management(
        self,
        query: str,
        history: Optional[List[Dict[str, str]]] = None
    ) -> str:
        """
        处理对话管理查询

        Args:
            query: 用户查询
            history: 历史对话记录

        Returns:
            生成的答案
        """
        try:
            # 截断历史记录，防止Token爆炸
            truncated_history = self._truncate_history(history)
            logger.info(f"处理对话管理查询: query='{query}', 原始历史长度={len(history) if history else 0}, 截断后长度={len(truncated_history)}")

            # 构建专门用于对话管理的系统提示词
            system_prompt = """
            你是一个专业的对话助手，负责回答关于对话本身的问题。
            请基于提供的对话历史记录回答用户的问题。

            常见问题类型：
            1. "我的上一个问题是什么？" - 从历史中找出最后一个用户问题
            2. "我们刚才在讨论什么？" - 简要总结最近的对话主题
            3. "重复一下刚才的回答" - 重新表述助理的最后一次回答
            4. "总结一下我们刚才的对话" - 提供对话摘要

            如果无法从历史中找到相关信息，请诚实地告知用户。
            回答要简洁、准确。
            """

            messages = [
                {"role": "system", "content": system_prompt}
            ]

            # 添加历史对话（使用截断后的历史）
            if truncated_history:
                messages.extend(truncated_history)

            # 添加当前问题
            messages.append({"role": "user", "content": query})

            # 调用大模型
            answer = await llm_config.chat_completion(
                messages=messages,
                temperature=0.3,
                max_tokens=500
            )

            logger.info(f"对话管理查询处理完成，答案长度={len(answer)}字符")
            return answer

        except Exception as e:
            logger.error(f"处理对话管理查询失败: {e}")
            # 返回友好的错误信息
            return "抱歉，我无法处理这个对话管理请求。请尝试重新提出您的问题。"

    async def generate_chitchat_response(
        self,
        query: str,
        intent: str,
        history: Optional[List[Dict[str, str]]] = None
    ) -> tuple[str, float]:
        """
        生成闲聊回复

        Args:
            query: 用户查询
            intent: 意图类别 (greeting/other)
            history: 历史对话记录

        Returns:
            tuple: (生成的闲聊回复, 生成耗时秒数)
        """
        try:
            start_time = datetime.now()
            logger.info(f"生成闲聊回复: query='{query}', intent='{intent}'")

            # 截断历史记录，防止Token爆炸
            truncated_history = self._truncate_history(history)

            # 构建闲聊专用的系统提示词
            system_prompt = """
            你是一个专业的地理信息与测绘政策助手，但当前用户正在与你进行闲聊或打招呼。
            请根据用户的意图和查询，生成友好、自然、专业的回复。

            意图说明：
            1. "greeting" - 用户正在打招呼或问候
            2. "other" - 用户提出了与地理信息、测绘、国土空间规划无关的其他问题

            回复要求：
            1. 友好、热情、自然
            2. 简要介绍你的专业领域（国土空间规划、测绘标准、地理信息政策法规）
            3. 引导用户提出相关专业问题
            4. 如果用户的问题超出你的专业范围，礼貌地说明你的能力边界
            5. 保持回复简洁（1-3句话）
            """

            messages = [
                {"role": "system", "content": system_prompt}
            ]

            # 添加历史对话（使用截断后的历史）
            if truncated_history:
                messages.extend(truncated_history)

            # 添加当前问题
            messages.append({"role": "user", "content": query})

            # 调用大模型生成回复
            answer = await llm_config.chat_completion(
                messages=messages,
                temperature=0.7,  # 稍高温度使回复更自然
                max_tokens=200
            )

            generation_time = (datetime.now() - start_time).total_seconds()
            logger.info(f"闲聊回复生成成功，耗时={generation_time:.2f}秒，答案长度={len(answer)}字符")
            return answer, generation_time

        except Exception as e:
            logger.error(f"生成闲聊回复失败: {e}", exc_info=True)
            # 返回友好的备用回复
            backup_response = "您好！我是 GeoAI 空间规划智能助手，专门为您提供国土空间规划、测绘标准、地理信息相关的政策法规查询服务。请问有什么可以帮助您的吗？"
            return backup_response, 0.0

    def _detect_rule_based_intent(self, query: str) -> Optional[str]:
        cleaned_query = _normalize_query_text(query)
        compact_query = re.sub(r"\s+", "", cleaned_query)

        if not compact_query:
            return "other"

        if cleaned_query in COMMON_GREETING_QUERIES or compact_query in COMMON_GREETING_QUERIES:
            return "greeting"

        if any(hint in compact_query for hint in DIALOG_MANAGEMENT_HINTS):
            return "dialog_management"

        if any(hint in compact_query for hint in CASUAL_CHAT_HINTS):
            return "other"

        return None

    async def detect_intent(self, query: str) -> str:
        """Detect user intent for search, follow-up, chitchat, and dialog-management turns."""
        rule_based_intent = self._detect_rule_based_intent(query)
        if rule_based_intent:
            logger.info("Rule-based intent detected for query=%r: %s", query, rule_based_intent)
            return rule_based_intent

        try:
            system_prompt = """
            你是一个意图分类器，负责判断用户输入的意图。
            请将用户输入分类为以下五种意图之一：
            1. "search" - 用户想要搜索或查询地理信息、测绘、国土空间规划相关的标准、规范、文档、政策等
            2. "greeting" - 用户只是在打招呼、问候、寒暄
            3. "clarification" - 用户在对之前的对话进行追问、澄清、细化
            4. "dialog_management" - 用户在询问对话本身，例如上一条问题、刚才讨论内容、重复回答等
            5. "other" - 其他非检索闲聊或无关问题

            只返回意图类别字符串，不要有任何解释或额外文本。
            """

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query},
            ]

            intent = await llm_config.chat_completion(
                messages=messages,
                temperature=0.1,
                max_tokens=20,
            )
            intent = intent.strip().lower()

            valid_intents = {"search", "greeting", "clarification", "dialog_management", "other"}
            if intent in valid_intents:
                logger.info("LLM intent detected for query=%r: %s", query, intent)
                return intent

            logger.warning("Invalid intent returned by model for query=%r: %r", query, intent)
            return "search"
        except Exception as exc:
            logger.error("Intent detection failed for query=%r: %s", query, exc)
            return "search"
