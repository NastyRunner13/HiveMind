"""Authenticated generation and retrieval endpoints for channel digests."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.channel import Channel, ChannelType
from app.models.digest import Digest
from app.models.workspace import Workspace
from app.schemas.digest import DigestGenerateRequest, DigestListResponse, DigestResponse
from app.security.auth import AuthenticatedPrincipal, get_current_principal
from app.services.authorization_service import (
    get_member_channel_ids,
    require_channel_access,
)
from app.services.digest_service import digest_service

router = APIRouter(prefix="/digests", tags=["Daily Digest"])


def _response(digest: Digest) -> DigestResponse:
    return DigestResponse.model_validate(digest)


@router.post("/generate", response_model=DigestListResponse)
async def generate_digest(
    request: DigestGenerateRequest,
    session: AsyncSession = Depends(get_db),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> DigestListResponse:
    """Generate public or explicitly authorized private-channel digests."""
    workspace = await session.get(Workspace, principal.workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    if request.channel_name:
        result = await session.execute(
            select(Channel).where(
                Channel.name.ilike(f"%{request.channel_name}%"),
                Channel.workspace_id == principal.workspace_id,
            )
        )
        channel = result.scalar_one_or_none()
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")
        await require_channel_access(session, principal, channel.id)
        digest = await digest_service.generate_channel_digest(
            channel_id=channel.id,
            workspace_id=principal.workspace_id,
            hours=request.hours,
        )
        digests = [digest] if digest else []
    else:
        digests = await digest_service.generate_daily_digest(
            workspace_id=principal.workspace_id,
            hours=request.hours,
        )
    return DigestListResponse(
        digests=[_response(digest) for digest in digests], total=len(digests)
    )


@router.get("", response_model=DigestListResponse)
async def list_digests(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> DigestListResponse:
    """List public and membership-authorized stored digests in the workspace."""
    member_ids = await get_member_channel_ids(session, principal)
    result = await session.execute(
        select(Digest)
        .outerjoin(Channel, Digest.channel_id == Channel.id)
        .where(
            Digest.workspace_id == principal.workspace_id,
            or_(
                Digest.channel_id.is_(None),
                Channel.channel_type == ChannelType.PUBLIC,
                and_(
                    Digest.channel_id.in_(member_ids),
                    Channel.channel_type.notin_([ChannelType.DM, ChannelType.GROUP_DM]),
                ),
            ),
        )
        .order_by(Digest.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    digests = list(result.scalars().all())
    return DigestListResponse(
        digests=[_response(digest) for digest in digests], total=len(digests)
    )


@router.get("/{digest_id}", response_model=DigestResponse)
async def get_digest(
    digest_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> DigestResponse:
    """Get a stored digest only where the source channel is authorized."""
    digest = await session.get(Digest, digest_id)
    if digest is None or digest.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Digest not found")
    if digest.channel_id:
        await require_channel_access(session, principal, digest.channel_id)
    return _response(digest)
