"""
Tests for app.slack.sync -- bulk sync utilities.

Verifies:
- Channel sync with pagination
- User sync (skipping Slackbot)
- Channel history backfill
- File metadata sync
- Error handling in each sync function
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

# ═════════════════════════════════════════════════════════════════
# SYNC CHANNELS
# ═════════════════════════════════════════════════════════════════


class TestSyncChannels:
    """Tests for sync_channels()."""

    @pytest.mark.asyncio
    @patch("app.slack.sync._ensure_workspace", new_callable=AsyncMock)
    @patch("app.slack.sync.ingest_channel_from_api", new_callable=AsyncMock)
    async def test_sync_channels_basic(
        self, mock_ingest, mock_ensure_ws, mock_slack_client
    ):
        """Should call ingest_channel_from_api for each channel."""
        mock_ingest.return_value = True  # All are new

        from app.slack.sync import sync_channels

        stats = await sync_channels(mock_slack_client)

        assert stats["synced"] == 2  # general + hivemind-test
        assert stats["new"] == 2
        assert mock_ingest.call_count == 2
        mock_ensure_ws.assert_called_once_with(mock_slack_client)

    @pytest.mark.asyncio
    @patch("app.slack.sync._ensure_workspace", new_callable=AsyncMock)
    @patch("app.slack.sync.ingest_channel_from_api", new_callable=AsyncMock)
    async def test_sync_channels_with_updates(
        self, mock_ingest, mock_ensure_ws, mock_slack_client
    ):
        """Should track new vs updated channels."""
        # First call: new, second call: existing
        mock_ingest.side_effect = [True, False]

        from app.slack.sync import sync_channels

        stats = await sync_channels(mock_slack_client)

        assert stats["synced"] == 2
        assert stats["new"] == 1
        assert stats["updated"] == 1

    @pytest.mark.asyncio
    @patch("app.slack.sync._ensure_workspace", new_callable=AsyncMock)
    @patch("app.slack.sync.ingest_channel_from_api", new_callable=AsyncMock)
    async def test_sync_channels_pagination(
        self, mock_ingest, mock_ensure_ws, mock_slack_client
    ):
        """Should handle paginated responses."""
        mock_ingest.return_value = True

        # First page has a cursor, second page doesn't
        mock_slack_client.conversations_list.side_effect = [
            {
                "ok": True,
                "channels": [{"id": "C1", "name": "chan1"}],
                "response_metadata": {"next_cursor": "cursor123"},
            },
            {
                "ok": True,
                "channels": [{"id": "C2", "name": "chan2"}],
                "response_metadata": {"next_cursor": ""},
            },
        ]

        from app.slack.sync import sync_channels

        stats = await sync_channels(mock_slack_client)

        assert stats["synced"] == 2
        assert mock_slack_client.conversations_list.call_count == 2

    @pytest.mark.asyncio
    @patch("app.slack.sync._ensure_workspace", new_callable=AsyncMock)
    @patch("app.slack.sync.ingest_channel_from_api", new_callable=AsyncMock)
    async def test_sync_channels_api_error(
        self, mock_ingest, mock_ensure_ws, mock_slack_client
    ):
        """Should stop gracefully on API error."""
        mock_slack_client.conversations_list.return_value = {
            "ok": False,
            "error": "invalid_auth",
        }

        from app.slack.sync import sync_channels

        stats = await sync_channels(mock_slack_client)

        assert stats["synced"] == 0
        mock_ingest.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.slack.sync._ensure_workspace", new_callable=AsyncMock)
    @patch("app.slack.sync.ingest_channel_from_api", new_callable=AsyncMock)
    async def test_sync_channels_ingestion_error(
        self, mock_ingest, mock_ensure_ws, mock_slack_client
    ):
        """If one channel fails to ingest, others should still succeed."""
        mock_ingest.side_effect = [Exception("DB error"), True]

        from app.slack.sync import sync_channels

        stats = await sync_channels(mock_slack_client)

        # One failed, one succeeded
        assert stats["synced"] == 1
        assert mock_ingest.call_count == 2


# ═════════════════════════════════════════════════════════════════
# SYNC USERS
# ═════════════════════════════════════════════════════════════════


class TestSyncUsers:
    """Tests for sync_users()."""

    @pytest.mark.asyncio
    @patch("app.slack.sync.ingest_user", new_callable=AsyncMock)
    async def test_sync_users_basic(self, mock_ingest, mock_slack_client):
        """Should call ingest_user for each user, skipping USLACKBOT."""
        mock_ingest.return_value = True

        from app.slack.sync import sync_users

        stats = await sync_users(mock_slack_client)

        # 2 members in fixture, but USLACKBOT is skipped
        assert stats["synced"] == 1
        assert stats["new"] == 1
        mock_ingest.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.slack.sync.ingest_user", new_callable=AsyncMock)
    async def test_sync_users_skips_slackbot(self, mock_ingest, mock_slack_client):
        """USLACKBOT should be skipped."""
        mock_ingest.return_value = True

        from app.slack.sync import sync_users

        await sync_users(mock_slack_client)

        # Verify the USLACKBOT user was never passed to ingest_user
        for call in mock_ingest.call_args_list:
            user_data = call[0][0]
            assert user_data.get("id") != "USLACKBOT"

    @pytest.mark.asyncio
    @patch("app.slack.sync.ingest_user", new_callable=AsyncMock)
    async def test_sync_users_api_error(self, mock_ingest, mock_slack_client):
        """Should stop gracefully on API error."""
        mock_slack_client.users_list.return_value = {
            "ok": False,
            "error": "invalid_auth",
        }

        from app.slack.sync import sync_users

        stats = await sync_users(mock_slack_client)

        assert stats["synced"] == 0


# ═════════════════════════════════════════════════════════════════
# SYNC CHANNEL HISTORY
# ═════════════════════════════════════════════════════════════════


class TestSyncChannelHistory:
    """Tests for sync_channel_history()."""

    @pytest.mark.asyncio
    @patch("app.slack.sync.ingest_message_from_history", new_callable=AsyncMock)
    async def test_sync_history_basic(self, mock_ingest, mock_slack_client):
        """Should ingest all messages from conversations.history."""
        from app.slack.sync import sync_channel_history

        stats = await sync_channel_history(mock_slack_client, "C_HIVEMIND_TEST")

        assert stats["fetched"] == 2
        assert stats["ingested"] == 2
        assert stats["errors"] == 0
        assert mock_ingest.call_count == 2

    @pytest.mark.asyncio
    @patch("app.slack.sync.ingest_message_from_history", new_callable=AsyncMock)
    async def test_sync_history_with_oldest(self, mock_ingest, mock_slack_client):
        """Should pass the 'oldest' parameter to the API."""
        oldest = datetime(2026, 1, 1, tzinfo=timezone.utc)

        from app.slack.sync import sync_channel_history

        await sync_channel_history(mock_slack_client, "C_HIVEMIND_TEST", oldest=oldest)

        call_kwargs = mock_slack_client.conversations_history.call_args.kwargs
        assert "oldest" in call_kwargs
        assert call_kwargs["oldest"] == str(oldest.timestamp())

    @pytest.mark.asyncio
    @patch("app.slack.sync.ingest_message_from_history", new_callable=AsyncMock)
    async def test_sync_history_respects_limit(self, mock_ingest, mock_slack_client):
        """Should request only up to 'limit' messages from the API."""
        # The sync function passes min(200, limit - fetched) to the API.
        # With limit=3, it requests 3. Our mock should return 3 messages
        # to simulate a well-behaved API.
        mock_slack_client.conversations_history.return_value = {
            "ok": True,
            "messages": [
                {"ts": f"17165000{i:02d}.000000", "text": f"msg {i}"} for i in range(3)
            ],
            "response_metadata": {"next_cursor": ""},
        }

        from app.slack.sync import sync_channel_history

        stats = await sync_channel_history(mock_slack_client, "C_TEST", limit=3)

        assert stats["fetched"] == 3
        assert stats["ingested"] == 3
        # Verify the API was called with the correct limit
        call_kwargs = mock_slack_client.conversations_history.call_args.kwargs
        assert call_kwargs["limit"] == 3

    @pytest.mark.asyncio
    @patch("app.slack.sync.ingest_message_from_history", new_callable=AsyncMock)
    async def test_sync_history_api_error(self, mock_ingest, mock_slack_client):
        """Should handle API errors gracefully."""
        mock_slack_client.conversations_history.return_value = {
            "ok": False,
            "error": "channel_not_found",
        }

        from app.slack.sync import sync_channel_history

        stats = await sync_channel_history(mock_slack_client, "C_INVALID")

        assert stats["fetched"] == 0
        assert stats["ingested"] == 0

    @pytest.mark.asyncio
    @patch("app.slack.sync.ingest_message_from_history", new_callable=AsyncMock)
    async def test_sync_history_ingestion_error(self, mock_ingest, mock_slack_client):
        """If one message fails, others should still be ingested."""
        mock_ingest.side_effect = [Exception("parse error"), None]

        from app.slack.sync import sync_channel_history

        stats = await sync_channel_history(mock_slack_client, "C_HIVEMIND_TEST")

        assert stats["fetched"] == 2
        assert stats["ingested"] == 1
        assert stats["errors"] == 1


# ═════════════════════════════════════════════════════════════════
# SYNC WORKSPACE FILES
# ═════════════════════════════════════════════════════════════════


class TestSyncWorkspaceFiles:
    """Tests for sync_workspace_files()."""

    @pytest.mark.asyncio
    @patch("app.slack.sync.ingest_file_metadata", new_callable=AsyncMock)
    async def test_sync_files_basic(self, mock_ingest, mock_slack_client):
        """Should ingest file metadata for each file."""
        from app.slack.sync import sync_workspace_files

        stats = await sync_workspace_files(mock_slack_client)

        assert stats["fetched"] == 1
        assert stats["ingested"] == 1
        mock_ingest.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.slack.sync.ingest_file_metadata", new_callable=AsyncMock)
    async def test_sync_files_api_error(self, mock_ingest, mock_slack_client):
        """Should handle API errors gracefully."""
        mock_slack_client.files_list.return_value = {
            "ok": False,
            "error": "invalid_auth",
        }

        from app.slack.sync import sync_workspace_files

        stats = await sync_workspace_files(mock_slack_client)

        assert stats["fetched"] == 0
        mock_ingest.assert_not_called()
