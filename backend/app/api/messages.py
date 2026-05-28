"""Authenticated message and file metadata query endpoints."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.channel import Channel
from app.models.file_metadata import FileMetadata
from app.models.message import Message
from app.schemas.file_metadata import FileListResponse, FileMetadataResponse
from app.schemas.message import (
    MessageListResponse,
    MessageResponse,
    MessageSearchResponse,
)
from app.security.auth import AuthenticatedPrincipal, get_current_principal
from app.services.authorization_service import (
    accessible_channel_condition,
    require_channel_access,
)

router = APIRouter()


@router.get("/channels/{channel_id}/messages", response_model=MessageListResponse)
async def list_channel_messages(
    channel_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    threads_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> MessageListResponse:
    """List messages only from a channel readable by the principal."""
    await require_channel_access(db, principal, channel_id)
    query = (
        select(Message)
        .where(Message.channel_id == channel_id)
        .options(selectinload(Message.sender))
    )
    count_query = select(func.count(Message.id)).where(Message.channel_id == channel_id)
    if since:
        query = query.where(Message.slack_sent_at >= since)
        count_query = count_query.where(Message.slack_sent_at >= since)
    if until:
        query = query.where(Message.slack_sent_at <= until)
        count_query = count_query.where(Message.slack_sent_at <= until)
    if threads_only:
        thread_root = or_(
            Message.thread_ts.is_(None), Message.thread_ts == Message.slack_message_ts
        )
        query = query.where(thread_root)
        count_query = count_query.where(thread_root)

    total = (await db.execute(count_query)).scalar() or 0
    query = (
        query.order_by(Message.slack_sent_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    messages = list((await db.execute(query)).scalars().all())
    return MessageListResponse(
        messages=[MessageResponse.model_validate(message) for message in messages],
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total,
    )


@router.get("/messages/search", response_model=MessageSearchResponse)
async def search_messages(
    q: str = Query(..., min_length=2),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    channel_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> MessageSearchResponse:
    """Search only messages in channels readable by the principal."""
    visibility = await accessible_channel_condition(db, principal)
    pattern = f"%{q}%"
    query = (
        select(Message)
        .join(Channel, Message.channel_id == Channel.id)
        .where(Message.content.ilike(pattern), visibility)
        .options(selectinload(Message.sender))
    )
    count_query = (
        select(func.count(Message.id))
        .join(Channel, Message.channel_id == Channel.id)
        .where(Message.content.ilike(pattern), visibility)
    )
    if channel_id:
        await require_channel_access(db, principal, channel_id)
        query = query.where(Message.channel_id == channel_id)
        count_query = count_query.where(Message.channel_id == channel_id)
    total = (await db.execute(count_query)).scalar() or 0
    query = (
        query.order_by(Message.slack_sent_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    messages = list((await db.execute(query)).scalars().all())
    return MessageSearchResponse(
        results=[MessageResponse.model_validate(message) for message in messages],
        query=q,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/files", response_model=FileListResponse)
async def list_files(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    channel_id: uuid.UUID | None = Query(None),
    filetype: str | None = Query(None),
    shared_by: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> FileListResponse:
    """List file metadata only where its source channel is readable."""
    visibility = await accessible_channel_condition(db, principal)
    query = (
        select(FileMetadata)
        .join(Channel, FileMetadata.channel_id == Channel.id)
        .where(visibility)
        .options(selectinload(FileMetadata.shared_by))
    )
    count_query = (
        select(func.count(FileMetadata.id))
        .join(Channel, FileMetadata.channel_id == Channel.id)
        .where(visibility)
    )
    if channel_id:
        await require_channel_access(db, principal, channel_id)
        query = query.where(FileMetadata.channel_id == channel_id)
        count_query = count_query.where(FileMetadata.channel_id == channel_id)
    if filetype:
        query = query.where(FileMetadata.filetype == filetype)
        count_query = count_query.where(FileMetadata.filetype == filetype)
    if shared_by:
        query = query.where(FileMetadata.shared_by_id == shared_by)
        count_query = count_query.where(FileMetadata.shared_by_id == shared_by)
    total = (await db.execute(count_query)).scalar() or 0
    query = (
        query.order_by(FileMetadata.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    files = list((await db.execute(query)).scalars().all())
    return FileListResponse(
        files=[FileMetadataResponse.model_validate(item) for item in files],
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total,
    )
