"""
Slack Bot — initializes the Slack Bolt async app and registers event handlers.

This module is the main entry point for Slack integration. It creates
the AsyncApp, registers all event handlers from events.py, and provides
the startup/shutdown lifecycle for Socket Mode (dev) or Events API (prod).

Architecture:
  Slack Events → Bolt AsyncApp → Event Handlers → Ingestion Service → Database
"""

import logging

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Slack Bolt App ───────────────────────────────────────────────
# The AsyncApp handles event verification, routing, and middleware.
# It's created at module level but event handlers are registered
# lazily via register_handlers() to avoid circular imports.
slack_app: AsyncApp | None = None
socket_handler: AsyncSocketModeHandler | None = None


def create_slack_app() -> AsyncApp:
    """
    Create and configure the Slack Bolt AsyncApp.

    Returns None if Slack credentials are not configured,
    allowing the app to start without Slack (useful for testing).
    """
    global slack_app

    if not settings.slack_configured:
        logger.warning(
            "Slack credentials not configured. "
            "Set SLACK_BOT_TOKEN and SLACK_SIGNING_SECRET in .env"
        )
        return None

    slack_app = AsyncApp(
        token=settings.slack_bot_token,
        signing_secret=settings.slack_signing_secret,
    )

    # Register all event handlers
    from app.slack.events import register_event_handlers

    register_event_handlers(slack_app)

    logger.info("Slack Bolt app created and event handlers registered")
    return slack_app


async def start_slack_bot() -> None:
    """
    Start the Slack bot.

    In development: uses Socket Mode (no public URL needed).
    In production: relies on FastAPI routes for Events API webhooks.
    """
    global socket_handler

    if slack_app is None:
        logger.warning("Slack app not initialized — skipping bot startup")
        return

    if settings.slack_socket_mode:
        if not settings.slack_app_token:
            logger.error(
                "SLACK_APP_TOKEN is required for Socket Mode. "
                "Create an App-Level Token with 'connections:write' scope."
            )
            return

        socket_handler = AsyncSocketModeHandler(
            app=slack_app,
            app_token=settings.slack_app_token,
        )

        # Start socket mode in a background task so it doesn't block
        logger.info("Starting Slack bot in Socket Mode...")
        await socket_handler.connect_async()
        logger.info("✅ Slack bot connected via Socket Mode")
    else:
        logger.info(
            "Socket Mode disabled — Slack events will be received "
            "via HTTP at /slack/events"
        )


async def stop_slack_bot() -> None:
    """Gracefully disconnect the Slack bot."""
    global socket_handler

    if socket_handler is not None:
        logger.info("Disconnecting Slack bot...")
        await socket_handler.close_async()
        socket_handler = None
        logger.info("Slack bot disconnected")


def get_slack_app() -> AsyncApp | None:
    """Return the current Slack app instance."""
    return slack_app
