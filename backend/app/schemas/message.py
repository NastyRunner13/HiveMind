"""
Pydantic schemas for Message API responses.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.identity import Platform
from app.models.message import MessageType


class MessageSenderResponse(BaseModel):
    """Minimal sender info included in message responses."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slack_user_id: str
    display_name: str
    avatar_url: str | None = None


class MessageResponse(BaseModel):
    """Message data returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    channel_id: uuid.UUID
    slack_message_ts: str
    thread_ts: str | None = None
    platform: Platform = Platform.SLACK
    external_message_id: str | None = None
    external_thread_id: str | None = None
    content: str
    message_type: MessageType
    has_attachments: bool = False
    has_files: bool = False
    reaction_count: int = 0
    reply_count: int = 0
    is_edited: bool = False
    slack_sent_at: datetime
    sent_at: datetime | None = None
    created_at: datetime

    # Nested sender info (populated via relationship)
    sender: MessageSenderResponse | None = None


class MessageListResponse(BaseModel):
    """Paginated list of messages."""

    messages: list[MessageResponse]
    total: int
    page: int
    page_size: int
    has_more: bool


class MessageSearchResponse(BaseModel):
    """Search results for messages."""

    results: list[MessageResponse]
    query: str
    total: int
    page: int
    page_size: int
