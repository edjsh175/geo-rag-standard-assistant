"""
Search API routes.
"""

from __future__ import annotations

from datetime import datetime
import json
import logging
from types import SimpleNamespace
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.auth import UserIdentity
from app.core.database import db_manager
from app.core.security import require_authenticated_user
from app.models.problem_details import ProblemDetails
from app.models.search_models import (
    AgentCancelRequest,
    AgentCancelResponse,
    FeedbackRequest,
    FeedbackResponse,
    FollowUpContext,
    SearchRequest,
    SearchResponse,
)
from app.core.llm_config import llm_config
from app.services.agent.answer_generator import AnswerGenerator
from app.services.agent.conversation_memory import ConversationMemorySummarizer
from app.services.agent.controller import MainController
from app.services.agent.dependencies import get_agent_store
from app.services.agent.distributed_lock import (
    PostgresAdvisorySessionLock,
    SessionLockAcquisitionError,
)
from app.services.agent.events import AgentEvent
from app.services.agent.event_projection import public_event_payload
from app.services.agent.model_client import LLMConfigStageModelClient, ModelCallAudit
from app.services.agent.provider_health import ProviderHealthService
from app.services.agent.reviewer import GroundingReviewer
from app.services.agent.runtime import AgentRuntime
from app.services.agent.tools import build_default_tool_registry
from app.services.demo_quota_service import DemoQuotaDecision, DemoQuotaService, get_demo_quota_service
from app.services.document_contract_service import DocumentContractService
from app.services.document_asset_service import DocumentAssetService
from app.services.document_repository import DocumentRepository
from app.services.search_feedback_service import SearchFeedbackService
from app.services.search_application_service import (
    RELAXED_VECTOR_THRESHOLD,
    SearchApplicationService,
)
from app.services.search_service import SearchService
from app.services.spatial_service import SpatialService

logger = logging.getLogger(__name__)

public_router = APIRouter()
router = APIRouter()

_agent_session_store = get_agent_store()
_provider_health_service = ProviderHealthService()


class HealthCheckResponse(BaseModel):
    status: str
    service: str


def _build_search_application_service(
    *,
    search_service: SearchService,
    asset_service: DocumentAssetService,
    contract_service: DocumentContractService,
    document_repository: DocumentRepository | None = None,
) -> SearchApplicationService:
    async def _durable_call_audit_sink(
        audit: ModelCallAudit,
        audit_context: Mapping[str, Any] | None,
    ) -> None:
        if not audit_context:
            return
        principal_id = str(audit_context.get("principal_id") or "").strip()
        session_id = str(audit_context.get("session_id") or "").strip()
        turn_id = str(audit_context.get("turn_id") or "").strip()
        trace_id = str(audit_context.get("trace_id") or "").strip()
        if not principal_id or not session_id:
            return
        event = AgentEvent(
            event_type="model_call_audited",
            session_id=session_id,
            turn_id=turn_id or "turn-0",
            trace_id=trace_id,
            payload={
                "call_id": audit.call_id,
                "stage": audit.stage,
                "attempt": audit.attempt,
                "model_name": audit.model_name,
                "timeout_seconds": audit.timeout_seconds,
                "elapsed_seconds": audit.elapsed_seconds,
                "outcome": audit.outcome,
                "context_snapshot_id": audit_context.get("context_snapshot_id"),
                "frozen_evidence_snapshot_id": audit_context.get("frozen_evidence_snapshot_id"),
            },
        )
        if hasattr(_agent_session_store, "append_event"):
            try:
                await _agent_session_store.append_event(
                    principal_id=principal_id,
                    event=event,
                )
            except Exception as exc:
                logger.warning("Failed to persist model_call_audited event: %s", exc)

    retrieval_port = search_service.get_retrieval_port()
    model_client = LLMConfigStageModelClient(
        llm_config,
        audit_sink=_agent_session_store.save_model_input_audit,
        call_audit_sink=_durable_call_audit_sink,
    )
    controller = MainController(
        model_client=model_client,
        tool_registry=build_default_tool_registry(),
    )
    runtime = AgentRuntime(
        retrieval_port=retrieval_port,
        controller=controller,
        answer_generator=AnswerGenerator(model_client=model_client),
        reviewer=GroundingReviewer(model_client=model_client),
        conversation_memory_summarizer=ConversationMemorySummarizer(
            model_client=model_client
        ),
        session_store=_agent_session_store,
        session_lock=PostgresAdvisorySessionLock(
            manager=SimpleNamespace(postgres_engine=db_manager.postgres_lock_engine)
        ),
        spatial_service=SpatialService(),
        provider_health_provider=_provider_health_service,
    )
    return SearchApplicationService(
        search_service=search_service,
        asset_service=asset_service,
        contract_service=contract_service,
        agent_runtime=runtime,
        retrieval_port=retrieval_port,
        document_repository=document_repository,
    )


def get_search_application_service(
    search_service: SearchService = Depends(SearchService),
    asset_service: DocumentAssetService = Depends(DocumentAssetService),
    contract_service: DocumentContractService = Depends(DocumentContractService),
    document_repository: DocumentRepository = Depends(DocumentRepository),
) -> SearchApplicationService:
    return _build_search_application_service(
        search_service=search_service,
        asset_service=asset_service,
        contract_service=contract_service,
        document_repository=document_repository,
    )


@public_router.get("/health", response_model=HealthCheckResponse)
async def health_check() -> HealthCheckResponse:
    return HealthCheckResponse(status="healthy", service="search")


@router.post("/query", response_model=SearchResponse)
async def search_documents(
    request: SearchRequest,
    current_user: UserIdentity = Depends(require_authenticated_user),
    application_service: SearchApplicationService = Depends(get_search_application_service),
    quota_service: DemoQuotaService = Depends(get_demo_quota_service),
):
    try:
        quota_decision = await _consume_visitor_generation_quota(
            request,
            current_user,
            quota_service,
        )
        generation_allowed = request.use_generation and (
            quota_decision is None or quota_decision.allowed
        )
        response = await application_service.execute(
            request,
            generation_allowed=generation_allowed,
            principal_id=_principal_id(current_user),
        )
        response.quota = _quota_status(quota_decision)
        return response
    except SessionLockAcquisitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
    application_service: SearchApplicationService = Depends(get_search_application_service),
    quota_service: DemoQuotaService = Depends(get_demo_quota_service),
):
    try:
        quota_decision = await _consume_visitor_generation_quota(
            request,
            current_user,
            quota_service,
        )
        generation_allowed = request.use_generation and (
            quota_decision is None or quota_decision.allowed
        )

        async def event_generator():
            fallback_sequence = 0
            try:
                async for frame in application_service.stream(
                    request,
                    generation_allowed=generation_allowed,
                    principal_id=_principal_id(current_user),
                ):
                    if frame.event is not None:
                        event = frame.event
                        fallback_sequence += 1
                        payload = {
                            "event_id": getattr(event, "event_id", "") or f"{event.session_id}:{event.turn_id}:{fallback_sequence}",
                            "sequence": getattr(event, "sequence", 0) or fallback_sequence,
                            "session_id": event.session_id,
                            "turn_id": event.turn_id,
                            "trace_id": event.trace_id,
                            "payload": public_event_payload(event.event_type, event.payload),
                            "created_at": event.created_at.isoformat(),
                        }
                        yield (
                            f"event: {event.event_type}\n"
                            f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                        )
                        continue

                    if frame.response is not None:
                        frame.response.quota = _quota_status(quota_decision)
                        payload = json.dumps(frame.response.model_dump(), ensure_ascii=False, default=str)
                        yield f"event: result\ndata: {payload}\n\n"
            except Exception as stream_exc:
                logging.getLogger(__name__).exception("SSE stream interrupted: %s", stream_exc)
                problem = ProblemDetails.from_status(
                    status_code=(
                        409
                        if isinstance(stream_exc, SessionLockAcquisitionError)
                        else 500
                    ),
                    detail=f"SSE stream interrupted: {stream_exc}",
                    instance="/api/search/query/stream",
                    type_uri="urn:geoai:error:stream",
                    title="Stream Execution Error",
                )
                yield f"event: error\ndata: {json.dumps(problem.to_response_dict(), ensure_ascii=False)}\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Stream search failed: {exc}") from exc


@router.post("/query/cancel", response_model=AgentCancelResponse)
async def cancel_agent_run(
    request: AgentCancelRequest,
    current_user: UserIdentity = Depends(require_authenticated_user),
    application_service: SearchApplicationService = Depends(get_search_application_service),
) -> AgentCancelResponse:
    try:
        event = await application_service.request_cancellation(
            principal_id=_principal_id(current_user),
            session_id=request.session_id,
            turn_id=request.turn_id,
            reason=request.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return AgentCancelResponse(
        session_id=request.session_id,
        turn_id=request.turn_id,
        event_id=event.event_id,
    )


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


def _principal_id(current_user: UserIdentity) -> str:
    if current_user.role == "visitor":
        if not current_user.visitor_id:
            raise RuntimeError("visitor identity is missing visitor_id")
        return f"visitor:{current_user.visitor_id}"
    return f"admin:{current_user.username}"
