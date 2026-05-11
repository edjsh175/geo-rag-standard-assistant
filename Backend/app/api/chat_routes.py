"""
Chat API routes.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.security import require_authenticated_admin
from app.models.chat_models import ChatRequest, ChatResponse
from app.services.chat_service import ChatService
from app.services.document_asset_service import DocumentAssetService
from app.services.search_service import SearchService

logger = logging.getLogger(__name__)

public_router = APIRouter()
router = APIRouter(dependencies=[Depends(require_authenticated_admin)])


class HealthCheckResponse(BaseModel):
    status: str
    service: str


@public_router.get("/health", response_model=HealthCheckResponse)
async def health_check() -> HealthCheckResponse:
    return HealthCheckResponse(status="healthy", service="chat")


@router.post("/query", response_model=ChatResponse)
async def chat_query(
    request: ChatRequest,
    search_service: SearchService = Depends(SearchService),
    asset_service: DocumentAssetService = Depends(DocumentAssetService),
) -> ChatResponse:
    try:
        chat_service = ChatService(search_service=search_service, asset_service=asset_service)
        return await chat_service.handle_chat(request)
    except Exception as exc:
        logger.error("Chat request failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Chat failed: {exc}") from exc
