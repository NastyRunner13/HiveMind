"""Authenticated Knowledge Fabric search and status endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.knowledge import (
    IndexingStatusResponse,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
)
from app.security.auth import AuthenticatedPrincipal, get_current_principal
from app.services.authorization_service import get_member_channel_ids
from app.services.knowledge_service import knowledge_service

router = APIRouter(prefix="/knowledge", tags=["Knowledge Fabric"])


@router.post("/search", response_model=SearchResponse)
async def search_knowledge(
    request: SearchRequest,
    session: AsyncSession = Depends(get_db),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> SearchResponse:
    """Search knowledge using UUID-based ACL context from verified identity."""
    user_channel_uuids = await get_member_channel_ids(session, principal)
    results = await knowledge_service.search(
        query=request.query,
        user_channel_uuids=user_channel_uuids,
        user_id=principal.user_id,
        workspace_id=principal.workspace_id,
        top_k=request.top_k,
    )
    return SearchResponse(
        query=request.query,
        results=[
            SearchResultItem(
                chunk_id=result.chunk_id,
                content=result.content,
                score=result.score,
                source_type=result.source_type,
                source_id=result.source_id,
                source_channel_id=result.source_channel_id,
                source_channel_uuid=result.source_channel_uuid,
                chunk_index=result.chunk_index,
            )
            for result in results
        ],
        total_results=len(results),
    )


@router.get("/status", response_model=IndexingStatusResponse)
async def get_indexing_status(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> IndexingStatusResponse:
    """Get indexing statistics scoped to the authenticated workspace."""
    status = await knowledge_service.get_indexing_status(
        workspace_id=principal.workspace_id
    )
    return IndexingStatusResponse(**status)
