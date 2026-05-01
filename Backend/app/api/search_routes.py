"""
Search API routes.
"""

from __future__ import annotations

from datetime import datetime
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.security import require_authenticated_admin
from app.models.search_models import FollowUpContext, SearchRequest, SearchResponse
from app.services.document_asset_service import DocumentAssetService
from app.services.search_service import SearchService

logger = logging.getLogger(__name__)

public_router = APIRouter()
router = APIRouter(dependencies=[Depends(require_authenticated_admin)])

RELAXED_VECTOR_THRESHOLD = 0.35
NON_SEARCH_INTENTS = {"greeting", "other", "dialog_management"}


class HealthCheckResponse(BaseModel):
    status: str
    service: str


@public_router.get("/health", response_model=HealthCheckResponse)
async def health_check() -> HealthCheckResponse:
    return HealthCheckResponse(status="healthy", service="search")


@router.post("/query", response_model=SearchResponse)
async def search_documents(
    request: SearchRequest,
    search_service: SearchService = Depends(SearchService),
    asset_service: DocumentAssetService = Depends(DocumentAssetService),
):
    try:
        start_time = datetime.now()

        follow_up_context = request.follow_up_context
        if (
            follow_up_context is None
            and request.use_generation
            and search_service._is_document_summary_query(request.query)
        ):
            explicit_document_id = search_service.extract_explicit_document_id(request.query)
            if explicit_document_id:
                follow_up_context = FollowUpContext(
                    target_document_id=explicit_document_id,
                    candidate_documents=[],
                    resolution_source="explicit_text",
                )

        follow_up_detail = None
        if follow_up_context and follow_up_context.target_document_id:
            follow_up_detail, follow_up_result = await search_service.load_follow_up_document_result(
                follow_up_context,
                asset_service,
            )
            if follow_up_detail and follow_up_result:
                base_response = SearchResponse(
                    query=request.query,
                    results=[follow_up_result],
                    total_count=1,
                    search_time=(datetime.now() - start_time).total_seconds(),
                    search_mode=request.search_mode,
                )

                if request.use_generation:
                    try:
                        generated_answer, generation_time = await search_service.generate_document_follow_up_answer(
                            query=request.query,
                            document_detail=follow_up_detail,
                            history=request.history,
                        )
                        base_response.generated_answer = generated_answer
                        base_response.generation_time = generation_time
                    except Exception as exc:
                        logger.error(
                            "Document follow-up answer generation failed, falling back to search: %s",
                            exc,
                        )
                    else:
                        return base_response
                else:
                    return base_response

        intent = await search_service.detect_intent(request.query)
        logger.info("Search intent detected for query=%r: %s", request.query, intent)

        if intent in NON_SEARCH_INTENTS:
            generated_answer = None
            generation_time = None
            if intent == "dialog_management":
                generated_answer = await search_service.handle_dialog_management(
                    query=request.query,
                    history=request.history,
                )
            elif request.use_generation:
                try:
                    generated_answer, _ = await search_service.generate_chitchat_response(
                        query=request.query,
                        intent=intent,
                        history=request.history,
                    )
                    generation_time = (datetime.now() - start_time).total_seconds()
                except Exception:
                    generated_answer = "您好，我主要负责标准检索、引用解读和相关文档查询。"
            else:
                generated_answer = None

            return SearchResponse(
                query=request.query,
                results=[],
                total_count=0,
                search_time=(datetime.now() - start_time).total_seconds(),
                search_mode=request.search_mode,
                generated_answer=generated_answer if request.use_generation else None,
                generation_time=generation_time if request.use_generation else None,
            )

        results = await search_service.search(
            query=request.query,
            top_k=request.top_k,
            threshold=request.threshold,
            spatial_filter=request.spatial_filter,
            metadata_filter=request.metadata_filter,
        )

        if not results and request.threshold > RELAXED_VECTOR_THRESHOLD:
            logger.info(
                "Retrying search with relaxed threshold: %.2f -> %.2f",
                request.threshold,
                RELAXED_VECTOR_THRESHOLD,
            )
            results = await search_service.search(
                query=request.query,
                top_k=request.top_k,
                threshold=RELAXED_VECTOR_THRESHOLD,
                spatial_filter=request.spatial_filter,
                metadata_filter=request.metadata_filter,
            )

        results = await asset_service.enrich_search_results(results)

        base_response = SearchResponse(
            query=request.query,
            results=results,
            total_count=len(results),
            search_time=(datetime.now() - start_time).total_seconds(),
            search_mode=request.search_mode,
        )

        if not request.use_generation:
            return base_response

        if getattr(request, "stream", False):
            async def event_generator():
                context_payload = json.dumps(base_response.model_dump(), ensure_ascii=False)
                yield f"event: context\ndata: {context_payload}\n\n"

                async for event_chunk in search_service.generate_stream_answer(
                    query=request.query,
                    results=results,
                    top_context_docs=min(5, len(results)),
                    history=request.history,
                ):
                    yield event_chunk

            return StreamingResponse(event_generator(), media_type="text/event-stream")

        try:
            generated_answer, _ = await search_service.generate_answer(
                query=request.query,
                results=results,
                top_context_docs=min(5, len(results)),
                history=request.history,
            )
            base_response.generated_answer = generated_answer
            base_response.generation_time = (datetime.now() - start_time).total_seconds()
        except Exception as exc:
            logger.error("Answer generation failed, returning search-only response: %s", exc)

        return base_response
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Search failed: {exc}") from exc


@router.post("/hybrid", response_model=SearchResponse)
async def hybrid_search(
    query: str = Query(..., description="Search query."),
    spatial_query: Optional[str] = Query(None, description="Spatial filter query."),
    top_k: int = Query(10, description="Maximum number of results."),
    search_service: SearchService = Depends(SearchService),
    asset_service: DocumentAssetService = Depends(DocumentAssetService),
):
    try:
        results = await search_service.hybrid_search(
            text_query=query,
            spatial_query=spatial_query,
            top_k=top_k,
        )
        results = await asset_service.enrich_search_results(results)
        return SearchResponse(
            query=f"text={query}; spatial={spatial_query}" if spatial_query else query,
            results=results,
            total_count=len(results),
            search_mode="hybrid",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Hybrid search failed: {exc}") from exc


@router.get("/suggest")
async def get_suggestions(
    prefix: str = Query(..., description="Input prefix."),
    limit: int = Query(5, description="Number of suggestions."),
):
    _ = prefix, limit
    return {"suggestions": []}


@router.get("/similar/{doc_id}")
async def find_similar_documents(
    doc_id: str,
    top_k: int = Query(5, description="Maximum number of similar documents."),
    search_service: SearchService = Depends(SearchService),
    asset_service: DocumentAssetService = Depends(DocumentAssetService),
):
    try:
        similar_docs = await search_service.find_similar_documents(doc_id=doc_id, top_k=top_k)
        similar_docs = await asset_service.enrich_search_results(similar_docs)
        return {
            "doc_id": doc_id,
            "similar_documents": similar_docs,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Find similar documents failed: {exc}") from exc
