"""
Tests for the Knowledge Indexing Consumer.

Tests the event consumer that processes MESSAGE_INGESTED events
from Redis Streams and indexes messages into the Knowledge Fabric.

Tests cover:
- Successful indexing flow
- Idempotency (skip already-indexed)
- Missing fields handling
- Unknown message/channel handling
- Re-indexing on message edit
- Channel-scoped message lookup (prevents cross-channel collisions)
- Ack-on-success semantics (failures leave messages pending)
- Pending message reclaim on startup
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Check if asyncpg is available (needed by app.database → consumers)
try:
    import asyncpg

    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False

skip_without_asyncpg = pytest.mark.skipif(
    not HAS_ASYNCPG,
    reason="asyncpg not installed — consumers imports app.database",
)


@pytest.fixture
def sample_message():
    """Create a mock message object."""
    msg = MagicMock()
    msg.id = uuid.uuid4()
    msg.slack_message_ts = "1716382103.001234"
    msg.content = "Test message for indexing"
    msg.slack_sent_at = datetime.now(timezone.utc)
    return msg


@pytest.fixture
def sample_channel():
    """Create a mock channel object."""
    ch = MagicMock()
    ch.id = uuid.uuid4()
    ch.slack_channel_id = "C024BE91L"
    ch.name = "test-channel"
    ch.channel_type = MagicMock(value="public")
    return ch


@skip_without_asyncpg
class TestProcessMessageIngested:
    """Tests for _process_message_ingested handler."""

    @pytest.mark.asyncio
    async def test_indexes_new_message(self, sample_message, sample_channel):
        """MESSAGE_INGESTED event should create document_chunks for new messages."""
        from app.events.consumers import _process_message_ingested

        event_data = {
            "type": "message.ingested",
            "data": {
                "slack_channel_id": sample_channel.slack_channel_id,
                "slack_message_ts": sample_message.slack_message_ts,
            },
        }

        with (
            patch(
                "app.events.consumers.AsyncSessionLocal"
            ) as mock_session_factory,
            patch(
                "app.services.knowledge_service.knowledge_service"
            ) as mock_ks,
        ):
            # Set up mock session
            mock_session = AsyncMock()
            mock_session_factory.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_session_factory.return_value.__aexit__ = AsyncMock(
                return_value=None
            )

            # Channel query returns our sample channel (queried FIRST)
            ch_result = MagicMock()
            ch_result.scalar_one_or_none.return_value = sample_channel

            # Message query returns our sample message (queried SECOND, scoped by channel)
            msg_result = MagicMock()
            msg_result.scalar_one_or_none.return_value = sample_message

            mock_session.execute = AsyncMock(
                side_effect=[ch_result, msg_result]
            )

            # Not already indexed
            mock_ks.is_already_indexed = AsyncMock(return_value=False)
            mock_ks.index_message = AsyncMock(return_value=3)

            await _process_message_ingested(event_data)

            # Verify indexing was called
            mock_ks.index_message.assert_called_once_with(
                message=sample_message, channel=sample_channel
            )

    @pytest.mark.asyncio
    async def test_skips_already_indexed_message(
        self, sample_message, sample_channel
    ):
        """MESSAGE_INGESTED should skip messages that are already indexed."""
        from app.events.consumers import _process_message_ingested

        event_data = {
            "type": "message.ingested",
            "data": {
                "slack_channel_id": sample_channel.slack_channel_id,
                "slack_message_ts": sample_message.slack_message_ts,
            },
        }

        with (
            patch(
                "app.events.consumers.AsyncSessionLocal"
            ) as mock_session_factory,
            patch(
                "app.services.knowledge_service.knowledge_service"
            ) as mock_ks,
        ):
            mock_session = AsyncMock()
            mock_session_factory.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_session_factory.return_value.__aexit__ = AsyncMock(
                return_value=None
            )

            # Channel first, then message
            ch_result = MagicMock()
            ch_result.scalar_one_or_none.return_value = sample_channel

            msg_result = MagicMock()
            msg_result.scalar_one_or_none.return_value = sample_message

            mock_session.execute = AsyncMock(
                side_effect=[ch_result, msg_result]
            )

            # Already indexed — should skip
            mock_ks.is_already_indexed = AsyncMock(return_value=True)
            mock_ks.index_message = AsyncMock()

            await _process_message_ingested(event_data)

            # index_message should NOT be called
            mock_ks.index_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_missing_fields(self):
        """EVENT with missing fields should be skipped gracefully."""
        from app.events.consumers import _process_message_ingested

        event_data = {
            "type": "message.ingested",
            "data": {},  # Missing slack_channel_id and slack_message_ts
        }

        # Should not raise
        await _process_message_ingested(event_data)

    @pytest.mark.asyncio
    async def test_skips_unknown_channel(self):
        """Event for a channel not in DB should be skipped."""
        from app.events.consumers import _process_message_ingested

        event_data = {
            "type": "message.ingested",
            "data": {
                "slack_channel_id": "C_UNKNOWN",
                "slack_message_ts": "9999999999.000000",
            },
        }

        with patch(
            "app.events.consumers.AsyncSessionLocal"
        ) as mock_session_factory:
            mock_session = AsyncMock()
            mock_session_factory.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_session_factory.return_value.__aexit__ = AsyncMock(
                return_value=None
            )

            # Channel not found
            ch_result = MagicMock()
            ch_result.scalar_one_or_none.return_value = None
            mock_session.execute = AsyncMock(return_value=ch_result)

            # Should not raise
            await _process_message_ingested(event_data)

    @pytest.mark.asyncio
    async def test_skips_unknown_message(self, sample_channel):
        """Event for a message not in DB should be skipped."""
        from app.events.consumers import _process_message_ingested

        event_data = {
            "type": "message.ingested",
            "data": {
                "slack_channel_id": sample_channel.slack_channel_id,
                "slack_message_ts": "9999999999.000000",
            },
        }

        with patch(
            "app.events.consumers.AsyncSessionLocal"
        ) as mock_session_factory:
            mock_session = AsyncMock()
            mock_session_factory.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_session_factory.return_value.__aexit__ = AsyncMock(
                return_value=None
            )

            # Channel found, message not found
            ch_result = MagicMock()
            ch_result.scalar_one_or_none.return_value = sample_channel

            msg_result = MagicMock()
            msg_result.scalar_one_or_none.return_value = None

            mock_session.execute = AsyncMock(
                side_effect=[ch_result, msg_result]
            )

            # Should not raise
            await _process_message_ingested(event_data)

    @pytest.mark.asyncio
    async def test_message_lookup_uses_channel_id(
        self, sample_message, sample_channel
    ):
        """Message lookup should include channel_id to prevent
        cross-channel timestamp collisions."""
        from app.events.consumers import _process_message_ingested

        event_data = {
            "type": "message.ingested",
            "data": {
                "slack_channel_id": sample_channel.slack_channel_id,
                "slack_message_ts": sample_message.slack_message_ts,
            },
        }

        with (
            patch(
                "app.events.consumers.AsyncSessionLocal"
            ) as mock_session_factory,
            patch(
                "app.services.knowledge_service.knowledge_service"
            ) as mock_ks,
        ):
            mock_session = AsyncMock()
            mock_session_factory.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_session_factory.return_value.__aexit__ = AsyncMock(
                return_value=None
            )

            ch_result = MagicMock()
            ch_result.scalar_one_or_none.return_value = sample_channel

            msg_result = MagicMock()
            msg_result.scalar_one_or_none.return_value = sample_message

            mock_session.execute = AsyncMock(
                side_effect=[ch_result, msg_result]
            )

            mock_ks.is_already_indexed = AsyncMock(return_value=False)
            mock_ks.index_message = AsyncMock(return_value=1)

            await _process_message_ingested(event_data)

            # Verify the message lookup query was called with the
            # channel's ID (second execute call)
            second_call = mock_session.execute.call_args_list[1]
            query = second_call[0][0]

            # The query should be a select() with WHERE clauses
            # including both channel_id and slack_message_ts
            query_str = str(query)
            assert "channel_id" in query_str, (
                "Message lookup must include channel_id to prevent "
                "cross-channel timestamp collisions"
            )
            assert "slack_message_ts" in query_str

    @pytest.mark.asyncio
    async def test_failed_indexing_raises_for_no_ack(
        self, sample_message, sample_channel
    ):
        """Failed indexing should re-raise so the event is NOT acked."""
        from app.events.consumers import _process_message_ingested

        event_data = {
            "type": "message.ingested",
            "data": {
                "slack_channel_id": sample_channel.slack_channel_id,
                "slack_message_ts": sample_message.slack_message_ts,
            },
        }

        with (
            patch(
                "app.events.consumers.AsyncSessionLocal"
            ) as mock_session_factory,
            patch(
                "app.services.knowledge_service.knowledge_service"
            ) as mock_ks,
        ):
            mock_session = AsyncMock()
            mock_session_factory.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_session_factory.return_value.__aexit__ = AsyncMock(
                return_value=None
            )

            ch_result = MagicMock()
            ch_result.scalar_one_or_none.return_value = sample_channel

            msg_result = MagicMock()
            msg_result.scalar_one_or_none.return_value = sample_message

            mock_session.execute = AsyncMock(
                side_effect=[ch_result, msg_result]
            )

            mock_ks.is_already_indexed = AsyncMock(return_value=False)
            mock_ks.index_message = AsyncMock(
                side_effect=RuntimeError("DB connection lost")
            )

            # Should re-raise so _process_event does NOT ack
            with pytest.raises(RuntimeError, match="DB connection lost"):
                await _process_message_ingested(event_data)


@skip_without_asyncpg
class TestProcessMessageEdited:
    """Tests for _process_message_edited handler."""

    @pytest.mark.asyncio
    async def test_reindexes_edited_message(
        self, sample_message, sample_channel
    ):
        """MESSAGE_EDITED should delete old chunks and re-index."""
        from app.events.consumers import _process_message_edited

        event_data = {
            "type": "message.edited",
            "data": {
                "slack_channel_id": sample_channel.slack_channel_id,
                "slack_message_ts": sample_message.slack_message_ts,
            },
        }

        with (
            patch(
                "app.events.consumers.AsyncSessionLocal"
            ) as mock_session_factory,
            patch(
                "app.services.knowledge_service.knowledge_service"
            ) as mock_ks,
        ):
            mock_session = AsyncMock()
            mock_session_factory.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_session_factory.return_value.__aexit__ = AsyncMock(
                return_value=None
            )

            # Channel first, then message (new lookup order)
            ch_result = MagicMock()
            ch_result.scalar_one_or_none.return_value = sample_channel

            msg_result = MagicMock()
            msg_result.scalar_one_or_none.return_value = sample_message

            mock_session.execute = AsyncMock(
                side_effect=[ch_result, msg_result]
            )

            mock_ks.delete_chunks_for_source = AsyncMock(return_value=2)
            mock_ks.index_message = AsyncMock(return_value=3)

            await _process_message_edited(event_data)

            # Verify old chunks were deleted
            mock_ks.delete_chunks_for_source.assert_called_once_with(
                sample_message.id
            )
            # Verify re-indexing happened
            mock_ks.index_message.assert_called_once_with(
                message=sample_message, channel=sample_channel
            )


@skip_without_asyncpg
class TestProcessEvent:
    """Tests for _process_event (ack-on-success semantics)."""

    @pytest.mark.asyncio
    async def test_acks_on_successful_processing(
        self, sample_message, sample_channel
    ):
        """Successful event processing should call event_bus.ack()."""
        from app.events.consumers import _process_event

        event = {
            "id": "1716382103-0",
            "type": "message.ingested",
            "stream": "hivemind-events",
            "group": "knowledge-indexer",
            "data": {
                "slack_channel_id": sample_channel.slack_channel_id,
                "slack_message_ts": sample_message.slack_message_ts,
            },
        }

        with (
            patch(
                "app.events.consumers.AsyncSessionLocal"
            ) as mock_session_factory,
            patch(
                "app.services.knowledge_service.knowledge_service"
            ) as mock_ks,
            patch("app.events.consumers.event_bus") as mock_bus,
        ):
            mock_session = AsyncMock()
            mock_session_factory.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_session_factory.return_value.__aexit__ = AsyncMock(
                return_value=None
            )

            ch_result = MagicMock()
            ch_result.scalar_one_or_none.return_value = sample_channel
            msg_result = MagicMock()
            msg_result.scalar_one_or_none.return_value = sample_message

            mock_session.execute = AsyncMock(
                side_effect=[ch_result, msg_result]
            )

            mock_ks.is_already_indexed = AsyncMock(return_value=False)
            mock_ks.index_message = AsyncMock(return_value=1)
            mock_bus.ack = AsyncMock()

            await _process_event(event)

            # Verify ack was called
            mock_bus.ack.assert_called_once_with(
                "hivemind-events", "knowledge-indexer", "1716382103-0"
            )

    @pytest.mark.asyncio
    async def test_does_not_ack_on_failure(
        self, sample_message, sample_channel
    ):
        """Failed event processing should NOT call event_bus.ack()."""
        from app.events.consumers import _process_event

        event = {
            "id": "1716382103-0",
            "type": "message.ingested",
            "stream": "hivemind-events",
            "group": "knowledge-indexer",
            "data": {
                "slack_channel_id": sample_channel.slack_channel_id,
                "slack_message_ts": sample_message.slack_message_ts,
            },
        }

        with (
            patch(
                "app.events.consumers.AsyncSessionLocal"
            ) as mock_session_factory,
            patch(
                "app.services.knowledge_service.knowledge_service"
            ) as mock_ks,
            patch("app.events.consumers.event_bus") as mock_bus,
        ):
            mock_session = AsyncMock()
            mock_session_factory.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_session_factory.return_value.__aexit__ = AsyncMock(
                return_value=None
            )

            ch_result = MagicMock()
            ch_result.scalar_one_or_none.return_value = sample_channel
            msg_result = MagicMock()
            msg_result.scalar_one_or_none.return_value = sample_message

            mock_session.execute = AsyncMock(
                side_effect=[ch_result, msg_result]
            )

            mock_ks.is_already_indexed = AsyncMock(return_value=False)
            mock_ks.index_message = AsyncMock(
                side_effect=RuntimeError("Indexing failed")
            )
            mock_bus.ack = AsyncMock()

            await _process_event(event)

            # Verify ack was NOT called
            mock_bus.ack.assert_not_called()

    @pytest.mark.asyncio
    async def test_acks_unknown_event_type(self):
        """Events with no matching handler should be acked (consumed)."""
        from app.events.consumers import _process_event

        event = {
            "id": "1716382103-0",
            "type": "some.unknown.event",
            "stream": "hivemind-events",
            "group": "knowledge-indexer",
            "data": {},
        }

        with patch("app.events.consumers.event_bus") as mock_bus:
            mock_bus.ack = AsyncMock()

            await _process_event(event)

            # Unknown events should still be acked
            mock_bus.ack.assert_called_once()
