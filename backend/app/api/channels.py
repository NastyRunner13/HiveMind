"""Authenticated channel query and Slack synchronization endpoints."""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.channel import ChannelType
from app.models.workspace import Workspace
from app.schemas.channel import (
    ChannelListResponse,
    ChannelResponse,
    ChannelSyncResponse,
)
from app.security.auth import (
    AuthenticatedPrincipal,
    get_current_principal,
    require_admin,
)
from app.services.authorization_service import (
    get_member_channel_ids,
    require_channel_access,
)
from app.services.channel_service import list_channels

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", response_model=ChannelListResponse)
async def list_all_channels(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    channel_type: ChannelType | None = Query(None),
    include_archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> ChannelListResponse:
    """List channels visible to the authenticated workspace member."""
    member_channel_ids = await get_member_channel_ids(db, principal)
    channels, total = await list_channels(
        session=db,
        page=page,
        page_size=page_size,
        channel_type=channel_type,
        include_archived=include_archived,
        workspace_id=principal.workspace_id,
        member_channel_ids=member_channel_ids,
    )
    return ChannelListResponse(
        channels=[ChannelResponse.model_validate(channel) for channel in channels],
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total,
    )


@router.post("/sync", response_model=ChannelSyncResponse)
async def sync_channels_from_slack(
    db: AsyncSession = Depends(get_db),
    principal: AuthenticatedPrincipal = Depends(require_admin),
) -> ChannelSyncResponse:
    """Synchronize Slack records; only canonical administrators may invoke it."""
    from app.integrations.slack.connector import SlackConnector
    from app.slack.bot import get_slack_app

    slack_app = get_slack_app()
    if slack_app is None:
        raise HTTPException(status_code=503, detail="Slack bot is not connected")

    try:
        connector = SlackConnector(slack_app.client)
        user_stats = await connector.sync_users()
        channel_stats = await connector.sync_channels()
        workspace = await db.get(Workspace, principal.workspace_id)
        membership_msg = ""
        if workspace:
            stats = await connector.sync_memberships(workspace.id)
            membership_msg = (
                f" Synced memberships for {stats['channels_synced']} channels."
            )
        return ChannelSyncResponse(
            synced_count=channel_stats["synced"],
            new_count=channel_stats["new"],
            updated_count=channel_stats["updated"],
            message=(
                f"Synced {channel_stats['synced']} channels "
                f"({channel_stats['new']} new, {channel_stats['updated']} updated), "
                f"{user_stats['synced']} users.{membership_msg}"
            ),
        )
    except Exception as exc:
        logger.error("Channel sync failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Sync failed") from exc


@router.get("/{channel_id}", response_model=ChannelResponse)
async def get_channel(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> ChannelResponse:
    """Get a channel only when it is visible to the authenticated user."""
    channel = await require_channel_access(db, principal, channel_id)
    return ChannelResponse.model_validate(channel)
