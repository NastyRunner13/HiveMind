"""
Message & File API Endpoints — query ingested messages and file metadata.

Provides:
- GET /api/v1/channels/{channel_id}/messages — paginated message list
- GET /api/v1/messages/search — text search across all messages
- GET /api/v1/files — list indexed file metadata
"""

import uuid
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.database import get_db
from app.models.file_metadata import FileMetadata
from app.models.message import Message
from app.models.user import SlackUser
from app.schemas.file_metadata import FileListResponse, FileMetadataResponse
from app.schemas.message import (
    MessageListResponse,
    MessageResponse,
    MessageSearchResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()


@router.get(
    "/channels/{channel_id}/messages",
    response_model=MessageListResponse,
)
async def list_channel_messages(
    channel_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    since: datetime | None = Query(
        None, description="Only messages after this timestamp"
    ),
    until: datetime | None = Query(
        None, description="Only messages before this timestamp"
    ),
    threads_only: bool = Query(
        False, description="Only show thread-starting messages"
    ),
    db: AsyncSession = Depends(get_db),
) -> MessageListResponse:
    """
    Get messages for a specific channel, ordered by time (newest first).

    Supports:
    - Date range filtering (since/until)
    - Thread filtering (threads_only=true shows only parent messages)
    - Pagination
    - Includes sender info for each message
    """
    query = (
        select(Message)
        .where(Message.channel_id == channel_id)
        .options(selectinload(Message.sender))
    )
    count_query = select(func.count(Message.id)).where(
        Message.channel_id == channel_id
    )

    if since:
        query = query.where(Message.slack_sent_at >= since)
        count_query = count_query.where(Message.slack_sent_at >= since)

    if until:
        query = query.where(Message.slack_sent_at <= until)
        count_query = count_query.where(Message.slack_sent_at <= until)

    if threads_only:
        # Only messages that are NOT thread replies
        query = query.where(
            or_(
                Message.thread_ts.is_(None),
                Message.thread_ts == Message.slack_message_ts,
            )
        )
        count_query = count_query.where(
            or_(
                Message.thread_ts.is_(None),
                Message.thread_ts == Message.slack_message_ts,
            )
        )

    # Get total
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # Apply pagination — newest first
    offset = (page - 1) * page_size
    query = (
        query.order_by(Message.slack_sent_at.desc())
        .offset(offset)
        .limit(page_size)
    )

    result = await db.execute(query)
    messages = list(result.scalars().all())

    return MessageListResponse(
        messages=[MessageResponse.model_validate(m) for m in messages],
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total,
    )


@router.get("/messages/search", response_model=MessageSearchResponse)
async def search_messages(
    q: str = Query(..., min_length=2, description="Search query"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    channel_id: uuid.UUID | None = Query(
        None, description="Limit search to a specific channel"
    ),
    db: AsyncSession = Depends(get_db),
) -> MessageSearchResponse:
    """
    Search messages using PostgreSQL text search (ILIKE for now).

    Future improvement: switch to PostgreSQL full-text search (tsvector)
    or vector similarity search once embeddings are added.
    """
    search_pattern = f"%{q}%"

    query = (
        select(Message)
        .where(Message.content.ilike(search_pattern))
        .options(selectinload(Message.sender))
    )
    count_query = select(func.count(Message.id)).where(
        Message.content.ilike(search_pattern)
    )

    if channel_id:
        query = query.where(Message.channel_id == channel_id)
        count_query = count_query.where(Message.channel_id == channel_id)

    total_result = await db.execute(count_query)
    total = total_result.scalar()

    offset = (page - 1) * page_size
    query = (
        query.order_by(Message.slack_sent_at.desc())
        .offset(offset)
        .limit(page_size)
    )

    result = await db.execute(query)
    messages = list(result.scalars().all())

    return MessageSearchResponse(
        results=[MessageResponse.model_validate(m) for m in messages],
        query=q,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/files", response_model=FileListResponse)
async def list_files(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    channel_id: uuid.UUID | None = Query(
        None, description="Filter by channel"
    ),
    filetype: str | None = Query(
        None, description="Filter by file type (e.g., 'pdf', 'png')"
    ),
    shared_by: uuid.UUID | None = Query(
        None, description="Filter by user who shared the file"
    ),
    db: AsyncSession = Depends(get_db),
) -> FileListResponse:
    """
    List indexed file metadata with filtering.

    Note: This returns metadata only — file content is never stored.
    Files can be filtered by channel, type, or sharing user.
    """
    query = select(FileMetadata).options(
        selectinload(FileMetadata.shared_by)
    )
    count_query = select(func.count(FileMetadata.id))

    if channel_id:
        query = query.where(FileMetadata.channel_id == channel_id)
        count_query = count_query.where(FileMetadata.channel_id == channel_id)

    if filetype:
        query = query.where(FileMetadata.filetype == filetype)
        count_query = count_query.where(FileMetadata.filetype == filetype)

    if shared_by:
        query = query.where(FileMetadata.shared_by_id == shared_by)
        count_query = count_query.where(
            FileMetadata.shared_by_id == shared_by
        )

    total_result = await db.execute(count_query)
    total = total_result.scalar()

    offset = (page - 1) * page_size
    query = (
        query.order_by(FileMetadata.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )

    result = await db.execute(query)
    files = list(result.scalars().all())

    return FileListResponse(
        files=[FileMetadataResponse.model_validate(f) for f in files],
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total,
    )
