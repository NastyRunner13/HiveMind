"""
Pydantic schemas for Channel API responses.

These schemas define the shape of data returned by the API.
They are separate from the SQLAlchemy models to decouple
the database layer from the API contract.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.channel import ChannelType
from app.models.identity import Platform


class ChannelResponse(BaseModel):
    """Channel data returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slack_channel_id: str
    platform: Platform = Platform.SLACK
    external_channel_id: str | None = None
    workspace_integration_id: uuid.UUID | None = None
    name: str
    channel_type: ChannelType
    topic: str | None = None
    purpose: str | None = None
    is_archived: bool = False
    member_count: int = 0
    last_synced_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ChannelListResponse(BaseModel):
    """Paginated list of channels."""

    channels: list[ChannelResponse]
    total: int
    page: int
    page_size: int
    has_more: bool


class ChannelSyncResponse(BaseModel):
    """Response from a channel sync operation."""

    synced_count: int
    new_count: int
    updated_count: int
    message: str
