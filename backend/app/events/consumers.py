"""
Event Consumers — background workers that process Redis Streams events.

Currently implements:
- Knowledge Indexing Consumer: subscribes to MESSAGE_INGESTED events
  and indexes messages into the Knowledge Fabric (document_chunks).

Architecture:
  Platform Event → Ingestion → Redis Event Bus → [This Consumer] → Knowledge Fabric

All events are expected to use normalized payloads with canonical internal
UUIDs (channel_id, message_id).  Legacy Slack-specific field parsing was
removed after the M4 canonical identity cutover confirmed that every
publisher emits normalized_payload() exclusively.

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
    """Load channel and message entities from normalized event UUIDs.

    Returns (channel, message) if both canonical UUIDs resolve to
    existing, matched entities. Returns (None, None) otherwise.

    Security: verifies that message.channel_id == channel.id to
    prevent ACL spoofing via forged event payloads.
    """
    internal_channel_id = data.get("channel_id")
    internal_message_id = data.get("message_id")
    if not internal_channel_id or not internal_message_id:
        logger.warning("Event missing required channel_id/message_id: %s", data)
        return None, None

    try:
        channel_id = uuid.UUID(str(internal_channel_id))
        message_id = uuid.UUID(str(internal_message_id))
    except ValueError:
        logger.warning("Event contains invalid UUIDs: %s", data)
        return None, None

    channel = await session.get(Channel, channel_id)
    message = await session.get(Message, message_id)
    if not channel or not message or message.channel_id != channel.id:
        logger.warning("Event references unknown or mismatched entities: %s", data)
        return None, None
    return channel, message


def _parse_uuid(value: object) -> uuid.UUID | None:
    """Parse a UUID from event payload data."""
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


async def _resolve_channel_from_event_data(session, data: dict) -> Channel | None:
    """Resolve a channel from normalized event payload channel_id UUID."""
    channel_id = _parse_uuid(data.get("channel_id"))
    if not channel_id:
        logger.warning("Event missing required channel_id: %s", data)
        return None
    return await session.get(Channel, channel_id)


async def _process_message_ingested(event_data: dict) -> None:
    """
    Process a MESSAGE_INGESTED event by indexing the message
    into the Knowledge Fabric.

    Steps:
    1. Load channel and message from canonical UUIDs
    2. Check idempotency — skip if already indexed
    3. Call knowledge_service.index_message()
    """
    from app.services.knowledge_service import knowledge_service

    data = event_data.get("data", {})
    async with AsyncSessionLocal() as session:
        channel, message = await _load_message_context(session, data)
    if not channel or not message:
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
    async with AsyncSessionLocal() as session:
        channel, message = await _load_message_context(session, data)
    if not channel or not message:
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


async def _process_message_deleted(event_data: dict) -> None:
    """Process a MESSAGE_DELETED event by removing source chunks."""
    from app.services.knowledge_service import knowledge_service

    data = event_data.get("data", {})
    async with AsyncSessionLocal() as session:
        _channel, message = await _load_message_context(session, data)
    if not message:
        return

    await knowledge_service.delete_chunks_for_source(message.id)


async def _process_channel_updated(event_data: dict) -> None:
    """Process a CHANNEL_UPDATED event by revalidating chunk ACL metadata."""
    from app.services.knowledge_service import knowledge_service

    data = event_data.get("data", {})
    async with AsyncSessionLocal() as session:
        channel = await _resolve_channel_from_event_data(session, data)
        if channel:
            channel_id = channel.id
            workspace_id = channel.workspace_id
    if not channel:
        logger.warning("CHANNEL_UPDATED event references unknown channel: %s", data)
        return

    await knowledge_service.revalidate_channel_acl(
        channel_id,
        workspace_id=workspace_id,
    )


async def _process_membership_updated(event_data: dict) -> None:
    """Process a MEMBERSHIP_UPDATED event by refreshing channel ACL metadata."""
    from app.services.knowledge_service import knowledge_service

    data = event_data.get("data", {})
    async with AsyncSessionLocal() as session:
        channel = await _resolve_channel_from_event_data(session, data)
        if channel:
            channel_id = channel.id
            workspace_id = channel.workspace_id
    if not channel:
        logger.warning("MEMBERSHIP_UPDATED event references unknown channel: %s", data)
        return

    await knowledge_service.revalidate_channel_acl(
        channel_id,
        workspace_id=workspace_id,
    )


# Map event types to their handler functions
_EVENT_HANDLERS = {
    EventType.MESSAGE_INGESTED.value: _process_message_ingested,
    EventType.MESSAGE_EDITED.value: _process_message_edited,
    EventType.MESSAGE_DELETED.value: _process_message_deleted,
    EventType.CHANNEL_UPDATED.value: _process_channel_updated,
    EventType.MEMBERSHIP_UPDATED.value: _process_membership_updated,
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
