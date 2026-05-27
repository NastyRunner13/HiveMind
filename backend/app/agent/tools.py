"""
Agent Tools — LangChain tool definitions wrapping HiveMind services.

These tools give the AI agent access to HiveMind's capabilities:
- Semantic search across the Knowledge Fabric
- Channel message retrieval
- Channel listing
- Channel activity summaries
- On-demand digest generation

SECURITY: Tools are created per-request via create_tools(), which
bakes the user's trusted ACL context into closures. The LLM never
sees or controls ACL parameters — they are injected from server-derived
context (channel memberships looked up from the database).
"""

import logging
from datetime import datetime, timedelta, timezone

from langchain_core.tools import tool
from sqlalchemy import func, select

from app.database import AsyncSessionLocal
from app.models.channel import Channel, ChannelType
from app.models.message import Message
from app.services.knowledge_service import knowledge_service

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════
# TOOL FACTORY — Creates tools with trusted user context baked in
# ═════════════════════════════════════════════════════════════════


def create_tools(user_slack_id: str, user_channel_ids: list[str]) -> list:
    """
    Create agent tools with trusted user context baked in via closures.

    The LLM never sees or controls ACL parameters — they are injected
    from server-derived context (channel memberships looked up from
    the database by the membership_service).

    Args:
        user_slack_id: The authenticated user's Slack ID (server-derived).
        user_channel_ids: Slack channel IDs the user is a member of (server-derived).

    Returns:
        List of LangChain tool instances scoped to this user's permissions.
    """

    @tool
    async def search_knowledge(query: str) -> str:
        """Search the team's Knowledge Fabric for relevant information.

        Use this when the user asks a question about past discussions, files,
        decisions, or any team knowledge. Returns relevant text chunks with
        source attribution.

        Args:
            query: The natural language search query.
        """
        results = await knowledge_service.search(
            query=query,
            user_channel_ids=user_channel_ids,
            user_slack_id=user_slack_id,
            top_k=5,
        )

        if not results:
            return "No relevant information found in the Knowledge Fabric."

        formatted = []
        for i, r in enumerate(results, 1):
            channel_info = (
                f" (channel: {r.source_channel_id})"
                if r.source_channel_id
                else ""
            )
            formatted.append(
                f"[{i}] (score: {r.score:.2f}, "
                f"source: {r.source_type}{channel_info})\n"
                f"{r.content}"
            )

        return "\n\n---\n\n".join(formatted)

    @tool
    async def get_recent_messages(
        channel_name: str = "",
        hours: int = 24,
        limit: int = 20,
    ) -> str:
        """Get recent messages from a specific channel.

        Use this when the user asks about recent activity in a channel,
        or wants to know what happened today/recently.

        Args:
            channel_name: Name of the Slack channel (without #).
            hours: How many hours back to look (default: 24).
            limit: Maximum number of messages to return (default: 20).
        """
        async with AsyncSessionLocal() as session:
            since = datetime.now(timezone.utc) - timedelta(hours=hours)

            # Find the channel
            query = select(Channel).where(
                Channel.name.ilike(f"%{channel_name}%")
            )
            result = await session.execute(query)
            channel = result.scalar_one_or_none()

            if not channel:
                return f"Channel '{channel_name}' not found."

            # ACL check: verify user has access to this channel
            if channel.slack_channel_id not in user_channel_ids:
                if channel.channel_type != ChannelType.PUBLIC:
                    return (
                        f"You don't have access to #{channel_name}. "
                        f"It's a {channel.channel_type.value} channel."
                    )

            # Fetch recent messages
            msg_query = (
                select(Message)
                .where(
                    Message.channel_id == channel.id,
                    Message.slack_sent_at >= since,
                )
                .order_by(Message.slack_sent_at.desc())
                .limit(limit)
            )
            msg_result = await session.execute(msg_query)
            messages = msg_result.scalars().all()

            if not messages:
                return (
                    f"No messages in #{channel_name} "
                    f"in the last {hours} hours."
                )

            formatted = []
            for msg in reversed(messages):  # Chronological order
                time_str = msg.slack_sent_at.strftime("%H:%M")
                content = (
                    msg.content[:200] if msg.content else "[no content]"
                )
                formatted.append(f"[{time_str}] {content}")

            return (
                f"Recent messages in #{channel_name} "
                f"(last {hours}h, {len(messages)} messages):\n\n"
                + "\n".join(formatted)
            )

    @tool
    async def list_channels() -> str:
        """List channels the user has access to in the workspace.

        Use this when the user asks about available channels, or when you
        need to find which channel a topic might be discussed in.
        """
        async with AsyncSessionLocal() as session:
            # Filter to channels the user is a member of + public channels
            query = (
                select(Channel)
                .where(
                    Channel.is_archived.is_(False),
                    # Show channels user is in, plus all public channels
                    (
                        Channel.slack_channel_id.in_(user_channel_ids)
                        | (Channel.channel_type == ChannelType.PUBLIC)
                    ),
                )
                .order_by(Channel.name)
                .limit(50)
            )
            result = await session.execute(query)
            channels = result.scalars().all()

            if not channels:
                return "No channels found."

            formatted = []
            for ch in channels:
                purpose = (
                    f" — {ch.purpose[:60]}..." if ch.purpose else ""
                )
                member_indicator = (
                    " ✓"
                    if ch.slack_channel_id in user_channel_ids
                    else ""
                )
                formatted.append(
                    f"• #{ch.name} ({ch.channel_type.value}, "
                    f"{ch.member_count} members){member_indicator}{purpose}"
                )

            return f"Channels ({len(channels)}):\n" + "\n".join(formatted)

    @tool
    async def get_channel_activity_summary(
        channel_name: str = "",
        hours: int = 24,
    ) -> str:
        """Get a quick activity summary for a channel.

        Use this to get stats about a channel's recent activity without
        reading all messages. Useful for deciding which channels to
        include in a digest.

        Args:
            channel_name: Name of the Slack channel (without #).
            hours: How many hours back to look (default: 24).
        """
        async with AsyncSessionLocal() as session:
            since = datetime.now(timezone.utc) - timedelta(hours=hours)

            query = select(Channel).where(
                Channel.name.ilike(f"%{channel_name}%")
            )
            result = await session.execute(query)
            channel = result.scalar_one_or_none()

            if not channel:
                return f"Channel '{channel_name}' not found."

            # ACL check: verify user has access
            if channel.slack_channel_id not in user_channel_ids:
                if channel.channel_type != ChannelType.PUBLIC:
                    return (
                        f"You don't have access to #{channel_name}. "
                        f"It's a {channel.channel_type.value} channel."
                    )

            # Count messages
            count_query = select(func.count(Message.id)).where(
                Message.channel_id == channel.id,
                Message.slack_sent_at >= since,
            )
            msg_count = (
                (await session.execute(count_query)).scalar() or 0
            )

            # Count threads
            thread_query = select(
                func.count(func.distinct(Message.thread_ts))
            ).where(
                Message.channel_id == channel.id,
                Message.slack_sent_at >= since,
                Message.thread_ts.isnot(None),
            )
            thread_count = (
                (await session.execute(thread_query)).scalar() or 0
            )

            return (
                f"#{channel_name} activity (last {hours}h):\n"
                f"• Messages: {msg_count}\n"
                f"• Active threads: {thread_count}\n"
                f"• Channel type: {channel.channel_type.value}\n"
                f"• Members: {channel.member_count}"
            )

    @tool
    async def generate_digest(
        channel_name: str = "",
        hours: int = 24,
        personalized: bool = False,
    ) -> str:
        """Generate a summary digest for a channel's recent activity.

        Use this when the user asks for a summary, digest, or recap of
        what happened in a channel. Returns a structured summary of key
        discussions, action items, and notable activity.

        When personalized=True, generates a digest across ALL channels the
        user has access to (including private channels), not just public ones.
        Use personalized mode when the user says things like "my digest",
        "summarize my channels", or "what did I miss".

        Args:
            channel_name: Name of the Slack channel (without #). Empty = all accessible channels.
            hours: How many hours back to summarize (default: 24).
            personalized: If True, include private channels the user has access to.
        """
        from app.services.digest_service import digest_service

        # Personalized digest: all channels the user is a member of
        if personalized and not channel_name:
            result = await digest_service.generate_personalized_digest(
                user_slack_id=user_slack_id,
                hours=hours,
            )
            if result:
                return f"📋 *Your Personalized Digest*\n\n{result}"
            else:
                return (
                    "No significant activity across your channels "
                    f"in the last {hours} hours."
                )

        if channel_name:
            # Generate for a specific channel
            async with AsyncSessionLocal() as session:
                from app.models.workspace import Workspace

                ws_result = await session.execute(
                    select(Workspace)
                    .where(Workspace.is_active.is_(True))
                    .limit(1)
                )
                workspace = ws_result.scalar_one_or_none()
                if not workspace:
                    return "No active workspace found."

                query = select(Channel).where(
                    Channel.name.ilike(f"%{channel_name}%")
                )
                result = await session.execute(query)
                channel = result.scalar_one_or_none()

                if not channel:
                    return f"Channel '{channel_name}' not found."

                # ACL check: skip private channels user isn't in
                if channel.slack_channel_id not in user_channel_ids:
                    if channel.channel_type != ChannelType.PUBLIC:
                        return (
                            f"You don't have access to #{channel_name}. "
                            f"It's a {channel.channel_type.value} channel."
                        )

                digest = await digest_service.generate_channel_digest(
                    channel_id=channel.id,
                    workspace_id=workspace.id,
                    hours=hours,
                )

            if digest:
                return f"Digest for #{channel_name}:\n\n{digest.content}"
            else:
                return (
                    f"No significant activity in #{channel_name} "
                    f"in the last {hours} hours."
                )
        else:
            # Generate for all accessible channels
            digests = await digest_service.generate_daily_digest()
            if digests:
                # Filter to channels user has access to
                accessible = [
                    d
                    for d in digests
                    if d.channel_id is None  # workspace-level
                ]
                parts = [d.content for d in (accessible or digests)]
                return "Daily Digest:\n\n" + "\n\n---\n\n".join(parts)
            else:
                return (
                    "No significant activity across channels "
                    "in the last 24 hours."
                )

    return [
        search_knowledge,
        get_recent_messages,
        list_channels,
        get_channel_activity_summary,
        generate_digest,
    ]
