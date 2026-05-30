"""
Knowledge Fabric Pydantic schemas — request/response models for search API.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.models.embedding import SourceType


class SearchRequest(BaseModel):
    """Request body for semantic search."""

    query: str = Field(
        ..., min_length=1, max_length=1000, description="Natural language search query"
    )
    top_k: int = Field(
        default=10, ge=1, le=50, description="Number of results to return"
    )
    since: datetime | None = Field(
        default=None, description="Optional inclusive source timestamp lower bound"
    )
    until: datetime | None = Field(
        default=None, description="Optional inclusive source timestamp upper bound"
    )
    source_types: list[SourceType] | None = Field(
        default=None, description="Optional source type filters"
    )
    channel_ids: list[uuid.UUID] | None = Field(
        default=None, description="Optional source channel UUID filters"
    )

    @model_validator(mode="after")
    def validate_time_window(self) -> "SearchRequest":
        if self.since and self.until and self.until < self.since:
            raise ValueError("until must be greater than or equal to since")
        return self


class SearchResultItem(BaseModel):
    """A single search result with source attribution."""

    chunk_id: uuid.UUID
    content: str
    score: float = Field(description="Relevance score (0-1, higher is better)")
    source_type: str
    source_id: uuid.UUID
    source_channel_id: str | None = None
    source_channel_uuid: uuid.UUID | None = None
    source_channel_name: str | None = None
    source_created_at: datetime | None = None
    source_updated_at: datetime | None = None
    source_author_id: uuid.UUID | None = None
    source_author_external_id: str | None = None
    source_author_display_name: str | None = None
    source_thread_id: str | None = None
    source_permalink: str | None = None
    retrieval_method: str = "vector"
    chunk_index: int


class SearchResponse(BaseModel):
    """Response from the semantic search endpoint."""

    query: str
    results: list[SearchResultItem]
    total_results: int


class IndexingStatusResponse(BaseModel):
    """Response from the indexing status endpoint."""

    total_chunks: int
    by_source_type: dict[str, int]
    embedding_model: str
    embedding_dimensions: int
