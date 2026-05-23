"""
Channel Service — business logic for channel queries.

Provides paginated, filtered access to channel data.
Used by the API layer for channel-related endpoints.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.channel import Channel, ChannelType


async def list_channels(
    session: AsyncSession,
    page: int = 1,
    page_size: int = 50,
    channel_type: ChannelType | None = None,
    include_archived: bool = False,
) -> tuple[list[Channel], int]:
    """
    List channels with pagination and filtering.

    Returns:
        Tuple of (channels list, total count)
    """
    query = select(Channel)
    count_query = select(func.count(Channel.id))

    # Apply filters
    if not include_archived:
        query = query.where(Channel.is_archived.is_(False))
        count_query = count_query.where(Channel.is_archived.is_(False))

    if channel_type:
        query = query.where(Channel.channel_type == channel_type)
        count_query = count_query.where(Channel.channel_type == channel_type)

    # Get total count
    total_result = await session.execute(count_query)
    total = total_result.scalar()

    # Apply pagination
    offset = (page - 1) * page_size
    query = query.order_by(Channel.name).offset(offset).limit(page_size)

    result = await session.execute(query)
    channels = list(result.scalars().all())

    return channels, total


async def get_channel_by_id(
    session: AsyncSession, channel_id: uuid.UUID
) -> Channel | None:
    """Get a single channel by its internal UUID."""
    result = await session.execute(
        select(Channel).where(Channel.id == channel_id)
    )
    return result.scalar_one_or_none()


async def get_channel_by_slack_id(
    session: AsyncSession, slack_channel_id: str
) -> Channel | None:
    """Get a single channel by its Slack channel ID."""
    result = await session.execute(
        select(Channel).where(Channel.slack_channel_id == slack_channel_id)
    )
    return result.scalar_one_or_none()
