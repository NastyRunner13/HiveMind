"""
Tests for the Knowledge Indexing Consumer.

Tests the event consumer that processes normalized events from Redis
Streams and indexes messages into the Knowledge Fabric.

All event payloads use canonical internal UUIDs (channel_id, message_id)
as emitted by normalized_payload() from the ingestion service.

Tests cover:
- Successful indexing flow (normalized UUID events)
- Idempotency (skip already-indexed)
- Missing/invalid UUID handling
- Unknown message/channel handling
- Mismatched channel-message association (ACL safety)
- Re-indexing on message edit
- Deletion chunk cleanup
- Channel/membership ACL revalidation
- Ack-on-success semantics (failures leave messages pending)
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Check if asyncpg is available (needed by app.database → consumers)
try:
    import asyncpg  # noqa: F401

    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False

skip_without_asyncpg = pytest.mark.skipif(
    not HAS_ASYNCPG,
    reason="asyncpg not installed — consumers imports app.database",
)


@pytest.fixture
def sample_message():
    """Create a mock message object with a matching channel_id."""
    msg = MagicMock()
    msg.id = uuid.uuid4()
    msg.slack_message_ts = "1716382103.001234"
    msg.content = "Test message for indexing"
    msg.slack_sent_at = datetime.now(timezone.utc)
    # channel_id will be set per-test to match the sample_channel
    msg.channel_id = None
    return msg


@pytest.fixture
def sample_channel():
    """Create a mock channel object."""
    ch = MagicMock()
    ch.id = uuid.uuid4()
    ch.slack_channel_id = "C024BE91L"
    ch.name = "test-channel"
    ch.channel_type = MagicMock(value="public")
    ch.workspace_id = uuid.uuid4()
    return ch


def _normalized_event_data(channel, message):
    """Build a normalized event data dict from sample objects."""
    return {
        "schema_version": 1,
        "platform": "slack",
        "channel_id": str(channel.id),
        "message_id": str(message.id),
    }


def _mock_session_factory():
    """Create a mock async session factory with context manager support."""
    mock_factory = MagicMock()
    mock_session = AsyncMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return mock_factory, mock_session


@skip_without_asyncpg
class TestProcessMessageIngested:
    """Tests for _process_message_ingested handler."""

    @pytest.mark.asyncio
    async def test_indexes_new_message(self, sample_message, sample_channel):
        """MESSAGE_INGESTED event should create document_chunks for new messages."""
        from app.events.consumers import _process_message_ingested

        sample_message.channel_id = sample_channel.id
        event_data = {
            "type": "message.ingested",
            "data": _normalized_event_data(sample_channel, sample_message),
        }

        with (
            patch("app.events.consumers.AsyncSessionLocal") as mock_factory,
            patch("app.services.knowledge_service.knowledge_service") as mock_ks,
        ):
            session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
            session.get = AsyncMock(side_effect=[sample_channel, sample_message])

            mock_ks.is_already_indexed = AsyncMock(return_value=False)
            mock_ks.index_message = AsyncMock(return_value=3)

            await _process_message_ingested(event_data)

            mock_ks.index_message.assert_called_once_with(
                message=sample_message, channel=sample_channel
            )

    @pytest.mark.asyncio
    async def test_skips_already_indexed_message(self, sample_message, sample_channel):
        """MESSAGE_INGESTED should skip messages that are already indexed."""
        from app.events.consumers import _process_message_ingested

        sample_message.channel_id = sample_channel.id
        event_data = {
            "type": "message.ingested",
            "data": _normalized_event_data(sample_channel, sample_message),
        }

        with (
            patch("app.events.consumers.AsyncSessionLocal") as mock_factory,
            patch("app.services.knowledge_service.knowledge_service") as mock_ks,
        ):
            session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
            session.get = AsyncMock(side_effect=[sample_channel, sample_message])

            mock_ks.is_already_indexed = AsyncMock(return_value=True)
            mock_ks.index_message = AsyncMock()

            await _process_message_ingested(event_data)

            # index_message should NOT be called
            mock_ks.index_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_missing_fields(self):
        """Events with missing channel_id/message_id should be rejected."""
        from app.events.consumers import _process_message_ingested

        event_data = {
            "type": "message.ingested",
            "data": {},  # Missing channel_id and message_id
        }

        # Should not raise — returns cleanly
        await _process_message_ingested(event_data)

    @pytest.mark.asyncio
    async def test_skips_invalid_uuids(self):
        """Events with malformed UUIDs should be rejected."""
        from app.events.consumers import _process_message_ingested

        event_data = {
            "type": "message.ingested",
            "data": {
                "channel_id": "not-a-uuid",
                "message_id": "also-not-a-uuid",
            },
        }

        with patch("app.events.consumers.AsyncSessionLocal") as mock_factory:
            session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            # Should not raise
            await _process_message_ingested(event_data)

            # session.get should not be called for invalid UUIDs
            session.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_unknown_channel(self, sample_message):
        """Event for a channel not in DB should be skipped."""
        from app.events.consumers import _process_message_ingested

        fake_channel_id = uuid.uuid4()
        event_data = {
            "type": "message.ingested",
            "data": {
                "channel_id": str(fake_channel_id),
                "message_id": str(sample_message.id),
            },
        }

        with patch("app.events.consumers.AsyncSessionLocal") as mock_factory:
            session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            # Channel not found, message found
            session.get = AsyncMock(side_effect=[None, sample_message])

            # Should not raise
            await _process_message_ingested(event_data)

    @pytest.mark.asyncio
    async def test_skips_unknown_message(self, sample_channel):
        """Event for a message not in DB should be skipped."""
        from app.events.consumers import _process_message_ingested

        fake_message_id = uuid.uuid4()
        event_data = {
            "type": "message.ingested",
            "data": {
                "channel_id": str(sample_channel.id),
                "message_id": str(fake_message_id),
            },
        }

        with patch("app.events.consumers.AsyncSessionLocal") as mock_factory:
            session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            # Channel found, message not found
            session.get = AsyncMock(side_effect=[sample_channel, None])

            # Should not raise
            await _process_message_ingested(event_data)

    @pytest.mark.asyncio
    async def test_skips_mismatched_channel_message(
        self, sample_message, sample_channel
    ):
        """Events where message.channel_id != channel.id should be rejected.

        This prevents ACL spoofing where a forged event payload pairs a
        message from one channel with a different channel's UUID.
        """
        from app.events.consumers import _process_message_ingested

        # Set message.channel_id to a DIFFERENT channel than the one in the event
        other_channel_id = uuid.uuid4()
        sample_message.channel_id = other_channel_id

        event_data = {
            "type": "message.ingested",
            "data": _normalized_event_data(sample_channel, sample_message),
        }

        with (
            patch("app.events.consumers.AsyncSessionLocal") as mock_factory,
            patch("app.services.knowledge_service.knowledge_service") as mock_ks,
        ):
            session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
            session.get = AsyncMock(side_effect=[sample_channel, sample_message])

            mock_ks.index_message = AsyncMock()

            await _process_message_ingested(event_data)

            # Must NOT index — channel/message association mismatch
            mock_ks.index_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_failed_indexing_raises_for_no_ack(
        self, sample_message, sample_channel
    ):
        """Failed indexing should re-raise so the event is NOT acked."""
        from app.events.consumers import _process_message_ingested

        sample_message.channel_id = sample_channel.id
        event_data = {
            "type": "message.ingested",
            "data": _normalized_event_data(sample_channel, sample_message),
        }

        with (
            patch("app.events.consumers.AsyncSessionLocal") as mock_factory,
            patch("app.services.knowledge_service.knowledge_service") as mock_ks,
        ):
            session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
            session.get = AsyncMock(side_effect=[sample_channel, sample_message])

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
    async def test_reindexes_edited_message(self, sample_message, sample_channel):
        """MESSAGE_EDITED should delete old chunks and re-index."""
        from app.events.consumers import _process_message_edited

        sample_message.channel_id = sample_channel.id
        event_data = {
            "type": "message.edited",
            "data": _normalized_event_data(sample_channel, sample_message),
        }

        with (
            patch("app.events.consumers.AsyncSessionLocal") as mock_factory,
            patch("app.services.knowledge_service.knowledge_service") as mock_ks,
        ):
            session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
            session.get = AsyncMock(side_effect=[sample_channel, sample_message])

            mock_ks.delete_chunks_for_source = AsyncMock(return_value=2)
            mock_ks.index_message = AsyncMock(return_value=3)

            await _process_message_edited(event_data)

            # Verify old chunks were deleted
            mock_ks.delete_chunks_for_source.assert_called_once_with(sample_message.id)
            # Verify re-indexing happened
            mock_ks.index_message.assert_called_once_with(
                message=sample_message, channel=sample_channel
            )


@skip_without_asyncpg
class TestProcessMessageDeleted:
    """Tests for _process_message_deleted handler."""

    @pytest.mark.asyncio
    async def test_deletes_chunks_for_message_event(
        self, sample_message, sample_channel
    ):
        """MESSAGE_DELETED should remove chunks for the deleted source."""
        from app.events.consumers import _process_message_deleted

        sample_message.channel_id = sample_channel.id
        event_data = {
            "type": "message.deleted",
            "data": _normalized_event_data(sample_channel, sample_message),
        }

        with (
            patch("app.events.consumers.AsyncSessionLocal") as mock_factory,
            patch("app.services.knowledge_service.knowledge_service") as mock_ks,
        ):
            session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
            session.get = AsyncMock(side_effect=[sample_channel, sample_message])
            mock_ks.delete_chunks_for_source = AsyncMock(return_value=2)

            await _process_message_deleted(event_data)

            mock_ks.delete_chunks_for_source.assert_called_once_with(sample_message.id)

    @pytest.mark.asyncio
    async def test_deleted_event_registered_for_ack(
        self, sample_message, sample_channel
    ):
        """The event router should process and ack message.deleted events."""
        from app.events.consumers import _process_event

        sample_message.channel_id = sample_channel.id
        event = {
            "id": "1716382103-0",
            "type": "message.deleted",
            "stream": "hivemind-events",
            "group": "knowledge-indexer",
            "data": _normalized_event_data(sample_channel, sample_message),
        }

        with (
            patch("app.events.consumers.AsyncSessionLocal") as mock_factory,
            patch("app.services.knowledge_service.knowledge_service") as mock_ks,
            patch("app.events.consumers.event_bus") as mock_bus,
        ):
            session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
            session.get = AsyncMock(side_effect=[sample_channel, sample_message])
            mock_ks.delete_chunks_for_source = AsyncMock(return_value=1)
            mock_bus.ack = AsyncMock()

            await _process_event(event)

            mock_bus.ack.assert_called_once_with(
                "hivemind-events", "knowledge-indexer", "1716382103-0"
            )


@skip_without_asyncpg
class TestProcessACLRevalidationEvents:
    """Tests for channel/membership ACL revalidation events."""

    @pytest.mark.asyncio
    async def test_channel_updated_revalidates_channel_acl(self, sample_channel):
        """CHANNEL_UPDATED should refresh ACL metadata for channel chunks."""
        from app.events.consumers import _process_channel_updated

        event_data = {
            "type": "channel.updated",
            "data": {
                "schema_version": 1,
                "platform": "slack",
                "workspace_id": str(sample_channel.workspace_id),
                "channel_id": str(sample_channel.id),
            },
        }

        with (
            patch("app.events.consumers.AsyncSessionLocal") as mock_factory,
            patch("app.services.knowledge_service.knowledge_service") as mock_ks,
        ):
            session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
            session.get = AsyncMock(return_value=sample_channel)
            mock_ks.revalidate_channel_acl = AsyncMock(
                return_value={"updated": 1, "deleted": 0}
            )

            await _process_channel_updated(event_data)

            mock_ks.revalidate_channel_acl.assert_awaited_once_with(
                sample_channel.id,
                workspace_id=sample_channel.workspace_id,
            )

    @pytest.mark.asyncio
    async def test_membership_updated_revalidates_channel_acl(self, sample_channel):
        """MEMBERSHIP_UPDATED should refresh ACL verification metadata."""
        from app.events.consumers import _process_membership_updated

        event_data = {
            "type": "membership.updated",
            "data": {
                "schema_version": 1,
                "platform": "slack",
                "workspace_id": str(sample_channel.workspace_id),
                "channel_id": str(sample_channel.id),
            },
        }

        with (
            patch("app.events.consumers.AsyncSessionLocal") as mock_factory,
            patch("app.services.knowledge_service.knowledge_service") as mock_ks,
        ):
            session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
            session.get = AsyncMock(return_value=sample_channel)
            mock_ks.revalidate_channel_acl = AsyncMock(
                return_value={"updated": 1, "deleted": 0}
            )

            await _process_membership_updated(event_data)

            mock_ks.revalidate_channel_acl.assert_awaited_once_with(
                sample_channel.id,
                workspace_id=sample_channel.workspace_id,
            )


@skip_without_asyncpg
class TestProcessEvent:
    """Tests for _process_event (ack-on-success semantics)."""

    @pytest.mark.asyncio
    async def test_acks_on_successful_processing(self, sample_message, sample_channel):
        """Successful event processing should call event_bus.ack()."""
        from app.events.consumers import _process_event

        sample_message.channel_id = sample_channel.id
        event = {
            "id": "1716382103-0",
            "type": "message.ingested",
            "stream": "hivemind-events",
            "group": "knowledge-indexer",
            "data": _normalized_event_data(sample_channel, sample_message),
        }

        with (
            patch("app.events.consumers.AsyncSessionLocal") as mock_factory,
            patch("app.services.knowledge_service.knowledge_service") as mock_ks,
            patch("app.events.consumers.event_bus") as mock_bus,
        ):
            session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
            session.get = AsyncMock(side_effect=[sample_channel, sample_message])

            mock_ks.is_already_indexed = AsyncMock(return_value=False)
            mock_ks.index_message = AsyncMock(return_value=1)
            mock_bus.ack = AsyncMock()

            await _process_event(event)

            # Verify ack was called
            mock_bus.ack.assert_called_once_with(
                "hivemind-events", "knowledge-indexer", "1716382103-0"
            )

    @pytest.mark.asyncio
    async def test_does_not_ack_on_failure(self, sample_message, sample_channel):
        """Failed event processing should NOT call event_bus.ack()."""
        from app.events.consumers import _process_event

        sample_message.channel_id = sample_channel.id
        event = {
            "id": "1716382103-0",
            "type": "message.ingested",
            "stream": "hivemind-events",
            "group": "knowledge-indexer",
            "data": _normalized_event_data(sample_channel, sample_message),
        }

        with (
            patch("app.events.consumers.AsyncSessionLocal") as mock_factory,
            patch("app.services.knowledge_service.knowledge_service") as mock_ks,
            patch("app.events.consumers.event_bus") as mock_bus,
        ):
            session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
            session.get = AsyncMock(side_effect=[sample_channel, sample_message])

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
