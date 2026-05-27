"""
Digest Pydantic schemas — request/response models for the digest API.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class DigestResponse(BaseModel):
    """Response schema for a single digest."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    channel_id: uuid.UUID | None = None
    digest_type: str
    content: str
    message_count: int
    time_range_start: datetime
    time_range_end: datetime
    generated_by: str
    created_at: datetime

    model_config = {"from_attributes": True}


class DigestListResponse(BaseModel):
    """Response schema for listing digests."""

    digests: list[DigestResponse]
    total: int


class DigestGenerateRequest(BaseModel):
    """Request to generate an on-demand digest."""

    channel_name: str | None = Field(
        default=None,
        description="Channel name to generate digest for (all channels if empty)",
    )
    hours: int = Field(
        default=24,
        ge=1,
        le=168,
        description="Hours of history to summarize (1-168)",
    )
