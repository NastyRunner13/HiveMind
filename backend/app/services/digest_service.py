"""
Digest Service — generates daily channel summaries using LLM.

This is the "morning briefing" feature from the v3 concept. It:
1. Fetches recent messages from active channels
2. Groups them by thread for context preservation
3. Sends them to the LLM for intelligent summarization
4. Stores the digest and optionally delivers to Slack

The service uses the same LLM as the agent but with a specialized
system prompt tuned for summarization.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.events.bus import EventType, event_bus
from app.models.channel import Channel, ChannelType
from app.models.digest import Digest, DigestType
from app.models.message import Message, MessageType
from app.models.workspace import Workspace

logger = logging.getLogger(__name__)
settings = get_settings()


class DigestService:
    """
    Generates daily channel and workspace summaries.

    Usage:
        service = DigestService()
        digest = await service.generate_channel_digest(channel_id)
        await service.deliver_to_slack(digest)
    """

    async def generate_channel_digest(
        self,
        channel_id: uuid.UUID,
        workspace_id: uuid.UUID,
        hours: int = 24,
        digest_type: DigestType = DigestType.DAILY,
    ) -> Digest | None:
        """
        Generate a digest for a specific channel.

        Fetches messages from the given time window, formats them
        for the LLM, and generates a structured summary.

        Args:
            channel_id: The internal channel UUID.
            workspace_id: The workspace UUID.
            hours: How many hours of history to summarize.
            digest_type: Type of digest being generated.

        Returns:
            A Digest object with the generated summary, or None if no activity.
        """
        time_end = datetime.now(timezone.utc)
        time_start = time_end - timedelta(hours=hours)

        async with AsyncSessionLocal() as session:
            # Get channel info
            channel = await session.get(Channel, channel_id)
            if not channel:
                logger.warning(f"Channel {channel_id} not found")
                return None

            # Fetch messages in the time range
            msg_query = (
                select(Message)
                .where(
                    and_(
                        Message.channel_id == channel_id,
                        Message.slack_sent_at >= time_start,
                        Message.slack_sent_at <= time_end,
                        Message.message_type == MessageType.USER,
                    )
                )
                .order_by(Message.slack_sent_at.asc())
                .limit(200)  # Cap to avoid huge LLM prompts
            )
            result = await session.execute(msg_query)
            messages = result.scalars().all()

            if not messages:
                logger.debug(f"No messages in #{channel.name} for digest")
                return None

            # Skip channels with minimal activity
            if len(messages) < 3:
                logger.debug(
                    f"Skipping #{channel.name} — only {len(messages)} messages"
                )
                return None

            # Format messages for the LLM
            formatted_messages = self._format_messages_for_llm(messages)
            time_range_str = (
                f"{time_start.strftime('%b %d, %H:%M')} — "
                f"{time_end.strftime('%b %d, %H:%M UTC')}"
            )

            # Generate summary using LLM
            summary = await self._generate_summary(
                channel_name=channel.name,
                time_range=time_range_str,
                messages_text=formatted_messages,
            )

            if not summary:
                return None

            # Store the digest
            digest = Digest(
                workspace_id=workspace_id,
                channel_id=channel_id,
                digest_type=digest_type,
                content=summary,
                message_count=len(messages),
                time_range_start=time_start,
                time_range_end=time_end,
                generated_by=f"{settings.llm_provider}/{settings.llm_model}",
            )
            session.add(digest)
            await session.commit()
            await session.refresh(digest)

            await event_bus.publish(
                EventType.DIGEST_GENERATED,
                {
                    "digest_id": str(digest.id),
                    "channel_name": channel.name,
                    "message_count": len(messages),
                    "digest_type": digest_type.value,
                },
            )

            logger.info(
                f"Generated {digest_type.value} digest for #{channel.name}: "
                f"{len(messages)} messages summarized"
            )
            return digest

    async def generate_daily_digest(
        self,
        workspace_id: uuid.UUID | None = None,
    ) -> list[Digest]:
        """
        Generate daily digests for all active channels in a workspace.

        Called by the scheduler every morning. Iterates through all
        non-archived channels with recent activity and generates
        individual channel digests.

        Returns:
            List of generated Digest objects.
        """
        async with AsyncSessionLocal() as session:
            # Find the workspace
            if workspace_id:
                workspace = await session.get(Workspace, workspace_id)
            else:
                result = await session.execute(
                    select(Workspace).where(Workspace.is_active.is_(True)).limit(1)
                )
                workspace = result.scalar_one_or_none()

            if not workspace:
                logger.warning("No active workspace found for digest generation")
                return []

            # Get all active PUBLIC channels only.
            # Private channels and DMs are excluded from global digests
            # to prevent data leaks. Personalized ACL-scoped digests
            # will be added in a future iteration.
            channel_query = select(Channel).where(
                and_(
                    Channel.workspace_id == workspace.id,
                    Channel.is_archived.is_(False),
                    Channel.channel_type == ChannelType.PUBLIC,
                )
            )
            result = await session.execute(channel_query)
            channels = result.scalars().all()

        # Generate digest for each channel
        digests = []
        for channel in channels:
            try:
                digest = await self.generate_channel_digest(
                    channel_id=channel.id,
                    workspace_id=workspace.id,
                    hours=24,
                    digest_type=DigestType.DAILY,
                )
                if digest:
                    digests.append(digest)
            except Exception as e:
                logger.error(
                    f"Failed to generate digest for #{channel.name}: {e}",
                    exc_info=True,
                )

        logger.info(
            f"Daily digest complete: {len(digests)} channel summaries generated"
        )
        return digests

    async def deliver_to_slack(
        self,
        digest: Digest,
        target_channel: str | None = None,
    ) -> bool:
        """
        Deliver a digest to Slack.

        Posts the digest content to the configured digest channel
        or a specified target channel.

        Args:
            digest: The Digest to deliver.
            target_channel: Override the default digest channel.

        Returns:
            True if delivery succeeded.
        """
        # Prefer posting to the source channel over a global digest channel
        if not target_channel and digest.channel_id:
            # Look up the source channel's Slack ID
            try:
                async with AsyncSessionLocal() as session:
                    source_channel = await session.get(Channel, digest.channel_id)
                    if source_channel:
                        external_channel_id = getattr(
                            source_channel, "external_channel_id", None
                        )
                        target_channel = (
                            external_channel_id
                            if isinstance(external_channel_id, str)
                            and external_channel_id
                            else source_channel.slack_channel_id
                        )
            except Exception as e:
                logger.warning(f"Could not resolve source channel for digest: {e}")

        channel = target_channel or settings.digest_channel
        if not channel:
            logger.warning("No digest channel configured — skipping delivery")
            return False

        if not settings.slack_configured:
            logger.warning("Slack not configured — skipping digest delivery")
            return False

        try:
            from app.integrations.slack.connector import SlackConnector
            from app.slack.bot import get_slack_app

            slack_app = get_slack_app()
            if not slack_app:
                return False

            connector = SlackConnector(slack_app.client)
            await connector.send_external_message(channel, digest.content)

            await event_bus.publish(
                EventType.DIGEST_DELIVERED,
                {
                    "digest_id": str(digest.id),
                    "channel": channel,
                },
            )

            logger.info(f"Digest delivered to {channel}")
            return True

        except Exception as e:
            logger.error(f"Failed to deliver digest to Slack: {e}")
            return False

    # ─────────────────────────────────────────────────────────────
    # PERSONALIZED DIGEST (ON-DEMAND)
    # ─────────────────────────────────────────────────────────────

    async def generate_personalized_digest(
        self,
        user_slack_id: str,
        canonical_user_id: uuid.UUID | None = None,
        hours: int = 24,
    ) -> str | None:
        """
        Generate a personalized digest for a specific user (on-demand).

        Unlike generate_daily_digest() which only covers PUBLIC channels,
        this includes ALL channels the user is a member of (public + private).
        The result is returned directly — NOT stored in the DB — since
        personalized digests are transient and generated only when requested.

        SECURITY: This method uses _generate_channel_summary_only() which
        does NOT persist summaries to the digests table. This prevents
        private-channel content from leaking through the digest API
        endpoints (GET /api/v1/digests), which return stored digests
        without per-user ACL checks.

        Supports dual-path identity resolution:
        - canonical_user_id (preferred): Looks up memberships via
          ChannelMembership.canonical_user_id and filters channels by
          Channel.id (internal UUID).
        - user_slack_id (fallback): Legacy Slack ID path using
          membership_service.get_user_channel_ids().

        Args:
            user_slack_id: The Slack user ID requesting the digest.
            canonical_user_id: Internal user UUID (OIDC path, preferred).
            hours: How many hours of history to summarize.

        Returns:
            Combined digest string, or None if no activity.
        """
        # --- Resolve channel access ---
        canonical_channel_ids: list[uuid.UUID] | None = None

        if canonical_user_id:
            # Preferred path: canonical UUID membership lookup
            from app.models.membership import ChannelMembership

            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(ChannelMembership.channel_id).where(
                        and_(
                            ChannelMembership.canonical_user_id == canonical_user_id,
                            ChannelMembership.is_active.is_(True),
                        )
                    )
                )
                canonical_channel_ids = [row[0] for row in result.all()]

            if not canonical_channel_ids:
                logger.info(
                    f"No canonical memberships for {canonical_user_id} — "
                    f"cannot generate personalized digest"
                )
                return None
        else:
            # Fallback: legacy Slack ID path
            from app.services.membership_service import membership_service

            user_channel_ids = await membership_service.get_user_channel_ids(
                user_slack_id
            )

            if not user_channel_ids:
                logger.info(
                    f"No channel memberships for {user_slack_id} — "
                    f"cannot generate personalized digest"
                )
                return None

        async with AsyncSessionLocal() as session:
            # Find the workspace
            result = await session.execute(
                select(Workspace).where(Workspace.is_active.is_(True)).limit(1)
            )
            workspace = result.scalar_one_or_none()

            if not workspace:
                logger.warning("No active workspace found for personalized digest")
                return None

            # Get channels the user is in (public + private)
            if canonical_channel_ids is not None:
                # UUID path: filter by Channel.id
                channel_query = select(Channel).where(
                    and_(
                        Channel.workspace_id == workspace.id,
                        Channel.is_archived.is_(False),
                        Channel.id.in_(canonical_channel_ids),
                    )
                )
            else:
                # Slack ID path: filter by slack_channel_id
                channel_query = select(Channel).where(
                    and_(
                        Channel.workspace_id == workspace.id,
                        Channel.is_archived.is_(False),
                        Channel.slack_channel_id.in_(user_channel_ids),
                    )
                )
            result = await session.execute(channel_query)
            channels = result.scalars().all()

        if not channels:
            return None

        # Generate summary for each channel WITHOUT storing to DB.
        # This is critical: generate_channel_digest() persists to the
        # digests table, which is readable without ACL checks.
        digest_parts = []
        for channel in channels:
            try:
                summary = await self._generate_channel_summary_only(
                    channel_id=channel.id,
                    hours=hours,
                )
                if summary:
                    digest_parts.append(f"**#{channel.name}**\n{summary}")
            except Exception as e:
                logger.error(
                    f"Failed to generate personalized digest for #{channel.name}: {e}",
                    exc_info=True,
                )

        if not digest_parts:
            return None

        identity_label = str(canonical_user_id) if canonical_user_id else user_slack_id
        logger.info(
            f"Personalized digest for {identity_label}: "
            f"{len(digest_parts)} channel summaries"
        )
        return "\n\n---\n\n".join(digest_parts)

    # ─────────────────────────────────────────────────────────────
    # PRIVATE HELPERS
    # ─────────────────────────────────────────────────────────────

    async def _generate_channel_summary_only(
        self,
        channel_id: uuid.UUID,
        hours: int = 24,
    ) -> str | None:
        """
        Generate a channel summary string WITHOUT persisting to DB.

        Used by generate_personalized_digest() to avoid storing
        private-channel content in the shared digests table. The
        digest API endpoints return stored digests without per-user
        ACL checks, so we must never persist private summaries.

        Args:
            channel_id: The internal channel UUID.
            hours: How many hours of history to summarize.

        Returns:
            Summary string, or None if no significant activity.
        """
        time_end = datetime.now(timezone.utc)
        time_start = time_end - timedelta(hours=hours)

        async with AsyncSessionLocal() as session:
            channel = await session.get(Channel, channel_id)
            if not channel:
                return None

            # Fetch messages in the time range
            msg_query = (
                select(Message)
                .where(
                    and_(
                        Message.channel_id == channel_id,
                        Message.slack_sent_at >= time_start,
                        Message.slack_sent_at <= time_end,
                        Message.message_type == MessageType.USER,
                    )
                )
                .order_by(Message.slack_sent_at.asc())
                .limit(200)
            )
            result = await session.execute(msg_query)
            messages = result.scalars().all()

            if not messages or len(messages) < 3:
                return None

            formatted_messages = self._format_messages_for_llm(messages)
            time_range_str = (
                f"{time_start.strftime('%b %d, %H:%M')} — "
                f"{time_end.strftime('%b %d, %H:%M UTC')}"
            )

            return await self._generate_summary(
                channel_name=channel.name,
                time_range=time_range_str,
                messages_text=formatted_messages,
            )

    def _format_messages_for_llm(self, messages: list[Message]) -> str:
        """Format messages into a text block for the LLM."""
        formatted = []
        for msg in messages:
            time_str = msg.slack_sent_at.strftime("%H:%M")
            thread_indicator = " [thread reply]" if msg.is_thread_reply else ""
            content = msg.content or "[no content]"
            formatted.append(f"[{time_str}]{thread_indicator} {content}")

        return "\n".join(formatted)

    async def _generate_summary(
        self,
        channel_name: str,
        time_range: str,
        messages_text: str,
    ) -> str | None:
        """Generate a summary using the configured LLM."""
        if not settings.llm_configured:
            logger.warning("LLM not configured — cannot generate digest")
            return None

        try:
            from app.agent.llm import get_llm
            from app.agent.prompts import CHANNEL_SUMMARY_PROMPT, DIGEST_SYSTEM_PROMPT

            llm = get_llm()

            prompt = CHANNEL_SUMMARY_PROMPT.format(
                channel_name=channel_name,
                time_range=time_range,
                messages=messages_text,
            )

            from langchain_core.messages import HumanMessage, SystemMessage

            response = await llm.ainvoke(
                [
                    SystemMessage(content=DIGEST_SYSTEM_PROMPT),
                    HumanMessage(content=prompt),
                ]
            )

            return response.content

        except Exception as e:
            logger.error(f"LLM digest generation failed: {e}", exc_info=True)
            return None


# ── Module-level singleton ──────────────────────────────────────
digest_service = DigestService()
