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
from typing import Any

from slack_bolt.async_app import AsyncApp

logger = logging.getLogger(__name__)

AsyncSessionLocal: Any = None
digest_service: Any = None
membership_service: Any = None


def _get_async_session_local() -> Any:
    """Return the async session factory, importing lazily for testability."""
    global AsyncSessionLocal
    if AsyncSessionLocal is None:
        from app.database import AsyncSessionLocal as session_factory

        AsyncSessionLocal = session_factory
    return AsyncSessionLocal


def _get_digest_service() -> Any:
    """Return the digest service singleton, importing lazily for testability."""
    global digest_service
    if digest_service is None:
        from app.services.digest_service import digest_service as service

        digest_service = service
    return digest_service


def _get_membership_service() -> Any:
    """Return the membership service singleton, importing lazily for testability."""
    global membership_service
    if membership_service is None:
        from app.services.membership_service import membership_service as service

        membership_service = service
    return membership_service


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
        Handle a user joining a channel — persist membership for ACL.

        This updates channel membership records used for ACL-scoped
        vector search and agent tool authorization.
        """
        try:
            await _get_membership_service().handle_member_joined(
                slack_user_id=event.get("user"),
                slack_channel_id=event.get("channel"),
            )
        except Exception as e:
            logger.error(f"Failed to record membership join: {e}", exc_info=True)

    @app.event("member_left_channel")
    async def handle_member_left(event: dict) -> None:
        """
        Handle a user leaving a channel — deactivate membership for ACL.

        Soft-deletes the membership record so the user can no longer
        access content from this channel via agent tools or search.
        """
        try:
            await _get_membership_service().handle_member_left(
                slack_user_id=event.get("user"),
                slack_channel_id=event.get("channel"),
            )
        except Exception as e:
            logger.error(f"Failed to record membership leave: {e}", exc_info=True)

    # ─────────────────────────────────────────────────────────────
    # BOT MENTION
    # ─────────────────────────────────────────────────────────────

    @app.event("app_mention")
    async def handle_app_mention(event: dict, say, client) -> None:
        """
        Handle @HiveMind mentions — parse commands or route through AI agent.

        Supported commands:
        - @HiveMind digest          → generate digest for all channels
        - @HiveMind digest #channel → generate digest for a specific channel
        - @HiveMind help            → show available commands
        - (anything else)           → route through the AI agent

        This gives users a fast path for common actions while keeping
        the full agent available for natural language queries.
        """
        import re

        user = event.get("user")
        text = event.get("text", "")
        channel = event.get("channel")
        thread_ts = event.get("ts")

        logger.info(f"Bot mentioned by {user}: {text}")

        # Clean the mention from the text
        clean_text = re.sub(r"<@[A-Z0-9]+>", "", text).strip().lower()

        # ── Command: digest ──────────────────────────────────────
        if clean_text.startswith("digest"):
            await _handle_digest_command(
                clean_text=clean_text,
                channel=channel,
                thread_ts=thread_ts,
                say=say,
                user_slack_id=user,
            )
            return

        # ── Command: help ────────────────────────────────────────
        if clean_text in ("help", "commands", "?"):
            help_text = (
                "🐝 *HiveMind Commands*\n\n"
                "• `@HiveMind digest` — Get a daily digest for all channels\n"
                "• `@HiveMind digest #channel-name` — Get a digest for a specific channel\n"
                "• `@HiveMind help` — Show this help message\n"
                "• Or just ask me anything! I can search team conversations, "
                "find files, and answer questions about your workspace."
            )
            await say(text=help_text, thread_ts=thread_ts)
            return

        # ── Default: AI Agent ────────────────────────────────────
        from app.services.agent_service import agent_service

        # Derive trusted ACL context from DB — NOT from client
        user_channel_ids = await _get_membership_service().get_user_channel_ids(user)

        response = await agent_service.process_message(
            user_slack_id=user,
            message=text,
            channel_id=channel,
            thread_ts=thread_ts,
            user_channel_ids=user_channel_ids,
        )

        # Reply in thread
        await say(
            text=response.content,
            thread_ts=thread_ts,
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


async def _handle_digest_command(
    clean_text: str,
    channel: str,
    thread_ts: str,
    say,
    user_slack_id: str | None = None,
) -> None:
    """Handle the 'digest' command — generate on-demand digests.

    Supports:
    - @HiveMind digest              → all public channels
    - @HiveMind digest #channel     → specific channel
    - @HiveMind digest --me         → personalized (public + private)
    """
    import re

    digest_svc = _get_digest_service()

    # Check for --me flag (personalized digest)
    is_personalized = "--me" in clean_text

    # Extract optional channel: "digest #backend-team", "digest <#C0B5W4HHHEE|social>", or "digest <#C0B5W4HHHEE>"
    parts = clean_text.replace("digest", "", 1).replace("--me", "").strip()
    channel_id = None
    channel_name = None
    if parts:
        # Check for Slack mention format: <#C0B5W4HHHEE|social> or <#C0B5W4HHHEE>
        mention_match = re.match(r"^<#([A-Z0-9]+)(?:\|([^>]+))?>$", parts, re.IGNORECASE)
        if mention_match:
            channel_id = mention_match.group(1).upper()
            channel_name = mention_match.group(2)
        else:
            # Remove # prefix if present
            channel_name = re.sub(r"^#", "", parts).strip()

    await say(
        text="🐝 Generating digest... one moment!",
        thread_ts=thread_ts,
    )

    try:
        # Personalized digest: includes private channels the user is in
        if is_personalized and not channel_id and not channel_name:
            if not user_slack_id:
                await say(
                    text="❌ Could not determine your user identity.",
                    thread_ts=thread_ts,
                )
                return

            result = await digest_svc.generate_personalized_digest(
                user_slack_id=user_slack_id,
            )
            if result:
                await say(
                    text=f"📋 *Your Personalized Digest*\n\n{result}",
                    thread_ts=thread_ts,
                )
            else:
                await say(
                    text="No significant activity across your channels in the last 24 hours.",
                    thread_ts=thread_ts,
                )
            return

        if channel_id or channel_name:
            # Generate for a specific channel
            from sqlalchemy import select

            from app.models.channel import Channel
            from app.models.workspace import Workspace

            async with _get_async_session_local()() as session:
                # Find workspace
                ws_result = await session.execute(
                    select(Workspace).where(Workspace.is_active.is_(True)).limit(1)
                )
                workspace = ws_result.scalar_one_or_none()
                if not workspace:
                    await say(text="❌ No active workspace found.", thread_ts=thread_ts)
                    return

                # Find channel by ID or Name
                if channel_id:
                    ch_result = await session.execute(
                        select(Channel).where(
                            Channel.slack_channel_id == channel_id,
                            Channel.workspace_id == workspace.id,
                        )
                    )
                else:
                    ch_result = await session.execute(
                        select(Channel).where(
                            Channel.name.ilike(f"%{channel_name}%"),
                            Channel.workspace_id == workspace.id,
                        )
                    )
                ch = ch_result.scalar_one_or_none()
                if not ch:
                    display_name = f"#{channel_name}" if channel_name else f"<#{channel_id}>"
                    await say(
                        text=f"❌ Channel `{display_name}` not found.",
                        thread_ts=thread_ts,
                    )
                    return

                # ACL: block private-channel digests if user is not a member
                from app.models.channel import ChannelType

                if ch.channel_type != ChannelType.PUBLIC:
                    user_channels = await _get_membership_service().get_user_channel_ids(
                        user_slack_id
                    )
                    if ch.slack_channel_id not in user_channels:
                        await say(
                            text="🔒 You don't have access to that channel's digest.",
                            thread_ts=thread_ts,
                        )
                        return

                display_channel_name = ch.name

                digest = await digest_svc.generate_channel_digest(
                    channel_id=ch.id,
                    workspace_id=workspace.id,
                    hours=24,
                )

            if digest:
                await say(
                    text=f"📋 *Digest for #{display_channel_name}*\n\n{digest.content}",
                    thread_ts=thread_ts,
                )
            else:
                await say(
                    text=f"No significant activity in #{display_channel_name} in the last 24 hours.",
                    thread_ts=thread_ts,
                )
        else:
            # Generate for all channels
            digests = await digest_svc.generate_daily_digest()
            if digests:
                summary_parts = []
                for d in digests:
                    summary_parts.append(d.content)
                full_digest = "\n\n---\n\n".join(summary_parts)
                await say(
                    text=f"📋 *Daily Digest*\n\n{full_digest}",
                    thread_ts=thread_ts,
                )
            else:
                await say(
                    text="No significant activity across channels in the last 24 hours.",
                    thread_ts=thread_ts,
                )

    except Exception as e:
        logger.error(f"Digest command failed: {e}", exc_info=True)
        await say(
            text="❌ Failed to generate digest. Please try again.",
            thread_ts=thread_ts,
        )
