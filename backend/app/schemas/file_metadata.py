"""
Pydantic schemas for FileMetadata API responses.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class FileOwnerResponse(BaseModel):
    """Minimal owner info for file responses."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slack_user_id: str
    display_name: str


class FileMetadataResponse(BaseModel):
    """File metadata returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slack_file_id: str
    filename: str
    title: str | None = None
    filetype: str
    mimetype: str
    size_bytes: int
    permalink: str | None = None
    shares_count: int = 1
    is_external: bool = False
    slack_created_at: datetime | None = None
    created_at: datetime

    # Nested info
    shared_by: FileOwnerResponse | None = None
    channel_id: uuid.UUID | None = None


class FileListResponse(BaseModel):
    """Paginated list of file metadata."""

    files: list[FileMetadataResponse]
    total: int
    page: int
    page_size: int
    has_more: bool
