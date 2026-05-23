"""
Ingestion Service — processes Slack events and persists data to the database.

This is the heart of HiveMind's data pipeline. Every Slack event
(message, file share, channel creation, user join) flows through
here and gets normalized, deduplicated, and stored.

Design principles:
- Idempotent: re-processing the same event produces the same result
- Fault-tolerant: individual failures don't crash the pipeline
- Workspace-aware: all data is scoped to a workspace for multi-tenancy
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import AsyncSessionLocal
from app.models.channel import Channel, ChannelType
from app.models.file_metadata import FileMetadata
from app.models.message import Message, MessageType
from app.models.user import SlackUser
from app.models.workspace import Workspace

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════
# WORKSPACE HELPERS
# ═════════════════════════════════════════════════════════════════


async def get_or_create_workspace(
    slack_team_id: str, name: str = "Unknown", domain: str = ""
) -> Workspace:
    """
    Get an existing workspace or create one if it doesn't exist.
    
    This is the top-level entity — we need a workspace before
    we can store any channels, users, or messages.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Workspace).where(Workspace.slack_team_id == slack_team_id)
        )
        workspace = result.scalar_one_or_none()

        if workspace is None:
            workspace = Workspace(
                slack_team_id=slack_team_id,
                name=name,
                domain=domain,
                is_active=True,
            )
            session.add(workspace)
            await session.commit()
            await session.refresh(workspace)
            logger.info(f"Created workspace: {name} ({slack_team_id})")

        return workspace


async def _get_workspace_id(session, slack_team_id: str = None):
    """Get the workspace ID. For now, returns the first active workspace."""
    if slack_team_id:
        result = await session.execute(
            select(Workspace.id).where(
                Workspace.slack_team_id == slack_team_id
            )
        )
    else:
        result = await session.execute(
            select(Workspace.id).where(Workspace.is_active.is_(True)).limit(1)
        )
    row = result.scalar_one_or_none()
    return row


async def _resolve_channel_id(session, slack_channel_id: str, workspace_id):
    """Look up the internal channel UUID from a Slack channel ID."""
    result = await session.execute(
        select(Channel.id).where(
            Channel.slack_channel_id == slack_channel_id,
            Channel.workspace_id == workspace_id,
        )
    )
    return result.scalar_one_or_none()


async def _resolve_user_id(session, slack_user_id: str, workspace_id):
    """Look up the internal user UUID from a Slack user ID."""
    if not slack_user_id:
        return None
    result = await session.execute(
        select(SlackUser.id).where(
            SlackUser.slack_user_id == slack_user_id,
            SlackUser.workspace_id == workspace_id,
        )
    )
    return result.scalar_one_or_none()


# ═════════════════════════════════════════════════════════════════
# MESSAGE INGESTION
# ═════════════════════════════════════════════════════════════════


async def ingest_message(event: dict) -> None:
    """
    Ingest a real-time message event from Slack.

    Called by the Slack event handler when a new message is received.
    Extracts message data, resolves references, and upserts to DB.
    """
    async with AsyncSessionLocal() as session:
        workspace_id = await _get_workspace_id(session)
        if not workspace_id:
            logger.warning("No active workspace found — skipping message")
            return

        slack_channel_id = event.get("channel")
        channel_id = await _resolve_channel_id(
            session, slack_channel_id, workspace_id
        )

        if not channel_id:
            # Channel not yet synced — auto-create a placeholder
            logger.debug(
                f"Channel {slack_channel_id} not found, creating placeholder"
            )
            channel = Channel(
                workspace_id=workspace_id,
                slack_channel_id=slack_channel_id,
                name=f"unknown-{slack_channel_id}",
                channel_type=ChannelType.PUBLIC,
            )
            session.add(channel)
            await session.flush()
            channel_id = channel.id

        sender_id = await _resolve_user_id(
            session, event.get("user"), workspace_id
        )

        # Determine message type
        msg_type = MessageType.USER
        if event.get("subtype") == "bot_message" or event.get("bot_id"):
            msg_type = MessageType.BOT
        elif event.get("subtype") in (
            "channel_topic",
            "channel_purpose",
            "channel_name",
        ):
            msg_type = MessageType.SYSTEM

        # Parse the Slack timestamp into a datetime
        slack_ts = event.get("ts", "0")
        slack_sent_at = datetime.fromtimestamp(
            float(slack_ts), tz=timezone.utc
        )

        message = Message(
            workspace_id=workspace_id,
            channel_id=channel_id,
            sender_id=sender_id,
            slack_message_ts=slack_ts,
            thread_ts=event.get("thread_ts"),
            content=event.get("text", ""),
            message_type=msg_type,
            has_attachments=bool(event.get("attachments")),
            has_files=bool(event.get("files")),
            reaction_count=len(event.get("reactions", [])),
            reply_count=event.get("reply_count", 0),
            is_edited=event.get("edited") is not None,
            slack_sent_at=slack_sent_at,
        )

        # Upsert: insert or update on conflict
        stmt = pg_insert(Message).values(
            workspace_id=message.workspace_id,
            channel_id=message.channel_id,
            sender_id=message.sender_id,
            slack_message_ts=message.slack_message_ts,
            thread_ts=message.thread_ts,
            content=message.content,
            message_type=message.message_type,
            has_attachments=message.has_attachments,
            has_files=message.has_files,
            reaction_count=message.reaction_count,
            reply_count=message.reply_count,
            is_edited=message.is_edited,
            slack_sent_at=message.slack_sent_at,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_message_workspace_channel_ts",
            set_={
                "content": stmt.excluded.content,
                "is_edited": True,
                "reaction_count": stmt.excluded.reaction_count,
                "reply_count": stmt.excluded.reply_count,
                "has_attachments": stmt.excluded.has_attachments,
                "has_files": stmt.excluded.has_files,
            },
        )
        await session.execute(stmt)
        await session.commit()

        logger.debug(
            f"Ingested message {slack_ts} in channel {slack_channel_id}"
        )


async def ingest_message_from_history(
    msg: dict, slack_channel_id: str
) -> None:
    """
    Ingest a message from conversations.history API response.

    Similar to ingest_message() but works with the slightly different
    format returned by the history API vs real-time events.
    """
    # Normalize to the event format and reuse the main ingest function
    event = {
        "channel": slack_channel_id,
        "user": msg.get("user"),
        "ts": msg.get("ts"),
        "thread_ts": msg.get("thread_ts"),
        "text": msg.get("text", ""),
        "subtype": msg.get("subtype"),
        "bot_id": msg.get("bot_id"),
        "attachments": msg.get("attachments"),
        "files": msg.get("files"),
        "reactions": msg.get("reactions"),
        "reply_count": msg.get("reply_count", 0),
        "edited": msg.get("edited"),
    }
    await ingest_message(event)


async def handle_message_edit(event: dict) -> None:
    """
    Handle a message_changed event — update stored message content.
    """
    message_data = event.get("message", {})
    if not message_data:
        return

    async with AsyncSessionLocal() as session:
        workspace_id = await _get_workspace_id(session)
        if not workspace_id:
            return

        slack_ts = message_data.get("ts")
        channel_id_str = event.get("channel")

        channel_id = await _resolve_channel_id(
            session, channel_id_str, workspace_id
        )
        if not channel_id:
            return

        await session.execute(
            update(Message)
            .where(
                Message.workspace_id == workspace_id,
                Message.channel_id == channel_id,
                Message.slack_message_ts == slack_ts,
            )
            .values(
                content=message_data.get("text", ""),
                is_edited=True,
            )
        )
        await session.commit()
        logger.debug(f"Updated edited message {slack_ts}")


# ═════════════════════════════════════════════════════════════════
# FILE METADATA INGESTION
# ═════════════════════════════════════════════════════════════════


async def ingest_file_metadata(
    file_info: dict, slack_channel_id: str | None = None
) -> None:
    """
    Ingest file metadata (NOT content) from a Slack file_shared event
    or files.list API response.

    This populates the Knowledge Fabric's Metadata Index — we store
    who shared what, where, when, and the file type/size. Content
    is fetched on-demand later when needed for RAG queries.
    """
    async with AsyncSessionLocal() as session:
        workspace_id = await _get_workspace_id(session)
        if not workspace_id:
            logger.warning("No active workspace — skipping file metadata")
            return

        channel_id = None
        if slack_channel_id:
            channel_id = await _resolve_channel_id(
                session, slack_channel_id, workspace_id
            )

        shared_by_id = await _resolve_user_id(
            session, file_info.get("user"), workspace_id
        )

        # Parse Slack's created timestamp
        slack_created = file_info.get("created")
        slack_created_at = (
            datetime.fromtimestamp(slack_created, tz=timezone.utc)
            if slack_created
            else None
        )

        # Count total shares across channels
        shares = file_info.get("shares", {})
        shares_count = sum(
            len(v) for v in shares.get("public", {}).values()
        ) + sum(len(v) for v in shares.get("private", {}).values())

        stmt = pg_insert(FileMetadata).values(
            workspace_id=workspace_id,
            slack_file_id=file_info.get("id", ""),
            channel_id=channel_id,
            shared_by_id=shared_by_id,
            filename=file_info.get("name", "unknown"),
            title=file_info.get("title"),
            filetype=file_info.get("filetype", "unknown"),
            mimetype=file_info.get("mimetype", "application/octet-stream"),
            size_bytes=file_info.get("size", 0),
            url_private=file_info.get("url_private"),
            permalink=file_info.get("permalink"),
            shares_count=max(shares_count, 1),
            is_external=file_info.get("is_external", False),
            slack_created_at=slack_created_at,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_file_workspace_slack_id",
            set_={
                "title": stmt.excluded.title,
                "shares_count": stmt.excluded.shares_count,
                "url_private": stmt.excluded.url_private,
                "permalink": stmt.excluded.permalink,
            },
        )
        await session.execute(stmt)
        await session.commit()

        logger.debug(
            f"Ingested file metadata: {file_info.get('name')} "
            f"({file_info.get('filetype')})"
        )


# ═════════════════════════════════════════════════════════════════
# CHANNEL INGESTION
# ═════════════════════════════════════════════════════════════════


async def ingest_channel(channel_data: dict) -> bool:
    """
    Ingest a channel from a channel_created event.
    Returns True if the channel was newly created, False if updated.
    """
    async with AsyncSessionLocal() as session:
        workspace_id = await _get_workspace_id(session)
        if not workspace_id:
            return False

        return await _upsert_channel(session, channel_data, workspace_id)


async def ingest_channel_from_api(channel_data: dict) -> bool:
    """
    Ingest a channel from the conversations.list API response.
    Returns True if newly created, False if updated.
    """
    async with AsyncSessionLocal() as session:
        workspace_id = await _get_workspace_id(session)
        if not workspace_id:
            return False

        return await _upsert_channel(session, channel_data, workspace_id)


async def _upsert_channel(session, channel_data: dict, workspace_id) -> bool:
    """Upsert a channel record. Returns True if new."""
    slack_id = channel_data.get("id", "")

    # Determine channel type
    if channel_data.get("is_im"):
        ch_type = ChannelType.DM
    elif channel_data.get("is_mpim"):
        ch_type = ChannelType.GROUP_DM
    elif channel_data.get("is_private"):
        ch_type = ChannelType.PRIVATE
    else:
        ch_type = ChannelType.PUBLIC

    values = {
        "workspace_id": workspace_id,
        "slack_channel_id": slack_id,
        "name": channel_data.get("name", f"unknown-{slack_id}"),
        "channel_type": ch_type,
        "topic": (channel_data.get("topic") or {}).get("value"),
        "purpose": (channel_data.get("purpose") or {}).get("value"),
        "is_archived": channel_data.get("is_archived", False),
        "member_count": channel_data.get("num_members", 0),
    }

    stmt = pg_insert(Channel).values(**values)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_channel_workspace_slack_id",
        set_={
            "name": stmt.excluded.name,
            "topic": stmt.excluded.topic,
            "purpose": stmt.excluded.purpose,
            "is_archived": stmt.excluded.is_archived,
            "member_count": stmt.excluded.member_count,
        },
    )

    # Check if it existed before
    existing = await session.execute(
        select(Channel.id).where(
            Channel.slack_channel_id == slack_id,
            Channel.workspace_id == workspace_id,
        )
    )
    is_new = existing.scalar_one_or_none() is None

    await session.execute(stmt)
    await session.commit()

    return is_new


async def update_channel(
    slack_channel_id: str, updates: dict
) -> None:
    """Update specific fields of a channel by its Slack ID."""
    async with AsyncSessionLocal() as session:
        workspace_id = await _get_workspace_id(session)
        if not workspace_id:
            return

        await session.execute(
            update(Channel)
            .where(
                Channel.slack_channel_id == slack_channel_id,
                Channel.workspace_id == workspace_id,
            )
            .values(**updates)
        )
        await session.commit()


# ═════════════════════════════════════════════════════════════════
# USER INGESTION
# ═════════════════════════════════════════════════════════════════


async def ingest_user(user_data: dict) -> bool:
    """
    Ingest a Slack user profile.
    Returns True if newly created, False if updated.
    """
    async with AsyncSessionLocal() as session:
        workspace_id = await _get_workspace_id(session)
        if not workspace_id:
            return False

        slack_id = user_data.get("id", "")
        profile = user_data.get("profile", {})

        values = {
            "workspace_id": workspace_id,
            "slack_user_id": slack_id,
            "display_name": (
                profile.get("display_name")
                or profile.get("real_name")
                or user_data.get("name", "Unknown")
            ),
            "real_name": (
                user_data.get("real_name")
                or profile.get("real_name", "")
            ),
            "email": profile.get("email"),
            "is_bot": user_data.get("is_bot", False),
            "is_admin": user_data.get("is_admin", False),
            "is_owner": user_data.get("is_owner", False),
            "is_active": not user_data.get("deleted", False),
            "avatar_url": (
                profile.get("image_192")
                or profile.get("image_72")
            ),
            "timezone": user_data.get("tz"),
            "status_text": profile.get("status_text"),
            "title": profile.get("title"),
        }

        # Check if exists
        existing = await session.execute(
            select(SlackUser.id).where(
                SlackUser.slack_user_id == slack_id,
                SlackUser.workspace_id == workspace_id,
            )
        )
        is_new = existing.scalar_one_or_none() is None

        stmt = pg_insert(SlackUser).values(**values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_user_workspace_slack_id",
            set_={
                "display_name": stmt.excluded.display_name,
                "real_name": stmt.excluded.real_name,
                "email": stmt.excluded.email,
                "is_admin": stmt.excluded.is_admin,
                "is_active": stmt.excluded.is_active,
                "avatar_url": stmt.excluded.avatar_url,
                "timezone": stmt.excluded.timezone,
                "status_text": stmt.excluded.status_text,
                "title": stmt.excluded.title,
            },
        )
        await session.execute(stmt)
        await session.commit()

        return is_new
