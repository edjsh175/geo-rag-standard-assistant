"""Deterministic PostgreSQL/pgvector search service."""

import inspect
import logging
from datetime import datetime
from typing import List, Optional

from app.core.database import db_manager
from app.models.search_models import DocumentResult, MetadataFilter, SpatialFilter
from app.services.rag.contracts import RetrievalQuery
from app.services.rag.postgres_adapter import PostgresRetrievalAdapter
from app.services.rag.search_logger import RagSearchLogger

logger = logging.getLogger(__name__)


class SearchService:
    """Deterministic retrieval/search facade."""

    def __init__(self):
        self.vector_service = None  # 将在后面初始化
        self.spatial_service = None  # 将在后面初始化
        self.postgres_available = False
        self.rag_search_logger = RagSearchLogger()
        self.retrieval_adapter = PostgresRetrievalAdapter()

        # 检查数据库连接状态
        self._check_database_status()

    def _get_rag_search_logger(self) -> RagSearchLogger:
        if not hasattr(self, "rag_search_logger"):
            self.rag_search_logger = RagSearchLogger()
        return self.rag_search_logger

    def get_retrieval_port(self) -> PostgresRetrievalAdapter:
        if not hasattr(self, "retrieval_adapter"):
            self.retrieval_adapter = PostgresRetrievalAdapter()
        return self.retrieval_adapter

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

            retrieval_query = RetrievalQuery(
                query_text=query,
                top_k=top_k,
                threshold=threshold,
                search_mode=search_mode,
                use_rerank=use_rerank,
                spatial_filter=spatial_filter,
                metadata_filter=metadata_filter,
            )
            retrieved = await self.get_retrieval_port().retrieve(retrieval_query)
            final_results = [candidate.source_result for candidate in retrieved.candidates]

            # 6. 记录搜索日志
            log_result = self._log_search(
                query=query,
                results_count=len(final_results),
                search_time=(datetime.now() - start_time).total_seconds(),
                search_mode=retrieval_query.mode,
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
                spatial_results = await self.get_retrieval_port().spatial_search(
                    spatial_query,
                    top_k,
                )

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
        return await self.get_retrieval_port().find_similar_documents(
            doc_id=doc_id,
            top_k=top_k,
        )
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
            context = RetrievalQuery(
                query_text=query,
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
