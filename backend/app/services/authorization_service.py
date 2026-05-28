"""Authorization checks based on canonical users and channel memberships."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.channel import Channel, ChannelType
from app.models.membership import ChannelMembership
from app.security.auth import AuthenticatedPrincipal


async def get_member_channel_ids(
    session: AsyncSession, principal: AuthenticatedPrincipal
) -> list[uuid.UUID]:
    """Return canonical channel IDs for active memberships of a principal."""
    conditions = [ChannelMembership.canonical_user_id == principal.user_id]
    if principal.slack_user_id:
        conditions.append(ChannelMembership.slack_user_id == principal.slack_user_id)
    result = await session.execute(
        select(ChannelMembership.channel_id).where(
            ChannelMembership.workspace_id == principal.workspace_id,
            ChannelMembership.is_active.is_(True),
            or_(*conditions),
        )
    )
    return [row[0] for row in result.all()]


async def require_channel_access(
    session: AsyncSession,
    principal: AuthenticatedPrincipal,
    channel_id: uuid.UUID,
) -> Channel:
    """Load a channel and ensure the principal can read its content."""
    result = await session.execute(
        select(Channel).where(
            Channel.id == channel_id,
            Channel.workspace_id == principal.workspace_id,
        )
    )
    channel = result.scalar_one_or_none()
    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found"
        )

    if channel.channel_type == ChannelType.PUBLIC:
        return channel

    member_channel_ids = await get_member_channel_ids(session, principal)
    if channel.id not in member_channel_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Channel access denied"
        )
    return channel


async def accessible_channel_condition(
    session: AsyncSession, principal: AuthenticatedPrincipal
):
    """Build a SQL condition for channels readable by the principal."""
    member_ids = await get_member_channel_ids(session, principal)
    return and_(
        Channel.workspace_id == principal.workspace_id,
        or_(Channel.channel_type == ChannelType.PUBLIC, Channel.id.in_(member_ids)),
    )
