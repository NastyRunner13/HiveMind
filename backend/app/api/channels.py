"""
Channel API Endpoints — list, retrieve, and sync channels.

Provides:
- GET /api/v1/channels — paginated channel list
- GET /api/v1/channels/{channel_id} — single channel details
- POST /api/v1/channels/sync — trigger manual Slack sync
"""

import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.channel import ChannelType
from app.schemas.channel import (
    ChannelListResponse,
    ChannelResponse,
    ChannelSyncResponse,
)
from app.services.channel_service import get_channel_by_id, list_channels

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()


@router.get("", response_model=ChannelListResponse)
async def list_all_channels(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page"),
    channel_type: ChannelType | None = Query(
        None, description="Filter by channel type"
    ),
    include_archived: bool = Query(
        False, description="Include archived channels"
    ),
    db: AsyncSession = Depends(get_db),
) -> ChannelListResponse:
    """
    List all synced channels with pagination and filtering.

    Supports filtering by channel type (public, private, dm, group_dm)
    and optionally including archived channels.
    """
    channels, total = await list_channels(
        session=db,
        page=page,
        page_size=page_size,
        channel_type=channel_type,
        include_archived=include_archived,
    )

    return ChannelListResponse(
        channels=[ChannelResponse.model_validate(ch) for ch in channels],
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total,
    )


@router.get("/{channel_id}", response_model=ChannelResponse)
async def get_channel(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ChannelResponse:
    """Get a single channel by its internal ID."""
    channel = await get_channel_by_id(db, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")

    return ChannelResponse.model_validate(channel)


@router.post("/sync", response_model=ChannelSyncResponse)
async def sync_channels_from_slack(
    db: AsyncSession = Depends(get_db),
) -> ChannelSyncResponse:
    """
    Trigger a manual sync of channels from Slack.

    Fetches all channels the bot is a member of and upserts them
    into the database. Useful for initial setup or manual refresh.
    """
    from app.slack.bot import get_slack_app

    slack_app = get_slack_app()
    if slack_app is None:
        raise HTTPException(
            status_code=503,
            detail="Slack bot is not connected. Check your Slack configuration.",
        )

    from app.slack.sync import sync_channels, sync_users

    # Sync channels and users
    try:
        channel_stats = await sync_channels(slack_app.client)
        user_stats = await sync_users(slack_app.client)

        return ChannelSyncResponse(
            synced_count=channel_stats["synced"],
            new_count=channel_stats["new"],
            updated_count=channel_stats["updated"],
            message=(
                f"Synced {channel_stats['synced']} channels "
                f"({channel_stats['new']} new, {channel_stats['updated']} updated). "
                f"Also synced {user_stats['synced']} users."
            ),
        )
    except Exception as e:
        logger.error(f"Channel sync failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Sync failed: {str(e)}",
        )
