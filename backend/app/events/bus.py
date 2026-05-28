"""
Event Bus — Redis Streams wrapper for HiveMind's event-driven architecture.

The Event Bus serves two purposes:
1. Decouple ingestion from processing (real-time event routing)
2. Store workflow traces for Phase 2's Skills Engine (pattern detection)

Every significant action (message ingested, file shared, agent response)
is published as an event. Consumers can subscribe to specific streams
for real-time processing.

Architecture:
  Slack Events → Ingestion → Event Bus → [Consumers: Embedding, Digest, etc.]
"""

import enum
import json
import logging
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

from app.config import get_settings

logger = logging.getLogger(__name__)


class EventType(str, enum.Enum):
    """Event types published to the bus."""

    # Ingestion events
    MESSAGE_INGESTED = "message.ingested"
    MESSAGE_EDITED = "message.edited"
    FILE_SHARED = "file.shared"
    CHANNEL_CREATED = "channel.created"
    CHANNEL_UPDATED = "channel.updated"
    USER_JOINED = "user.joined"

    # Agent events (for workflow tracing)
    AGENT_QUERY = "agent.query"
    AGENT_RESPONSE = "agent.response"
    AGENT_TOOL_CALL = "agent.tool_call"
    IDENTITY_MAPPED = "identity.mapped"

    # Digest events
    DIGEST_GENERATED = "digest.generated"
    DIGEST_DELIVERED = "digest.delivered"

    # Knowledge events
    DOCUMENT_INDEXED = "knowledge.indexed"
    SEARCH_PERFORMED = "knowledge.search"


class EventBus:
    """
    Redis Streams-based event bus for HiveMind.

    Provides publish/subscribe semantics using Redis Streams,
    which give us durable, ordered, fan-out-capable message delivery.

    Usage:
        bus = EventBus()
        await bus.connect()

        # Publish
        await bus.publish(EventType.MESSAGE_INGESTED, {
            "channel_id": "C123",
            "message_ts": "1234567890.123456",
        })

        # Subscribe (consumer group)
        async for event in bus.subscribe("hivemind-events", "worker-1"):
            process(event)
    """

    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None
        self._settings = get_settings()

    async def connect(self) -> None:
        """Establish connection to Redis."""
        if self._redis is not None:
            return

        self._redis = aioredis.from_url(
            self._settings.redis_url,
            decode_responses=True,
            max_connections=10,
        )
        # Verify connectivity
        await self._redis.ping()
        logger.info("✅ Redis Event Bus connected")

    async def disconnect(self) -> None:
        """Close the Redis connection."""
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
            logger.info("Redis Event Bus disconnected")

    @property
    def is_connected(self) -> bool:
        """Check if the bus is connected."""
        return self._redis is not None

    async def publish(
        self,
        event_type: EventType,
        data: dict[str, Any],
        stream: str = "hivemind-events",
    ) -> str | None:
        """
        Publish an event to a Redis Stream.

        Args:
            event_type: The type of event being published.
            data: Event payload (must be JSON-serializable).
            stream: Redis Stream name to publish to.

        Returns:
            The message ID assigned by Redis, or None if publishing failed.
        """
        if self._redis is None:
            logger.debug("Event Bus not connected — skipping publish")
            return None

        event = {
            "type": event_type.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": json.dumps(data),
        }

        try:
            msg_id = await self._redis.xadd(
                stream,
                event,
                maxlen=self._settings.redis_stream_max_len,
            )
            logger.debug(f"Published {event_type.value} → {stream} ({msg_id})")
            return msg_id
        except Exception as e:
            logger.error(f"Failed to publish event {event_type.value}: {e}")
            return None

    async def subscribe(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 5000,
    ):
        """
        Subscribe to a Redis Stream using consumer groups.

        Yields (message_id, event_data) tuples. Uses consumer groups
        for reliable, at-least-once delivery with acknowledgment.

        Args:
            stream: Redis Stream name to read from.
            group: Consumer group name.
            consumer: Consumer name within the group.
            count: Max messages to read per batch.
            block_ms: Milliseconds to block waiting for new messages.
        """
        if self._redis is None:
            logger.warning("Event Bus not connected — cannot subscribe")
            return

        # Create consumer group if it doesn't exist
        try:
            await self._redis.xgroup_create(stream, group, id="0", mkstream=True)
            logger.info(f"Created consumer group '{group}' on stream '{stream}'")
        except aioredis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise  # Group already exists — that's fine

        while True:
            try:
                messages = await self._redis.xreadgroup(
                    groupname=group,
                    consumername=consumer,
                    streams={stream: ">"},
                    count=count,
                    block=block_ms,
                )

                if not messages:
                    continue

                for _stream_name, stream_messages in messages:
                    for msg_id, msg_data in stream_messages:
                        event_data = {
                            "id": msg_id,
                            "type": msg_data.get("type"),
                            "timestamp": msg_data.get("timestamp"),
                            "data": json.loads(msg_data.get("data", "{}")),
                            "stream": stream,
                            "group": group,
                        }
                        yield event_data

                        # NOTE: ack is now the consumer's responsibility.
                        # Call event_bus.ack(stream, group, msg_id) after
                        # successful processing. This ensures failed
                        # handlers leave messages in pending state for
                        # retry/reclaim.

            except Exception as e:
                logger.error(f"Error reading from stream {stream}: {e}")
                break

    async def ack(
        self,
        stream: str,
        group: str,
        msg_id: str,
    ) -> None:
        """Acknowledge a successfully processed message.

        Must be called by the consumer after successful processing.
        Messages that are not acked remain in the pending entries list
        and can be reclaimed by reclaim_pending().
        """
        if self._redis:
            await self._redis.xack(stream, group, msg_id)

    async def reclaim_pending(
        self,
        stream: str,
        group: str,
        consumer: str,
        min_idle_ms: int = 60_000,
        count: int = 10,
    ) -> list[dict]:
        """Reclaim messages stuck in pending state after a crash.

        Uses XAUTOCLAIM to take ownership of messages that have been
        idle for min_idle_ms without being acked. These are messages
        that were read (xreadgroup) but never acked (xack) because
        the consumer process died mid-processing.

        Args:
            stream: Redis Stream name.
            group: Consumer group name.
            consumer: Consumer name to assign ownership to.
            min_idle_ms: Minimum idle time before reclaiming.
            count: Max messages to reclaim per call.

        Returns:
            List of reclaimed event dicts, same format as subscribe().
        """
        if self._redis is None:
            return []

        try:
            result = await self._redis.xautoclaim(
                name=stream,
                groupname=group,
                consumername=consumer,
                min_idle_time=min_idle_ms,
                count=count,
            )
            # xautoclaim returns:
            #   (next_start_id, [(msg_id, data), ...], [deleted_ids])
            messages = []
            if result and len(result) > 1:
                for msg_id, msg_data in result[1]:
                    messages.append(
                        {
                            "id": msg_id,
                            "type": msg_data.get("type"),
                            "timestamp": msg_data.get("timestamp"),
                            "data": json.loads(msg_data.get("data", "{}")),
                            "stream": stream,
                            "group": group,
                        }
                    )
            if messages:
                logger.info(
                    f"Reclaimed {len(messages)} pending messages from {stream}/{group}"
                )
            return messages
        except Exception as e:
            logger.error(f"Failed to reclaim pending messages: {e}")
            return []

    async def get_stream_info(self, stream: str = "hivemind-events") -> dict:
        """Get info about a stream (length, groups, etc.)."""
        if self._redis is None:
            return {"connected": False}

        try:
            info = await self._redis.xinfo_stream(stream)
            return {
                "connected": True,
                "stream": stream,
                "length": info.get("length", 0),
                "first_entry": info.get("first-entry"),
                "last_entry": info.get("last-entry"),
            }
        except aioredis.ResponseError:
            return {"connected": True, "stream": stream, "length": 0}


# ── Module-level singleton ──────────────────────────────────────
# Used across the app. Initialized in main.py lifespan.
event_bus = EventBus()
