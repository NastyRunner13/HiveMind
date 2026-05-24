"""
Tests for app.slack.bot -- Slack Bolt app creation and lifecycle.

Verifies:
- App creation with/without credentials
- Socket Mode startup and shutdown
- Graceful handling of missing tokens
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ═════════════════════════════════════════════════════════════════
# CREATE SLACK APP
# ═════════════════════════════════════════════════════════════════


class TestCreateSlackApp:
    """Tests for create_slack_app()."""

    @patch("app.slack.bot.get_settings")
    @patch("app.slack.bot.AsyncApp")
    def test_create_slack_app_success(
        self, mock_async_app_cls, mock_get_settings, mock_settings
    ):
        """With valid credentials, should create and return an AsyncApp."""
        mock_get_settings.return_value = mock_settings
        mock_app_instance = MagicMock()
        mock_async_app_cls.return_value = mock_app_instance

        # Reset module-level state
        import app.slack.bot as bot_module

        bot_module.settings = mock_settings
        bot_module.slack_app = None

        result = bot_module.create_slack_app()

        assert result is not None
        mock_async_app_cls.assert_called_once_with(
            token=mock_settings.slack_bot_token,
            signing_secret=mock_settings.slack_signing_secret,
        )

    @patch("app.slack.bot.get_settings")
    def test_create_slack_app_no_credentials(
        self, mock_get_settings, mock_settings_no_slack
    ):
        """Without credentials, should return None and log a warning."""
        mock_get_settings.return_value = mock_settings_no_slack

        import app.slack.bot as bot_module

        bot_module.settings = mock_settings_no_slack
        bot_module.slack_app = None

        result = bot_module.create_slack_app()

        assert result is None


# ═════════════════════════════════════════════════════════════════
# START SLACK BOT
# ═════════════════════════════════════════════════════════════════


class TestStartSlackBot:
    """Tests for start_slack_bot()."""

    @pytest.mark.asyncio
    @patch("app.slack.bot.AsyncSocketModeHandler")
    async def test_start_socket_mode(self, mock_handler_cls, mock_settings):
        """Socket Mode should call connect_async on the handler."""
        import app.slack.bot as bot_module

        mock_handler = AsyncMock()
        mock_handler_cls.return_value = mock_handler

        bot_module.settings = mock_settings
        bot_module.slack_app = MagicMock()  # Pretend app exists
        bot_module.socket_handler = None

        await bot_module.start_slack_bot()

        mock_handler_cls.assert_called_once()
        mock_handler.connect_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_no_app(self, mock_settings):
        """If slack_app is None, should skip startup gracefully."""
        import app.slack.bot as bot_module

        bot_module.settings = mock_settings
        bot_module.slack_app = None
        bot_module.socket_handler = None

        # Should not raise
        await bot_module.start_slack_bot()

    @pytest.mark.asyncio
    async def test_start_socket_mode_no_app_token(self, mock_settings):
        """Socket Mode without SLACK_APP_TOKEN should log error, not crash."""
        import app.slack.bot as bot_module

        mock_settings.slack_app_token = ""
        bot_module.settings = mock_settings
        bot_module.slack_app = MagicMock()
        bot_module.socket_handler = None

        # Should not raise
        await bot_module.start_slack_bot()


# ═════════════════════════════════════════════════════════════════
# STOP SLACK BOT
# ═════════════════════════════════════════════════════════════════


class TestStopSlackBot:
    """Tests for stop_slack_bot()."""

    @pytest.mark.asyncio
    async def test_stop_with_handler(self):
        """Should call close_async on the socket handler."""
        import app.slack.bot as bot_module

        mock_handler = AsyncMock()
        bot_module.socket_handler = mock_handler

        await bot_module.stop_slack_bot()

        mock_handler.close_async.assert_called_once()
        assert bot_module.socket_handler is None

    @pytest.mark.asyncio
    async def test_stop_without_handler(self):
        """Should handle None handler gracefully."""
        import app.slack.bot as bot_module

        bot_module.socket_handler = None

        # Should not raise
        await bot_module.stop_slack_bot()


# ═════════════════════════════════════════════════════════════════
# GET SLACK APP
# ═════════════════════════════════════════════════════════════════


class TestGetSlackApp:
    """Tests for get_slack_app()."""

    def test_returns_current_app(self):
        """Should return whatever slack_app is set to."""
        import app.slack.bot as bot_module

        mock_app = MagicMock()
        bot_module.slack_app = mock_app

        result = bot_module.get_slack_app()
        assert result is mock_app

    def test_returns_none_when_not_initialized(self):
        """Should return None when no app is created."""
        import app.slack.bot as bot_module

        bot_module.slack_app = None

        result = bot_module.get_slack_app()
        assert result is None
