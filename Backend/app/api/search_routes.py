"""
智能检索 API 路由
"""

import logging
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import StreamingResponse
from typing import List, Optional
import json
from pydantic import BaseModel
from datetime import datetime

from app.core.security import require_authenticated_admin
from app.services.search_service import SearchService
from app.models.search_models import SearchRequest, SearchResponse, DocumentResult

logger = logging.getLogger(__name__)

public_router = APIRouter()
router = APIRouter(dependencies=[Depends(require_authenticated_admin)])

RELAXED_VECTOR_THRESHOLD = 0.35


class HealthCheckResponse(BaseModel):
    """健康检查响应"""
    status: str
    service: str


@public_router.get("/health", response_model=HealthCheckResponse)
async def health_check():
    """检索服务健康检查"""
    return HealthCheckResponse(
        status="healthy",
        service="智能检索服务"
    )


@router.post("/query")
async def search_documents(
    request: SearchRequest,
    search_service: SearchService = Depends(SearchService)
):
    """
    智能检索文档

    Args:
        request: 检索请求参数
        search_service: 检索服务实例

    Returns:
        检索结果

    TODO: 未来优化方向
    - 会话状态持久化：使用Redis/PostgreSQL存储会话历史，前端只传递session_id
    - 高可用设计：支持浏览器刷新、多设备登录等场景下的会话恢复
    - 分布式会话：支持多实例部署下的会话共享
    """
    try:
        start_time = datetime.now()

        # 0. 意图检测（避免闲聊触发不必要的向量搜索）
        intent = await search_service.detect_intent(request.query)
        logger.info(f"意图检测结果: query='{request.query}', intent='{intent}'")

        # 定义非搜索意图集合（这些意图不应触发向量检索）
        NON_SEARCH_INTENTS = {"greeting", "other", "dialog_management"}
        # 澄清意图（clarification）需要基于上下文进行搜索，因此不属于非搜索意图

        # 严格短路控制：如果是非搜索意图，绝对禁止调用向量检索
        if intent in NON_SEARCH_INTENTS:
            logger.info(f"检测到非搜索意图 '{intent}'，执行严格短路，跳过向量检索")
            search_time = (datetime.now() - start_time).total_seconds()

            generated_answer = None
            generation_time = None

            # 根据意图类型选择处理方式
            if intent == "dialog_management":
                # 对话管理意图：基于历史记录生成答案
                generated_answer = await search_service.handle_dialog_management(
                    query=request.query,
                    history=request.history
                )
                logger.info(f"对话管理处理完成，答案长度={len(generated_answer) if generated_answer else 0}字符")
            else:
                # 闲聊意图（greeting/other）：生成友好回复
                # 使用LLM生成更自然的回复，避免硬编码
                try:
                    if request.use_generation:
                        gen_start_time = datetime.now()
                        # 调用专门的闲聊回复生成
                        generated_answer, gen_time = await search_service.generate_chitchat_response(
                            query=request.query,
                            intent=intent,
                            history=request.history
                        )
                        generation_time = (datetime.now() - gen_start_time).total_seconds()
                        logger.info(f"闲聊回复生成完成，耗时={generation_time:.2f}秒")
                    else:
                        # 如果不使用生成，返回简洁的硬编码回复
                        if intent == "greeting":
                            generated_answer = "您好！我是 GeoAI 空间规划智能助手，专门为您提供国土空间规划、测绘标准、地理信息相关的政策法规查询服务。请问有什么可以帮助您的吗？"
                        else:
                            generated_answer = "您好！我主要专注于国土空间规划、测绘标准、地理信息相关的政策法规查询。如果您有其他问题，我会尽力提供帮助。"
                except Exception as gen_error:
                    logger.error(f"闲聊回复生成失败，使用备用回复: {gen_error}")
                    # 备用回复
                    generated_answer = "您好！我是 GeoAI 空间规划智能助手，请问有什么可以帮助您的吗？"

            # 返回完整但空的检索结果，确保数据结构完整性
            return SearchResponse(
                query=request.query,
                results=[],  # 强制置空，绝对禁止返回任何文档片段
                total_count=0,
                search_time=search_time,
                search_mode=request.search_mode,
                generated_answer=generated_answer if request.use_generation else None,
                generation_time=generation_time if request.use_generation else None
            )

        # 执行至此，说明 intent 是 search、clarification 或无效意图（兜底）
        # 只有这些意图才允许执行向量检索
        logger.info(f"检测到搜索相关意图 '{intent}'，执行向量检索")

        # 1. 执行检索
        results = await search_service.search(
            query=request.query,
            top_k=request.top_k,
            threshold=request.threshold,
            spatial_filter=request.spatial_filter,
            metadata_filter=request.metadata_filter
        )

        if not results and request.threshold > RELAXED_VECTOR_THRESHOLD:
            logger.info(
                "默认阈值未命中结果，使用较低阈值重试: query='%s', threshold=%.2f -> %.2f",
                request.query,
                request.threshold,
                RELAXED_VECTOR_THRESHOLD,
            )
            results = await search_service.search(
                query=request.query,
                top_k=request.top_k,
                threshold=RELAXED_VECTOR_THRESHOLD,
                spatial_filter=request.spatial_filter,
                metadata_filter=request.metadata_filter
            )

        search_time = (datetime.now() - start_time).total_seconds()
        # 生成检索响应的基础数据
        base_response = SearchResponse(
            query=request.query,
            results=results,
            total_count=len(results),
            search_time=search_time,
            search_mode=request.search_mode,
            generated_answer=None,
            generation_time=None
        )

        # 2. 检查是否开启大模型生成
        # 即使没有命中文档，也继续生成一条诚实回答，避免前端退化为泛化报错文案。
        if not request.use_generation:
            return base_response

        # 如果开启大模型生成，并且启用了 SSE 流式传输
        if getattr(request, "stream", False):
            async def event_generator():
                # 1. 首先下发 context 检索结果（供前端渲染列表）
                context_payload = json.dumps(base_response.model_dump(), ensure_ascii=False)
                yield f"event: context\ndata: {context_payload}\n\n"
                
                # 2. 下发流式推理过程 (同时包含 map_action 追加事件)
                stream = search_service.generate_stream_answer(
                    query=request.query,
                    results=results,
                    top_context_docs=min(5, len(results)),
                    history=request.history
                )
                async for event_chunk in stream:
                    yield event_chunk
                    
            return StreamingResponse(event_generator(), media_type="text/event-stream")
        
        # 否则使用同步的一把梭返回
        try:
            gen_start_time = datetime.now()
            generated_answer, gen_time = await search_service.generate_answer(
                query=request.query,
                results=results,
                top_context_docs=min(5, len(results)),
                history=request.history
            )
            base_response.generation_time = (datetime.now() - gen_start_time).total_seconds()
            base_response.generated_answer = generated_answer
            logger.info(f"答案生成完成，耗时={base_response.generation_time:.2f}秒")
        except Exception as gen_error:
            logger.error(f"生成答案失败，但检索结果仍然返回: {gen_error}")

        return base_response

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"检索失败: {str(e)}")


@router.post("/hybrid", response_model=SearchResponse)
async def hybrid_search(
    query: str = Query(..., description="检索查询语句"),
    spatial_query: Optional[str] = Query(None, description="空间查询条件，如'北京市海淀区'"),
    top_k: int = Query(10, description="返回结果数量"),
    search_service: SearchService = Depends(SearchService)
):
    """
    混合检索（文本 + 空间）

    Args:
        query: 文本查询
        spatial_query: 空间查询
        top_k: 返回结果数量
        search_service: 检索服务实例

    Returns:
        混合检索结果
    """
    try:
        results = await search_service.hybrid_search(
            text_query=query,
            spatial_query=spatial_query,
            top_k=top_k
        )
        return SearchResponse(
            query=f"文本: {query}, 空间: {spatial_query}" if spatial_query else query,
            results=results,
            total_count=len(results)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"混合检索失败: {str(e)}")


@router.get("/suggest")
async def get_suggestions(
    prefix: str = Query(..., description="输入前缀"),
    limit: int = Query(5, description="建议数量")
):
    """
    搜索建议

    Args:
        prefix: 输入前缀
        limit: 建议数量

    Returns:
        搜索建议列表
    """
    # TODO: 实现搜索建议逻辑
    suggestions = []
    return {"suggestions": suggestions}


@router.get("/similar/{doc_id}")
async def find_similar_documents(
    doc_id: str,
    top_k: int = Query(5, description="相似文档数量"),
    search_service: SearchService = Depends(SearchService)
):
    """
    查找相似文档

    Args:
        doc_id: 文档ID
        top_k: 相似文档数量

    Returns:
        相似文档列表
    """
    try:
        similar_docs = await search_service.find_similar_documents(
            doc_id=doc_id,
            top_k=top_k
        )
        return {
            "doc_id": doc_id,
            "similar_documents": similar_docs
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查找相似文档失败: {str(e)}")
