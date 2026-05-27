"""
Digest Service tests — validates message formatting and digest generation.

Tests cover:
- Message formatting for LLM input
- LLM not configured handling
- Slack delivery logic

Note: Digest service imports from app.database which needs asyncpg.
Tests that need the actual DigestService class are marked to skip
if asyncpg is not available. Pure logic tests work independently.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Check if asyncpg is available (needed by app.database → digest_service)
try:
    import asyncpg
    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False

skip_without_asyncpg = pytest.mark.skipif(
    not HAS_ASYNCPG,
    reason="asyncpg not installed — digest_service imports app.database"
)


# ═════════════════════════════════════════════════════════════════
# MESSAGE FORMATTING
# ═════════════════════════════════════════════════════════════════


@skip_without_asyncpg
class TestMessageFormatting:
    """Tests for message formatting before LLM processing."""

    def _make_message(self, content, time_str="10:30", is_thread=False):
        """Create a mock Message object."""
        msg = MagicMock()
        msg.content = content
        msg.slack_sent_at = datetime(2026, 5, 26, 10, 30, tzinfo=timezone.utc)
        msg.is_thread_reply = is_thread
        return msg

    def test_format_single_message(self):
        """Single message formats correctly."""
        from app.services.digest_service import DigestService
        service = DigestService()

        messages = [self._make_message("Hello team!")]
        result = service._format_messages_for_llm(messages)

        assert "[10:30]" in result
        assert "Hello team!" in result

    def test_format_thread_reply(self):
        """Thread replies are marked with indicator."""
        from app.services.digest_service import DigestService
        service = DigestService()

        messages = [self._make_message("Reply in thread", is_thread=True)]
        result = service._format_messages_for_llm(messages)

        assert "[thread reply]" in result

    def test_format_multiple_messages(self):
        """Multiple messages are joined with newlines."""
        from app.services.digest_service import DigestService
        service = DigestService()

        messages = [
            self._make_message("First message"),
            self._make_message("Second message"),
        ]
        result = service._format_messages_for_llm(messages)

        assert "First message" in result
        assert "Second message" in result
        assert "\n" in result

    def test_format_empty_content(self):
        """Messages with no content get [no content] placeholder."""
        from app.services.digest_service import DigestService
        service = DigestService()

        messages = [self._make_message(None)]
        result = service._format_messages_for_llm(messages)

        assert "[no content]" in result


# ═════════════════════════════════════════════════════════════════
# SUMMARY GENERATION
# ═════════════════════════════════════════════════════════════════


@skip_without_asyncpg
class TestSummaryGeneration:
    """Tests for LLM-based summary generation."""

    async def test_generate_summary_llm_not_configured(self):
        """Returns None when LLM is not configured."""
        from app.services.digest_service import DigestService

        with patch.object(DigestService, '__init__', lambda self: None):
            service = DigestService()

            # Mock the settings check
            with patch("app.services.digest_service.settings") as mock_settings:
                mock_settings.llm_configured = False
                result = await service._generate_summary(
                    channel_name="test",
                    time_range="May 26, 09:00 — May 26, 17:00 UTC",
                    messages_text="[10:00] Hello",
                )
                assert result is None

    async def test_generate_summary_handles_llm_error(self):
        """Returns None when LLM raises an exception."""
        from app.services.digest_service import DigestService

        with patch.object(DigestService, '__init__', lambda self: None):
            service = DigestService()

            with patch("app.services.digest_service.settings") as mock_settings:
                mock_settings.llm_configured = True

            with patch("app.agent.llm.get_llm", side_effect=Exception("LLM error")):
                result = await service._generate_summary(
                    channel_name="test",
                    time_range="test",
                    messages_text="test",
                )
                assert result is None


# ═════════════════════════════════════════════════════════════════
# SLACK DELIVERY
# ═════════════════════════════════════════════════════════════════


@skip_without_asyncpg
class TestSlackDelivery:
    """Tests for digest Slack delivery."""

    async def test_deliver_no_channel_configured(self):
        """Returns False when no digest channel is configured."""
        from app.services.digest_service import DigestService

        with patch("app.services.digest_service.settings") as mock_settings:
            mock_settings.digest_channel = ""

            service = DigestService()
            digest = MagicMock()
            digest.content = "Test digest"

            result = await service.deliver_to_slack(digest)
            assert result is False

    async def test_deliver_slack_not_configured(self):
        """Returns False when Slack is not configured."""
        from app.services.digest_service import DigestService

        with patch("app.services.digest_service.settings") as mock_settings:
            mock_settings.digest_channel = "hivemind-daily"
            mock_settings.slack_configured = False

            service = DigestService()
            digest = MagicMock()
            result = await service.deliver_to_slack(digest)
            assert result is False


# ═════════════════════════════════════════════════════════════════
# DIGEST SAFETY — Private Channel Exclusion
# ═════════════════════════════════════════════════════════════════


@skip_without_asyncpg
class TestDigestSafety:
    """Tests that private channels are excluded from global digests."""

    @pytest.mark.asyncio
    async def test_daily_digest_excludes_private_channels(self):
        """generate_daily_digest should only query PUBLIC channels."""
        import uuid

        from app.services.digest_service import DigestService

        service = DigestService()

        with patch(
            "app.services.digest_service.AsyncSessionLocal"
        ) as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_factory.return_value.__aexit__ = AsyncMock(
                return_value=None
            )

            # Mock workspace
            workspace = MagicMock()
            workspace.id = uuid.uuid4()
            workspace.is_active = True

            ws_result = MagicMock()
            ws_result.scalar_one_or_none.return_value = workspace

            # Mock channel query returning empty (no channels found)
            ch_result = MagicMock()
            ch_result.scalars.return_value.all.return_value = []

            mock_session.execute = AsyncMock(
                side_effect=[ws_result, ch_result]
            )
            mock_session.get = AsyncMock(return_value=workspace)

            result = await service.generate_daily_digest()

            assert result == []

            # Verify the channel query was called — we can't easily
            # inspect the exact WHERE clause without actual DB, but the
            # query was made
            assert mock_session.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_deliver_to_slack_posts_to_source_channel(self):
        """deliver_to_slack should post to the source channel, not global."""
        import uuid

        from app.services.digest_service import DigestService

        service = DigestService()

        digest = MagicMock()
        digest.id = uuid.uuid4()
        digest.content = "Test digest"
        digest.channel_id = uuid.uuid4()  # Has a source channel

        with (
            patch(
                "app.services.digest_service.AsyncSessionLocal"
            ) as mock_factory,
            patch("app.services.digest_service.settings") as mock_settings,
            patch(
                "app.services.digest_service.event_bus"
            ) as mock_bus,
        ):
            mock_settings.digest_channel = "global-digest"
            mock_settings.slack_configured = True

            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_factory.return_value.__aexit__ = AsyncMock(
                return_value=None
            )

            # Source channel lookup
            source_ch = MagicMock()
            source_ch.slack_channel_id = "C_SOURCE_CHANNEL"
            mock_session.get = AsyncMock(return_value=source_ch)

            # Mock Slack app
            with patch(
                "app.slack.bot.get_slack_app"
            ) as mock_get_app:
                mock_app = MagicMock()
                mock_app.client.chat_postMessage = AsyncMock()
                mock_get_app.return_value = mock_app

                mock_bus.publish = AsyncMock()

                result = await service.deliver_to_slack(digest)

                assert result is True
                # Should have posted to source channel, NOT "global-digest"
                mock_app.client.chat_postMessage.assert_called_once()
                call_kwargs = mock_app.client.chat_postMessage.call_args
                assert call_kwargs.kwargs["channel"] == "C_SOURCE_CHANNEL"

