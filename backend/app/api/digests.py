"""
Digest API — endpoints for generating and viewing channel summaries.

Provides on-demand digest generation and historical digest retrieval.
Daily digest scheduling is handled by the SchedulerService.

Security:
- list_digests and get_digest filter out private-channel digests
  (defense-in-depth — personalized digests should not be stored,
  but this prevents leaks if they are stored by other code paths).
- generate_digest requires membership verification for private channels.
"""

import logging
import uuid

from fastapi import APIRouter, Header, HTTPException, Query
from sqlalchemy import or_, select

from app.database import AsyncSessionLocal
from app.models.channel import Channel, ChannelType
from app.models.digest import Digest
from app.models.workspace import Workspace
from app.schemas.digest import (
    DigestGenerateRequest,
    DigestListResponse,
    DigestResponse,
)
from app.services.digest_service import digest_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/digests", tags=["Daily Digest"])


@router.post(
    "/generate",
    response_model=DigestListResponse,
    summary="Generate an on-demand digest",
)
async def generate_digest(
    request: DigestGenerateRequest,
    x_slack_user_id: str = Header(
        default=None,
        alias="X-Slack-User-Id",
        description="Slack user ID — required for private channel digests",
    ),
) -> DigestListResponse:
    """
    Generate a digest on demand.

    If channel_name is provided, generates a digest for that specific
    channel. Otherwise, generates digests for all active channels.

    Private channels require the X-Slack-User-Id header and membership
    verification before a digest can be generated.
    """
    async with AsyncSessionLocal() as session:
        # Get workspace
        result = await session.execute(
            select(Workspace).where(Workspace.is_active.is_(True)).limit(1)
        )
        workspace = result.scalar_one_or_none()
        if not workspace:
            raise HTTPException(status_code=404, detail="No active workspace found")

        if request.channel_name:
            # Generate for a specific channel
            ch_result = await session.execute(
                select(Channel).where(
                    Channel.name.ilike(f"%{request.channel_name}%"),
                    Channel.workspace_id == workspace.id,
                )
            )
            channel = ch_result.scalar_one_or_none()
            if not channel:
                raise HTTPException(
                    status_code=404,
                    detail=f"Channel '{request.channel_name}' not found",
                )

            # ACL: block private-channel digest if user is not a member
            if channel.channel_type != ChannelType.PUBLIC:
                if not x_slack_user_id:
                    raise HTTPException(
                        status_code=403,
                        detail="Authentication required for private channel digests",
                    )
                from app.services.membership_service import membership_service

                user_channels = await membership_service.get_user_channel_ids(
                    x_slack_user_id
                )
                if channel.slack_channel_id not in user_channels:
                    raise HTTPException(
                        status_code=403,
                        detail="You are not a member of this channel",
                    )

            digest = await digest_service.generate_channel_digest(
                channel_id=channel.id,
                workspace_id=workspace.id,
                hours=request.hours,
            )
            digests = [digest] if digest else []
        else:
            # Generate for all channels (public only — enforced by service)
            digests = await digest_service.generate_daily_digest(
                workspace_id=workspace.id,
            )

    return DigestListResponse(
        digests=[
            DigestResponse(
                id=d.id,
                workspace_id=d.workspace_id,
                channel_id=d.channel_id,
                digest_type=d.digest_type.value,
                content=d.content,
                message_count=d.message_count,
                time_range_start=d.time_range_start,
                time_range_end=d.time_range_end,
                generated_by=d.generated_by,
                created_at=d.created_at,
            )
            for d in digests
        ],
        total=len(digests),
    )


@router.get(
    "",
    response_model=DigestListResponse,
    summary="List past digests",
)
async def list_digests(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> DigestListResponse:
    """List past digests, most recent first.

    Only returns digests from PUBLIC channels (or workspace-level
    digests with no channel). This is defense-in-depth — personalized
    digests should not be stored in the DB, but this filter prevents
    leaks if private-channel digests exist from legacy code paths.
    """
    async with AsyncSessionLocal() as session:
        # Filter: only public-channel digests or workspace-level (no channel)
        query = (
            select(Digest)
            .outerjoin(Channel, Digest.channel_id == Channel.id)
            .where(
                or_(
                    Digest.channel_id.is_(None),
                    Channel.channel_type == ChannelType.PUBLIC,
                )
            )
            .order_by(Digest.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await session.execute(query)
        digests = result.scalars().all()

        return DigestListResponse(
            digests=[
                DigestResponse(
                    id=d.id,
                    workspace_id=d.workspace_id,
                    channel_id=d.channel_id,
                    digest_type=d.digest_type.value,
                    content=d.content,
                    message_count=d.message_count,
                    time_range_start=d.time_range_start,
                    time_range_end=d.time_range_end,
                    generated_by=d.generated_by,
                    created_at=d.created_at,
                )
                for d in digests
            ],
            total=len(digests),
        )


@router.get(
    "/{digest_id}",
    response_model=DigestResponse,
    summary="Get a specific digest",
)
async def get_digest(digest_id: uuid.UUID) -> DigestResponse:
    """Get a specific digest by its ID.

    Returns 404 for private-channel digests (defense-in-depth).
    """
    async with AsyncSessionLocal() as session:
        digest = await session.get(Digest, digest_id)
        if not digest:
            raise HTTPException(status_code=404, detail="Digest not found")

        # Block access to private-channel digests (defense-in-depth)
        if digest.channel_id:
            channel = await session.get(Channel, digest.channel_id)
            if channel and channel.channel_type != ChannelType.PUBLIC:
                raise HTTPException(status_code=404, detail="Digest not found")

        return DigestResponse(
            id=digest.id,
            workspace_id=digest.workspace_id,
            channel_id=digest.channel_id,
            digest_type=digest.digest_type.value,
            content=digest.content,
            message_count=digest.message_count,
            time_range_start=digest.time_range_start,
            time_range_end=digest.time_range_end,
            generated_by=digest.generated_by,
            created_at=digest.created_at,
        )
