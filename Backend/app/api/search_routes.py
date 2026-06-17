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

from app.core.auth import UserIdentity
from app.core.security import require_authenticated_user
from app.models.search_models import FeedbackRequest, FeedbackResponse, FollowUpContext, SearchRequest, SearchResponse
from app.services.demo_quota_service import DemoQuotaDecision, DemoQuotaService, get_demo_quota_service
from app.services.document_contract_service import DocumentContractService
from app.services.document_asset_service import DocumentAssetService
from app.services.search_feedback_service import SearchFeedbackService
from app.services.search_service import SearchService

logger = logging.getLogger(__name__)

public_router = APIRouter()
router = APIRouter()

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
    current_user: UserIdentity = Depends(require_authenticated_user),
    search_service: SearchService = Depends(SearchService),
    asset_service: DocumentAssetService = Depends(DocumentAssetService),
    contract_service: DocumentContractService = Depends(DocumentContractService),
    quota_service: DemoQuotaService = Depends(get_demo_quota_service),
):
    try:
        start_time = datetime.now()
        quota_decision = await _consume_visitor_generation_quota(
            request,
            current_user,
            quota_service,
        )
        generation_allowed = request.use_generation and (
            quota_decision is None or quota_decision.allowed
        )

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

                base_response.quota = _quota_status(quota_decision)

                if generation_allowed:
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
                return base_response

        if not generation_allowed:
            results = await _retrieve_results(request, search_service, asset_service, contract_service)
            return SearchResponse(
                query=request.query,
                results=results,
                total_count=len(results),
                search_time=(datetime.now() - start_time).total_seconds(),
                search_mode=request.search_mode,
                quota=_quota_status(quota_decision),
            )

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
            elif generation_allowed:
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
                generated_answer=generated_answer if generation_allowed else None,
                generation_time=generation_time if generation_allowed else None,
                quota=_quota_status(quota_decision),
            )

        results = await _retrieve_results(request, search_service, asset_service, contract_service)

        base_response = SearchResponse(
            query=request.query,
            results=results,
            total_count=len(results),
            search_time=(datetime.now() - start_time).total_seconds(),
            search_mode=request.search_mode,
        )

        base_response.quota = _quota_status(quota_decision)

        if not generation_allowed:
            return base_response

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


@router.post(
    "/query/stream",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def stream_search_documents(
    request: SearchRequest,
    current_user: UserIdentity = Depends(require_authenticated_user),
    search_service: SearchService = Depends(SearchService),
    asset_service: DocumentAssetService = Depends(DocumentAssetService),
    contract_service: DocumentContractService = Depends(DocumentContractService),
    quota_service: DemoQuotaService = Depends(get_demo_quota_service),
):
    try:
        start_time = datetime.now()
        quota_decision = await _consume_visitor_generation_quota(
            request,
            current_user,
            quota_service,
        )
        generation_allowed = request.use_generation and (
            quota_decision is None or quota_decision.allowed
        )
        results = await _retrieve_results(request, search_service, asset_service, contract_service)
        base_response = SearchResponse(
            query=request.query,
            results=results,
            total_count=len(results),
            search_time=(datetime.now() - start_time).total_seconds(),
            search_mode=request.search_mode,
            quota=_quota_status(quota_decision),
        )

        async def event_generator():
            context_payload = json.dumps(base_response.model_dump(), ensure_ascii=False)
            yield f"event: context\ndata: {context_payload}\n\n"

            if not generation_allowed:
                return

            async for event_chunk in search_service.generate_stream_answer(
                query=request.query,
                results=results,
                top_context_docs=min(5, len(results)),
                history=request.history,
            ):
                yield event_chunk

        return StreamingResponse(event_generator(), media_type="text/event-stream")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Stream search failed: {exc}") from exc


@router.post("/hybrid", response_model=SearchResponse)
async def hybrid_search(
    query: str = Query(..., description="Search query."),
    spatial_query: Optional[str] = Query(None, description="Spatial filter query."),
    top_k: int = Query(10, description="Maximum number of results."),
    search_service: SearchService = Depends(SearchService),
    asset_service: DocumentAssetService = Depends(DocumentAssetService),
    contract_service: DocumentContractService = Depends(DocumentContractService),
    current_user: UserIdentity = Depends(require_authenticated_user),
):
    _ = current_user
    try:
        results = await search_service.hybrid_search(
            text_query=query,
            spatial_query=spatial_query,
            top_k=top_k,
        )
        results = await asset_service.enrich_search_results(results)
        results = await contract_service.filter_deleted_results(results)
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
    contract_service: DocumentContractService = Depends(DocumentContractService),
    current_user: UserIdentity = Depends(require_authenticated_user),
):
    _ = current_user
    try:
        similar_docs = await search_service.find_similar_documents(doc_id=doc_id, top_k=top_k)
        similar_docs = await asset_service.enrich_search_results(similar_docs)
        similar_docs = await contract_service.filter_deleted_results(similar_docs)
        return {
            "doc_id": doc_id,
            "similar_documents": similar_docs,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Find similar documents failed: {exc}") from exc


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_search_feedback(
    feedback: FeedbackRequest,
    current_user: UserIdentity = Depends(require_authenticated_user),
    feedback_service: SearchFeedbackService = Depends(SearchFeedbackService),
):
    try:
        return await feedback_service.submit_feedback(feedback, current_user)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Feedback submission failed: {exc}") from exc


async def _retrieve_results(
    request: SearchRequest,
    search_service: SearchService,
    asset_service: DocumentAssetService,
    contract_service: DocumentContractService | None = None,
):
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

    enriched_results = await asset_service.enrich_search_results(results)
    if contract_service is None or not hasattr(contract_service, "filter_deleted_results"):
        contract_service = DocumentContractService()
    return await contract_service.filter_deleted_results(enriched_results)


def _quota_status(quota_decision: DemoQuotaDecision | None):
    return quota_decision.quota if quota_decision else None


async def _consume_visitor_generation_quota(
    request: SearchRequest,
    current_user,
    quota_service,
) -> DemoQuotaDecision | None:
    if not request.use_generation or getattr(current_user, "role", None) != "visitor":
        return None

    visitor_id = getattr(current_user, "visitor_id", None)
    ip_hash = getattr(current_user, "ip_hash", None)
    if not visitor_id or not ip_hash:
        return DemoQuotaDecision(
            allowed=False,
            quota=quota_service._unavailable_status(),
            reason="visitor_identity_missing",
        )

    return await quota_service.consume_generation(visitor_id, ip_hash)
