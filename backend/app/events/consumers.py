"""
Event Consumers — background workers that process Redis Streams events.

Currently implements:
- Knowledge Indexing Consumer: subscribes to MESSAGE_INGESTED events
  and indexes messages into the Knowledge Fabric (document_chunks).

Architecture:
  Slack Event → Ingestion → Redis Event Bus → [This Consumer] → Knowledge Fabric

The consumer runs as an asyncio background task inside the FastAPI process.
This is simpler to deploy than a separate worker and sufficient for
single-instance deployments. Extract to a separate process if throughput
demands it later.

Reliability:
- Messages are only acked after successful processing (ack-on-success).
- Failed handler exceptions leave the message in pending state for retry.
- On startup, stranded pending messages from previous crashes are reclaimed.
"""

import asyncio
import logging
import uuid

from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.events.bus import EventType, event_bus
from app.models.channel import Channel
from app.models.message import Message

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Consumer group and name ──────────────────────────────────────
CONSUMER_GROUP = "knowledge-indexer"
CONSUMER_NAME = "indexer-main"
STREAM_NAME = "hivemind-events"


async def _load_message_context(
    session, data: dict
) -> tuple[Channel | None, Message | None]:
    """Load normalized events by UUID, with a legacy Slack-event fallback."""
    internal_channel_id = data.get("channel_id")
    internal_message_id = data.get("message_id")
    if internal_channel_id and internal_message_id:
        try:
            channel_id = uuid.UUID(str(internal_channel_id))
            message_id = uuid.UUID(str(internal_message_id))
        except ValueError:
            logger.warning("Message event contains invalid internal UUIDs: %s", data)
            return None, None

        channel = await session.get(Channel, channel_id)
        message = await session.get(Message, message_id)
        if not channel or not message or message.channel_id != channel.id:
            logger.warning(
                "Message event references unknown or mismatched entities: %s", data
            )
            return None, None
        return channel, message

    slack_channel_id = data.get("slack_channel_id")
    slack_message_ts = data.get("slack_message_ts")
    if not slack_channel_id or not slack_message_ts:
        return None, None

    channel_result = await session.execute(
        select(Channel).where(Channel.slack_channel_id == slack_channel_id)
    )
    channel = channel_result.scalar_one_or_none()
    if not channel:
        logger.warning("Channel %s not found for indexing", slack_channel_id)
        return None, None

    message_result = await session.execute(
        select(Message).where(
            Message.channel_id == channel.id,
            Message.slack_message_ts == slack_message_ts,
        )
    )
    return channel, message_result.scalar_one_or_none()


async def _process_message_ingested(event_data: dict) -> None:
    """
    Process a MESSAGE_INGESTED event by indexing the message
    into the Knowledge Fabric.

    Steps:
    1. Fetch the channel from DB using slack_channel_id
    2. Fetch the message using channel_id + slack_message_ts
       (prevents cross-channel timestamp collisions)
    3. Check idempotency — skip if already indexed
    4. Call knowledge_service.index_message()
    """
    from app.services.knowledge_service import knowledge_service

    data = event_data.get("data", {})
    if data.get("channel_id") and data.get("message_id"):
        async with AsyncSessionLocal() as session:
            channel, message = await _load_message_context(session, data)
        if not channel or not message:
            return
        if await knowledge_service.is_already_indexed(message.id):
            return
        await knowledge_service.index_message(message=message, channel=channel)
        return

    slack_channel_id = data.get("slack_channel_id")
    slack_message_ts = data.get("slack_message_ts")

    if not slack_channel_id or not slack_message_ts:
        logger.warning(f"MESSAGE_INGESTED event missing required fields: {data}")
        return

    async with AsyncSessionLocal() as session:
        # Find the channel FIRST — needed for scoped message lookup
        ch_result = await session.execute(
            select(Channel).where(
                Channel.slack_channel_id == slack_channel_id,
            )
        )
        channel = ch_result.scalar_one_or_none()

        if not channel:
            logger.warning(f"Channel {slack_channel_id} not found for indexing")
            return

        # Find the message — use channel_id to prevent cross-channel
        # timestamp collisions. The model uniqueness constraint is
        # (workspace_id, channel_id, slack_message_ts), so ts alone
        # is NOT unique. Without channel_id, a collision could index
        # the wrong message under the wrong channel's ACL.
        msg_result = await session.execute(
            select(Message).where(
                Message.channel_id == channel.id,
                Message.slack_message_ts == slack_message_ts,
            )
        )
        message = msg_result.scalar_one_or_none()

        if not message:
            logger.debug(
                f"Message {slack_message_ts} in channel "
                f"{slack_channel_id} not found in DB — "
                f"may not have been committed yet, skipping"
            )
            return

    # Idempotency check — skip if already indexed
    if await knowledge_service.is_already_indexed(message.id):
        logger.debug(f"Message {message.id} already indexed — skipping")
        return

    # Index the message
    try:
        chunks_created = await knowledge_service.index_message(
            message=message, channel=channel
        )
        if chunks_created > 0:
            logger.info(
                f"Indexed message {message.id}: {chunks_created} chunks created"
            )
    except Exception as e:
        logger.error(
            f"Failed to index message {message.id}: {e}",
            exc_info=True,
        )
        raise  # Re-raise so _process_event does NOT ack


async def _process_message_edited(event_data: dict) -> None:
    """
    Process a MESSAGE_EDITED event by re-indexing the message.

    Deletes existing chunks for the source message and re-indexes
    with the updated content.
    """
    from app.services.knowledge_service import knowledge_service

    data = event_data.get("data", {})
    if data.get("channel_id") and data.get("message_id"):
        async with AsyncSessionLocal() as session:
            channel, message = await _load_message_context(session, data)
        if not channel or not message:
            return
        await knowledge_service.delete_chunks_for_source(message.id)
        await knowledge_service.index_message(message=message, channel=channel)
        return

    slack_channel_id = data.get("slack_channel_id")
    slack_message_ts = data.get("slack_message_ts")

    if not slack_channel_id or not slack_message_ts:
        return

    async with AsyncSessionLocal() as session:
        # Find channel first for scoped message lookup
        ch_result = await session.execute(
            select(Channel).where(
                Channel.slack_channel_id == slack_channel_id,
            )
        )
        channel = ch_result.scalar_one_or_none()

        if not channel:
            return

        # Scoped lookup: channel_id + timestamp (prevents collisions)
        msg_result = await session.execute(
            select(Message).where(
                Message.channel_id == channel.id,
                Message.slack_message_ts == slack_message_ts,
            )
        )
        message = msg_result.scalar_one_or_none()

        if not message:
            return

    # Delete old chunks and re-index
    try:
        deleted = await knowledge_service.delete_chunks_for_source(message.id)
        if deleted > 0:
            logger.debug(
                f"Deleted {deleted} old chunks for edited message {message.id}"
            )

        chunks_created = await knowledge_service.index_message(
            message=message, channel=channel
        )
        if chunks_created > 0:
            logger.info(
                f"Re-indexed edited message {message.id}: {chunks_created} chunks"
            )
    except Exception as e:
        logger.error(
            f"Failed to re-index edited message {message.id}: {e}",
            exc_info=True,
        )
        raise  # Re-raise so _process_event does NOT ack


# ═════════════════════════════════════════════════════════════════
# EVENT ROUTER
# ═════════════════════════════════════════════════════════════════

# Map event types to their handler functions
_EVENT_HANDLERS = {
    EventType.MESSAGE_INGESTED.value: _process_message_ingested,
    EventType.MESSAGE_EDITED.value: _process_message_edited,
}


async def _process_event(event: dict) -> None:
    """Process a single event with ack-on-success semantics.

    If the handler succeeds (or there's no handler for this event type),
    the message is acknowledged. If the handler raises an exception,
    the message is NOT acked — it stays in the pending entries list
    and will be reclaimed on the next consumer startup.
    """
    event_type = event.get("type")
    handler = _EVENT_HANDLERS.get(event_type)
    msg_id = event.get("id")
    stream = event.get("stream", STREAM_NAME)
    group = event.get("group", CONSUMER_GROUP)

    if handler:
        try:
            await handler(event)
        except Exception as e:
            logger.error(
                f"Error processing {event_type} event {msg_id}: {e}",
                exc_info=True,
            )
            # Don't ack — message stays pending for retry/reclaim
            return

    # Ack on success (or if no handler — irrelevant event types)
    await event_bus.ack(stream, group, msg_id)


async def start_knowledge_consumer() -> None:
    """
    Start the knowledge indexing consumer as a long-running coroutine.

    Subscribes to the hivemind-events Redis Stream using consumer
    groups for at-least-once delivery with acknowledgment.

    On startup, reclaims any messages that were stranded in the
    pending entries list from a previous crash (messages read but
    not acked before the process died).

    This coroutine runs forever until cancelled. It should be launched
    as an asyncio task from the FastAPI lifespan.
    """
    logger.info(
        f"Knowledge indexing consumer starting "
        f"(group={CONSUMER_GROUP}, consumer={CONSUMER_NAME})"
    )

    try:
        # Reclaim messages stranded from a previous crash.
        # These are messages that were read (xreadgroup) but never
        # acked (xack) because the process died mid-processing.
        pending = await event_bus.reclaim_pending(
            stream=STREAM_NAME,
            group=CONSUMER_GROUP,
            consumer=CONSUMER_NAME,
            min_idle_ms=60_000,
        )
        if pending:
            logger.info(f"Reclaiming {len(pending)} stranded pending messages")
            for event in pending:
                await _process_event(event)

        # Main consumer loop
        async for event in event_bus.subscribe(
            stream=STREAM_NAME,
            group=CONSUMER_GROUP,
            consumer=CONSUMER_NAME,
            count=10,
            block_ms=5000,
        ):
            await _process_event(event)

    except asyncio.CancelledError:
        logger.info("Knowledge indexing consumer shutting down...")
        raise
    except Exception as e:
        logger.error(
            f"Knowledge indexing consumer crashed: {e}",
            exc_info=True,
        )
