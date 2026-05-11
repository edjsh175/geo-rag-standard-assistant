"""
Search request and response models.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class SpatialFilter(BaseModel):
    """Spatial filtering for search results."""

    geometry: Optional[Dict[str, Any]] = None
    distance: Optional[float] = Field(None, description="Distance in meters.")
    spatial_relation: str = Field("within", description="within, intersects, or near")


class MetadataFilter(BaseModel):
    """Metadata filtering for search results."""

    document_type: Optional[str] = None
    source: Optional[str] = None
    year: Optional[int] = None
    region: Optional[str] = None
    keywords: Optional[List[str]] = None
    custom_filters: Optional[Dict[str, Any]] = None


class DocumentResult(BaseModel):
    """A single search result document."""

    id: str = Field(..., description="Document identifier.")
    title: str = Field(..., description="Document title.")
    content: str = Field(..., description="Snippet or summary content.")
    similarity: float = Field(..., ge=0, le=1, description="Similarity score.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadata payload.")
    spatial_info: Optional[Dict[str, Any]] = Field(None, description="Optional spatial metadata.")
    file_type: str = Field(..., description="File extension or logical type.")
    file_size: int = Field(..., description="File size in bytes.")
    upload_time: datetime = Field(..., description="Upload or import timestamp.")
    source_url: Optional[str] = Field(None, description="Legacy source URL field.")
    download_available: bool = Field(False, description="Whether the original file can be downloaded.")
    download_url: Optional[str] = Field(None, description="Authenticated download URL.")

    @field_validator("id", mode="before")
    @classmethod
    def coerce_id_to_str(cls, value: Any) -> str:
        return str(value)


class FollowUpCandidateDocument(BaseModel):
    """A candidate document that can be referenced by a follow-up question."""

    id: str = Field(..., description="Document identifier shown to the user.")
    title: str = Field(..., description="Document title shown to the user.")
    rank: int = Field(..., ge=1, description="1-based rank from the previous assistant reply.")


class FollowUpContext(BaseModel):
    """Client-provided context for document-specific follow-up questions."""

    target_document_id: Optional[str] = Field(None, description="Resolved follow-up target document id.")
    candidate_documents: List[FollowUpCandidateDocument] = Field(
        default_factory=list,
        description="Candidate documents from the previous assistant response.",
    )
    resolution_source: Optional[Literal["explicit_text", "ordinal", "selected_document"]] = Field(
        None,
        description="How the client resolved the follow-up target.",
    )


class SearchRequest(BaseModel):
    """Search request payload."""

    query: str = Field(..., min_length=1, max_length=1000, description="Search query.")
    top_k: int = Field(10, ge=1, le=100, description="Maximum number of results.")
    threshold: float = Field(0.7, ge=0, le=1, description="Similarity threshold.")
    spatial_filter: Optional[SpatialFilter] = Field(None, description="Optional spatial filter.")
    metadata_filter: Optional[MetadataFilter] = Field(None, description="Optional metadata filter.")
    use_rerank: bool = Field(True, description="Whether to rerank results.")
    search_mode: str = Field("hybrid", description="semantic, keyword, or hybrid")
    use_generation: bool = Field(False, description="Whether to generate a natural-language answer.")
    stream: bool = Field(False, description="Whether to stream the generated answer with SSE.")
    history: Optional[List[Dict[str, str]]] = Field(default_factory=list, description="Conversation history.")
    follow_up_context: Optional[FollowUpContext] = Field(
        None,
        description="Optional document follow-up context resolved on the client.",
    )


class SearchResponse(BaseModel):
    """Search response payload."""

    query: str = Field(..., description="Original query.")
    results: List[DocumentResult] = Field(default_factory=list, description="Matched results.")
    total_count: int = Field(0, description="Total number of results.")
    search_time: float = Field(0.0, description="Search duration in seconds.")
    search_mode: str = Field("hybrid", description="Search mode used.")
    suggestions: Optional[List[str]] = Field(None, description="Suggested related queries.")
    generated_answer: Optional[str] = Field(None, description="Generated answer, if requested.")
    generation_time: Optional[float] = Field(None, description="Generation duration in seconds.")


class SearchHistory(BaseModel):
    """Stored search history entry."""

    id: str = Field(..., description="History identifier.")
    query: str = Field(..., description="Search query.")
    results_count: int = Field(..., description="Number of results returned.")
    search_time: datetime = Field(..., description="When the search ran.")
    user_id: Optional[str] = Field(None, description="Optional user identifier.")
    session_id: Optional[str] = Field(None, description="Optional session identifier.")


class SearchStatistic(BaseModel):
    """Aggregate search statistics."""

    total_searches: int = Field(0, description="Total search count.")
    average_results: float = Field(0.0, description="Average result count.")
    popular_queries: List[Dict[str, Any]] = Field(default_factory=list, description="Popular query samples.")
    search_trends: Dict[str, int] = Field(default_factory=dict, description="Search trend counters.")


class FeedbackRequest(BaseModel):
    """Feedback payload for a search result."""

    query: str = Field(..., description="Original query.")
    result_id: str = Field(..., description="Selected result identifier.")
    feedback_type: str = Field(..., description="relevant, irrelevant, helpful, or not_helpful")
    comment: Optional[str] = Field(None, description="Optional feedback comment.")
    rating: Optional[int] = Field(None, ge=1, le=5, description="Optional rating score.")
