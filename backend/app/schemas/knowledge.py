"""
Knowledge Fabric Pydantic schemas — request/response models for search API.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """Request body for semantic search."""

    query: str = Field(..., min_length=1, max_length=1000, description="Natural language search query")
    top_k: int = Field(default=10, ge=1, le=50, description="Number of results to return")


class SearchResultItem(BaseModel):
    """A single search result with source attribution."""

    chunk_id: uuid.UUID
    content: str
    score: float = Field(description="Relevance score (0-1, higher is better)")
    source_type: str
    source_id: uuid.UUID
    source_channel_id: str | None = None
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
