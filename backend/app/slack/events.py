"""
Slack Event Handlers — processes real-time events from Slack.

Each handler follows the pattern:
  1. Acknowledge the event (Slack requires ack within 3 seconds)
  2. Extract relevant data from the event payload
  3. Pass to the ingestion service for processing + DB storage

The handlers are designed to be lightweight — heavy processing
happens in the ingestion service, not here. This keeps Slack happy
with the 3-second timeout requirement.
"""

import logging

from slack_bolt.async_app import AsyncApp

logger = logging.getLogger(__name__)


def register_event_handlers(app: AsyncApp) -> None:
    """
    Register all Slack event handlers on the Bolt app.

    Called once during app startup. Each handler is an async function
    that receives the event data and supporting utilities from Bolt.
    """

    # ─────────────────────────────────────────────────────────────
    # MESSAGE EVENTS
    # ─────────────────────────────────────────────────────────────

    @app.event("message")
    async def handle_message(event: dict, say, client) -> None:
        """
        Handle incoming messages from channels the bot is in.

        Covers: new messages, edits, deletions, bot messages,
        thread replies, and system messages (join/leave/topic).
        """
        # Skip message subtypes we don't want to ingest
        subtype = event.get("subtype")
        skip_subtypes = {"message_deleted", "channel_join", "channel_leave"}

        if subtype in skip_subtypes:
            logger.debug(f"Skipping message subtype: {subtype}")
            return

        # Import here to avoid circular imports at module level
        from app.services.ingestion import ingest_message

        try:
            await ingest_message(event)
        except Exception as e:
            logger.error(f"Failed to ingest message: {e}", exc_info=True)

    # ─────────────────────────────────────────────────────────────
    # FILE EVENTS
    # ─────────────────────────────────────────────────────────────

    @app.event("file_shared")
    async def handle_file_shared(event: dict, client) -> None:
        """
        Handle file sharing events — index file metadata (not content).

        When a file is shared in a channel, we fetch its metadata
        from the Slack API and store it in our metadata index.
        The actual file content is never downloaded at this stage.
        """
        from app.services.ingestion import ingest_file_metadata

        file_id = event.get("file_id")
        if not file_id:
            logger.warning("file_shared event missing file_id")
            return

        try:
            # Fetch full file info from Slack API
            result = await client.files_info(file=file_id)
            if result["ok"]:
                file_info = result["file"]
                channel_id = event.get("channel_id")
                await ingest_file_metadata(file_info, channel_id)
            else:
                logger.warning(f"Failed to fetch file info: {result}")
        except Exception as e:
            logger.error(
                f"Failed to ingest file metadata for {file_id}: {e}",
                exc_info=True,
            )

    # ─────────────────────────────────────────────────────────────
    # CHANNEL EVENTS
    # ─────────────────────────────────────────────────────────────

    @app.event("channel_created")
    async def handle_channel_created(event: dict, client) -> None:
        """Handle new channel creation — add to our channel index."""
        from app.services.ingestion import ingest_channel

        channel_data = event.get("channel", {})
        try:
            await ingest_channel(channel_data)
            logger.info(f"New channel indexed: #{channel_data.get('name')}")
        except Exception as e:
            logger.error(f"Failed to index new channel: {e}", exc_info=True)

    @app.event("channel_rename")
    async def handle_channel_rename(event: dict) -> None:
        """Handle channel rename — update our index."""
        from app.services.ingestion import update_channel

        channel_data = event.get("channel", {})
        try:
            await update_channel(
                slack_channel_id=channel_data.get("id"),
                updates={"name": channel_data.get("name")},
            )
            logger.info(
                f"Channel renamed: {channel_data.get('id')} → "
                f"#{channel_data.get('name')}"
            )
        except Exception as e:
            logger.error(f"Failed to update channel name: {e}", exc_info=True)

    @app.event("channel_archive")
    async def handle_channel_archive(event: dict) -> None:
        """Handle channel archive."""
        from app.services.ingestion import update_channel

        try:
            await update_channel(
                slack_channel_id=event.get("channel"),
                updates={"is_archived": True},
            )
            logger.info(f"Channel archived: {event.get('channel')}")
        except Exception as e:
            logger.error(f"Failed to archive channel: {e}", exc_info=True)

    @app.event("channel_unarchive")
    async def handle_channel_unarchive(event: dict) -> None:
        """Handle channel unarchive."""
        from app.services.ingestion import update_channel

        try:
            await update_channel(
                slack_channel_id=event.get("channel"),
                updates={"is_archived": False},
            )
            logger.info(f"Channel unarchived: {event.get('channel')}")
        except Exception as e:
            logger.error(f"Failed to unarchive channel: {e}", exc_info=True)

    # ─────────────────────────────────────────────────────────────
    # USER EVENTS
    # ─────────────────────────────────────────────────────────────

    @app.event("team_join")
    async def handle_team_join(event: dict) -> None:
        """Handle new user joining the workspace."""
        from app.services.ingestion import ingest_user

        user_data = event.get("user", {})
        try:
            await ingest_user(user_data)
            logger.info(f"New user indexed: {user_data.get('real_name', 'unknown')}")
        except Exception as e:
            logger.error(f"Failed to index new user: {e}", exc_info=True)

    @app.event("member_joined_channel")
    async def handle_member_joined(event: dict) -> None:
        """
        Log when a user joins a channel — important for future RBAC.

        For now, we just log it. Later, this will update channel
        membership records used for ACL-scoped vector search.
        """
        logger.info(f"User {event.get('user')} joined channel {event.get('channel')}")

    # ─────────────────────────────────────────────────────────────
    # BOT MENTION
    # ─────────────────────────────────────────────────────────────

    @app.event("app_mention")
    async def handle_app_mention(event: dict, say) -> None:
        """
        Handle @HiveMind mentions — the main interaction point.

        For now, responds with a simple acknowledgment.
        Future: route to the AI agent for intent classification
        and response generation.
        """
        user = event.get("user")
        text = event.get("text", "")

        logger.info(f"Bot mentioned by {user}: {text}")

        await say(
            text=(
                f"👋 Hey <@{user}>! I'm HiveMind — your team intelligence agent. "
                f"I'm currently in setup mode, learning about your workspace. "
                f"I'll be able to help with questions, summaries, and tasks soon!"
            ),
            thread_ts=event.get("ts"),
        )

    # ─────────────────────────────────────────────────────────────
    # CATCH-ALL for unhandled events
    # ─────────────────────────────────────────────────────────────

    @app.event(
        event={"type": "message", "subtype": "message_changed"},
    )
    async def handle_message_changed(event: dict) -> None:
        """Handle message edits — update the stored message content."""
        from app.services.ingestion import handle_message_edit

        try:
            await handle_message_edit(event)
        except Exception as e:
            logger.error(f"Failed to handle message edit: {e}", exc_info=True)

    logger.info("All Slack event handlers registered")
