"""
Chat request and response models.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from .search_models import DocumentResult, FollowUpContext


class ChatToolTrace(BaseModel):
    """Trace metadata for a tool decision made during chat orchestration."""

    tool_name: str = Field(..., description="Logical tool name, such as search_documents.")
    used: bool = Field(..., description="Whether the tool was actually invoked.")
    reason: Optional[str] = Field(None, description="Why the tool was or was not used.")
    query: Optional[str] = Field(None, description="Tool query when a search tool is invoked.")
    result_count: Optional[int] = Field(None, ge=0, description="Number of results returned by the tool.")


class ChatRequest(BaseModel):
    """Chat request payload."""

    message: str = Field(..., min_length=1, max_length=1000, description="User message.")
    conversation_id: Optional[str] = Field(None, description="Optional client conversation id.")
    history: List[Dict[str, str]] = Field(default_factory=list, description="Prior conversation turns.")
    follow_up_context: Optional[FollowUpContext] = Field(
        None,
        description="Optional resolved document follow-up context from the client.",
    )
    top_k: int = Field(5, ge=1, le=20, description="Maximum number of document references to return.")


class ChatResponse(BaseModel):
    """Chat response payload."""

    message: str = Field(..., description="Assistant response content.")
    conversation_id: str = Field(..., description="Conversation id.")
    references: List[DocumentResult] = Field(default_factory=list, description="Document references when retrieval was used.")
    timestamp: datetime = Field(default_factory=datetime.now, description="Response timestamp.")
    tool_trace: Optional[List[ChatToolTrace]] = Field(None, description="Optional tool decision trace.")
    mode: Literal["direct", "search", "follow_up"] = Field(
        "direct",
        description="High-level chat handling mode used for the response.",
    )
