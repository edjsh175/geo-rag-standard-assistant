"""
智能检索服务
"""

import logging
import re
import string
from typing import List, Optional, Dict, Any
from datetime import datetime

from app.core.llm_config import llm_config
from app.core.database import db_manager
from sqlalchemy import text
from app.models.search_models import (
    DocumentResult, SpatialFilter, MetadataFilter
)

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

        # 检查数据库连接状态
        self._check_database_status()

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
        metadata_filter: Optional[MetadataFilter] = None
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

            # 1. 获取查询的向量嵌入
            query_embedding = await self._get_query_embedding(query)

            # 2. 向量相似度搜索
            vector_results = await self._vector_search(
                query_embedding=query_embedding,
                top_k=top_k * 2,  # 获取更多结果用于后续过滤
                threshold=threshold
            )

            keyword_results = await self._keyword_search(
                query=query,
                top_k=top_k * 2,
            )

            vector_results = self._merge_and_dedupe_results(
                keyword_results,
                vector_results,
                top_k=top_k * 2,
            )

            # 3. 应用空间过滤器
            if spatial_filter:
                vector_results = await self._apply_spatial_filter(
                    results=vector_results,
                    spatial_filter=spatial_filter
                )

            # 4. 应用元数据过滤器
            if metadata_filter:
                vector_results = await self._apply_metadata_filter(
                    results=vector_results,
                    metadata_filter=metadata_filter
                )

            # 5. 重排序和截断
            final_results = await self._rerank_results(
                query=query,
                results=vector_results,
                top_k=top_k
            )

            # 6. 记录搜索日志
            await self._log_search(
                query=query,
                results_count=len(final_results),
                search_time=(datetime.now() - start_time).total_seconds()
            )

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

        deduped_terms: List[str] = []
        for term in terms:
            if term not in deduped_terms:
                deduped_terms.append(term)
        return deduped_terms[:6]

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
                        LEAST(0.95, 0.55 + ({' + '.join(score_parts)})) AS similarity
                    FROM policy_chunks
                    WHERE {' OR '.join(conditions)}
                    ORDER BY document_name, similarity DESC, id
                )
                SELECT id, standard_code, document_name, content, similarity
                FROM matched
                ORDER BY similarity DESC, document_name
                LIMIT :limit
            """

            async with db_manager.get_postgres_session() as session:
                result = await session.execute(text(sql), params)
                rows = result.fetchall()

            keyword_results = []
            for row in rows:
                keyword_results.append(DocumentResult(
                    id=row.id,
                    title=row.document_name,
                    content=row.content[:500] if row.content else "",
                    similarity=float(row.similarity),
                    metadata={
                        "standard_code": row.standard_code,
                        "document_name": row.document_name,
                        "match_type": "keyword",
                    },
                    spatial_info=None,
                    file_type="unknown",
                    file_size=0,
                    upload_time=datetime.now(),
                    source_url=None,
                ))

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


                    # 构建元数据
                    metadata = {
                        "standard_code": row.standard_code,
                        "document_name": row.document_name
                    }

                    # 创建DocumentResult
                    # 注意：policy_chunks表可能不包含所有字段，这里提供默认值
                    # 实际项目中应根据表结构调整
                    doc_result = DocumentResult(
                        id=row.id,
                        title=row.document_name,  # 使用文档名作为标题
                        content=row.content[:500] if row.content else "",  # 截取前500字符作为摘要
                        similarity=similarity,
                        metadata=metadata,
                        spatial_info=None,  # 需要从其他表获取
                        file_type="unknown",  # 需要从其他表获取
                        file_size=0,  # 需要从其他表获取
                        upload_time=datetime.now(),  # 需要从其他表获取
                        source_url=None  # 需要从其他表获取
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
            # TODO: 实现空间过滤逻辑
            # 这里应该根据空间关系过滤结果
            return results
        except Exception as e:
            logger.error(f"空间过滤失败: {e}")
            return results

    async def _apply_metadata_filter(
        self,
        results: List[DocumentResult],
        metadata_filter: MetadataFilter
    ) -> List[DocumentResult]:
        """应用元数据过滤器"""
        try:
            # TODO: 实现元数据过滤逻辑
            filtered_results = []
            for result in results:
                if self._matches_metadata_filter(result.metadata, metadata_filter):
                    filtered_results.append(result)
            return filtered_results
        except Exception as e:
            logger.error(f"元数据过滤失败: {e}")
            return results

    def _matches_metadata_filter(
        self,
        metadata: Dict[str, Any],
        filter_: MetadataFilter
    ) -> bool:
        """检查文档是否匹配元数据过滤器"""
        # TODO: 实现完整的元数据匹配逻辑
        return True

    async def _spatial_search(
        self,
        spatial_query: str,
        top_k: int
    ) -> List[DocumentResult]:
        """空间搜索"""
        try:
            # TODO: 实现空间搜索逻辑
            # 1. 地理编码（地址转坐标）
            # 2. 空间查询（查找附近的文档）
            return []
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
        top_k: int
    ) -> List[DocumentResult]:
        """使用大模型对结果进行重排序"""
        try:
            if not results or len(results) <= 1:
                return results

            # TODO: 实现大模型重排序逻辑
            # 可以使用交叉编码器或大模型进行相关性评估
            return results[:top_k]

        except Exception as e:
            logger.error(f"重排序失败: {e}")
            return results[:top_k]

    async def _log_search(
        self,
        query: str,
        results_count: int,
        search_time: float
    ):
        """记录搜索日志"""
        try:
            # TODO: 实现搜索日志记录
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

        # 只保留最近的 max_messages 条消息
        truncated = history[-max_messages:]

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
