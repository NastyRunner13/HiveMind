"""
Knowledge API — semantic search and indexing status endpoints.

These endpoints expose the Knowledge Fabric's search capabilities.
All search queries are ACL-filtered at the database level.

ACL context is derived server-side — callers cannot supply their own
identity or channel memberships. The X-Slack-User-Id header is set
by the Slack bot internally (not exposed to end users).
"""

import logging

from fastapi import APIRouter, Header, HTTPException

from app.schemas.knowledge import (
    IndexingStatusResponse,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
)
from app.services.knowledge_service import knowledge_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge", tags=["Knowledge Fabric"])


@router.post(
    "/search",
    response_model=SearchResponse,
    summary="Semantic search across the Knowledge Fabric",
)
async def search_knowledge(
    request: SearchRequest,
    x_slack_user_id: str = Header(
        default=None,
        alias="X-Slack-User-Id",
        description="Slack user ID — set by the bot, not user-supplied",
    ),
) -> SearchResponse:
    """
    Search the Knowledge Fabric using natural language.

    Results are filtered by ACL metadata — only chunks the requesting
    user has access to are returned. Channel memberships are derived
    server-side from the database, never from client input.
    """
    # Derive channel memberships from DB — NOT from client
    user_channel_ids = None
    user_slack_id = x_slack_user_id

    if user_slack_id:
        from app.services.membership_service import membership_service

        user_channel_ids = await membership_service.get_user_channel_ids(
            user_slack_id
        )

    results = await knowledge_service.search(
        query=request.query,
        user_channel_ids=user_channel_ids,
        user_slack_id=user_slack_id,
        top_k=request.top_k,
    )

    return SearchResponse(
        query=request.query,
        results=[
            SearchResultItem(
                chunk_id=r.chunk_id,
                content=r.content,
                score=r.score,
                source_type=r.source_type,
                source_id=r.source_id,
                source_channel_id=r.source_channel_id,
                chunk_index=r.chunk_index,
            )
            for r in results
        ],
        total_results=len(results),
    )


@router.get(
    "/status",
    response_model=IndexingStatusResponse,
    summary="Get Knowledge Fabric indexing status",
)
async def get_indexing_status() -> IndexingStatusResponse:
    """Get statistics about the indexing state of the Knowledge Fabric."""
    status = await knowledge_service.get_indexing_status()
    return IndexingStatusResponse(**status)
