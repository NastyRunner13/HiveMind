"""
Event Bus tests — tests for the Redis Streams event bus.

Tests cover:
- Connection lifecycle (connect, disconnect)
- Event publishing
- Stream info retrieval
- Graceful handling when Redis is not connected
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.events.bus import EventBus, EventType


# ═════════════════════════════════════════════════════════════════
# CONNECTION LIFECYCLE
# ═════════════════════════════════════════════════════════════════


class TestEventBusConnection:
    """Tests for connect/disconnect lifecycle."""

    async def test_connect_success(self, mock_redis):
        """EventBus connects to Redis and verifies with ping."""
        bus = EventBus()

        with patch("app.events.bus.aioredis.from_url", return_value=mock_redis):
            await bus.connect()

        assert bus.is_connected is True
        mock_redis.ping.assert_awaited_once()

    async def test_connect_already_connected(self, mock_event_bus):
        """Connecting when already connected is a no-op."""
        # Already connected via fixture
        assert mock_event_bus.is_connected is True
        # Connecting again should not raise
        await mock_event_bus.connect()

    async def test_disconnect(self, mock_event_bus, mock_redis):
        """Disconnecting closes the Redis connection."""
        await mock_event_bus.disconnect()

        assert mock_event_bus.is_connected is False
        mock_redis.aclose.assert_awaited_once()

    async def test_disconnect_when_not_connected(self):
        """Disconnecting when not connected is a no-op."""
        bus = EventBus()
        await bus.disconnect()  # Should not raise

    async def test_is_connected_initially_false(self):
        """New EventBus instances are not connected."""
        bus = EventBus()
        assert bus.is_connected is False


# ═════════════════════════════════════════════════════════════════
# EVENT PUBLISHING
# ═════════════════════════════════════════════════════════════════


class TestEventPublishing:
    """Tests for event publishing."""

    async def test_publish_success(self, mock_event_bus, mock_redis):
        """Publishing an event calls xadd with correct data."""
        msg_id = await mock_event_bus.publish(
            EventType.MESSAGE_INGESTED,
            {"channel_id": "C123", "message_ts": "1234567890.123456"},
        )

        assert msg_id == "1234567890-0"
        mock_redis.xadd.assert_awaited_once()

        # Verify the event structure
        call_args = mock_redis.xadd.call_args
        event_data = call_args[0][1]  # Second positional arg = the data dict
        assert event_data["type"] == "message.ingested"
        assert "timestamp" in event_data
        # Data should be JSON-serialized
        parsed_data = json.loads(event_data["data"])
        assert parsed_data["channel_id"] == "C123"

    async def test_publish_custom_stream(self, mock_event_bus, mock_redis):
        """Publishing to a custom stream name works."""
        await mock_event_bus.publish(
            EventType.DIGEST_GENERATED,
            {"digest_id": "abc"},
            stream="custom-stream",
        )

        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == "custom-stream"

    async def test_publish_when_not_connected(self):
        """Publishing when not connected returns None without error."""
        bus = EventBus()
        result = await bus.publish(EventType.MESSAGE_INGESTED, {"test": True})
        assert result is None

    async def test_publish_handles_redis_error(self, mock_event_bus, mock_redis):
        """Publishing gracefully handles Redis errors."""
        mock_redis.xadd = AsyncMock(side_effect=Exception("Redis down"))

        result = await mock_event_bus.publish(
            EventType.MESSAGE_INGESTED,
            {"test": True},
        )
        assert result is None

    async def test_publish_all_event_types(self, mock_event_bus):
        """All defined event types can be published."""
        for event_type in EventType:
            result = await mock_event_bus.publish(event_type, {"test": True})
            assert result is not None


# ═════════════════════════════════════════════════════════════════
# STREAM INFO
# ═════════════════════════════════════════════════════════════════


class TestStreamInfo:
    """Tests for stream info retrieval."""

    async def test_get_stream_info(self, mock_event_bus, mock_redis):
        """Stream info returns correct structure."""
        info = await mock_event_bus.get_stream_info()

        assert info["connected"] is True
        assert info["stream"] == "hivemind-events"
        assert info["length"] == 42

    async def test_get_stream_info_not_connected(self):
        """Stream info when not connected returns connected=False."""
        bus = EventBus()
        info = await bus.get_stream_info()
        assert info == {"connected": False}

    async def test_get_stream_info_handles_missing_stream(self, mock_event_bus, mock_redis):
        """Stream info handles non-existent streams gracefully."""
        from redis.asyncio import ResponseError

        mock_redis.xinfo_stream = AsyncMock(side_effect=ResponseError("no such key"))

        info = await mock_event_bus.get_stream_info()
        assert info["connected"] is True
        assert info["length"] == 0


# ═════════════════════════════════════════════════════════════════
# EVENT TYPES
# ═════════════════════════════════════════════════════════════════


class TestEventTypes:
    """Tests for EventType enum."""

    def test_event_types_are_strings(self):
        """All event types have string values."""
        for event_type in EventType:
            assert isinstance(event_type.value, str)
            assert "." in event_type.value  # e.g., "message.ingested"

    def test_expected_event_types_exist(self):
        """All expected event types are defined."""
        expected = [
            "MESSAGE_INGESTED",
            "MESSAGE_EDITED",
            "FILE_SHARED",
            "AGENT_QUERY",
            "AGENT_RESPONSE",
            "DIGEST_GENERATED",
            "DOCUMENT_INDEXED",
            "SEARCH_PERFORMED",
        ]
        for name in expected:
            assert hasattr(EventType, name), f"Missing EventType.{name}"
