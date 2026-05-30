"""
Agent tool definitions wrapping HiveMind services.

Tools are created per request with trusted ACL context closed over from the
server. The LLM can choose tool inputs such as query text and time window, but
it never receives user IDs, channel membership lists, or workspace scope.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from langchain_core.tools import tool
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, or_, select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.channel import Channel, ChannelType
from app.models.message import Message
from app.models.workspace import Workspace
from app.services.knowledge_service import knowledge_service

logger = logging.getLogger(__name__)

DEFAULT_AGENT_TOOL_TIMEOUT_SECONDS = 20.0
MIN_AGENT_TOOL_TIMEOUT_SECONDS = 1.0
MAX_AGENT_TOOL_TIMEOUT_SECONDS = 60.0


def _tool_timeout_seconds() -> float:
    """Return a bounded per-tool timeout from settings."""
    value = getattr(
        get_settings(),
        "agent_tool_timeout_seconds",
        DEFAULT_AGENT_TOOL_TIMEOUT_SECONDS,
    )
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return DEFAULT_AGENT_TOOL_TIMEOUT_SECONDS
    return max(
        MIN_AGENT_TOOL_TIMEOUT_SECONDS,
        min(float(value), MAX_AGENT_TOOL_TIMEOUT_SECONDS),
    )


async def _run_tool_with_timeout(coro, tool_name: str) -> str:
    """Run an agent tool with a hard timeout and a safe user-facing response."""
    timeout = _tool_timeout_seconds()
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except TimeoutError:
        logger.warning("Agent tool %s timed out after %.1fs", tool_name, timeout)
        return (
            f"Tool '{tool_name}' timed out after {timeout:g} seconds. "
            "Try a narrower request."
        )


class SearchKnowledgeArgs(BaseModel):
    """Bounded semantic search arguments exposed to the LLM."""

    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=50)
    hours: int | None = Field(default=None, ge=1, le=168)
    since: datetime | None = None
    until: datetime | None = None

    @model_validator(mode="after")
    def validate_window(self) -> "SearchKnowledgeArgs":
        if self.since and self.until and self.until < self.since:
            raise ValueError("until must be greater than or equal to since")
        return self


class RecentMessagesArgs(BaseModel):
    """Bounded recent-message lookup arguments exposed to the LLM."""

    channel_name: str = Field(default="", max_length=80)
    hours: int = Field(default=24, ge=1, le=168)
    limit: int = Field(default=20, ge=1, le=100)


class ChannelActivityArgs(BaseModel):
    """Bounded channel activity arguments exposed to the LLM."""

    channel_name: str = Field(default="", max_length=80)
    hours: int = Field(default=24, ge=1, le=168)


class GenerateDigestArgs(BaseModel):
    """Bounded digest arguments exposed to the LLM."""

    channel_name: str = Field(default="", max_length=80)
    hours: int = Field(default=24, ge=1, le=168)
    personalized: bool = False


class SummarizeActivityArgs(BaseModel):
    """Deterministic time-window summary arguments exposed to the LLM."""

    channel_name: str | None = Field(default=None, max_length=80)
    hours: int = Field(default=24, ge=1, le=168)
    topic: str | None = Field(default=None, max_length=300)
    personalized: bool = True


def _is_member_channel(
    channel: Channel,
    user_channel_ids: list[str],
    canonical_channel_ids: list[uuid.UUID] | None,
) -> bool:
    """Return whether the server-derived membership context includes channel."""
    ext_id = getattr(channel, "external_channel_id", None)
    return (
        channel.slack_channel_id in user_channel_ids
        or (bool(ext_id) and ext_id in user_channel_ids)
        or (
            canonical_channel_ids is not None
            and channel.id in set(canonical_channel_ids)
        )
    )


def _can_read_channel(
    channel: Channel,
    user_channel_ids: list[str],
    canonical_channel_ids: list[uuid.UUID] | None,
) -> bool:
    """Enforce channel read access for agent tools."""
    if channel.channel_type == ChannelType.PUBLIC:
        return True
    return _is_member_channel(channel, user_channel_ids, canonical_channel_ids)


def _safe_since_until(
    hours: int | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> tuple[datetime | None, datetime | None]:
    """Normalize relative tool time windows into explicit UTC datetimes."""
    resolved_until = until or (datetime.now(timezone.utc) if hours else None)
    resolved_since = since
    if hours and resolved_since is None:
        resolved_since = (resolved_until or datetime.now(timezone.utc)) - timedelta(
            hours=hours
        )
    return resolved_since, resolved_until


def create_tools(
    user_slack_id: str,
    user_channel_ids: list[str],
    workspace_id: uuid.UUID,
    canonical_user_id: uuid.UUID | None = None,
    canonical_channel_ids: list[uuid.UUID] | None = None,
) -> list:
    """
    Create agent tools with trusted user and workspace context baked in.

    Args:
        user_slack_id: Authenticated Slack user ID.
        user_channel_ids: Slack channel IDs the user belongs to.
        workspace_id: Internal workspace UUID. Required for all retrieval.
        canonical_user_id: Internal user UUID, when available.
        canonical_channel_ids: Internal channel UUIDs the user can access.

    Returns:
        LangChain tools scoped to this user and workspace.
    """

    @tool(args_schema=SearchKnowledgeArgs)
    async def search_knowledge(
        query: str,
        top_k: int = 5,
        hours: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> str:
        """Search workspace knowledge with ACL and optional source-time filters.

        Use this for topic-specific questions about past discussions or files.
        For broad recaps such as "what did we discuss last week", use
        summarize_activity instead because it scans the bounded message window.
        """

        async def _run() -> str:
            resolved_since, resolved_until = _safe_since_until(hours, since, until)
            results = await knowledge_service.search(
                query=query,
                workspace_id=workspace_id,
                user_channel_ids=user_channel_ids,
                user_slack_id=user_slack_id,
                user_channel_uuids=canonical_channel_ids,
                user_id=canonical_user_id,
                since=resolved_since,
                until=resolved_until,
                top_k=top_k,
            )

            if not results:
                return "No relevant information found in the Knowledge Fabric."

            formatted = []
            for index, result in enumerate(results, 1):
                channel = result.source_channel_name or result.source_channel_id
                timestamp = (
                    result.source_created_at.isoformat()
                    if result.source_created_at
                    else "unknown time"
                )
                author = (
                    result.source_author_display_name
                    or result.source_author_external_id
                    or "unknown author"
                )
                permalink = (
                    f"\nPermalink: {result.source_permalink}"
                    if result.source_permalink
                    else ""
                )
                formatted.append(
                    "[{index}] score={score:.2f} source={source} "
                    "channel={channel} time={timestamp} author={author}\n"
                    "<UNTRUSTED_SOURCE_CONTENT>\n{content}\n"
                    "</UNTRUSTED_SOURCE_CONTENT>{permalink}".format(
                        index=index,
                        score=result.score,
                        source=result.source_type,
                        channel=channel or "unknown",
                        timestamp=timestamp,
                        author=author,
                        content=result.content,
                        permalink=permalink,
                    )
                )

            return "\n\n---\n\n".join(formatted)

        return await _run_tool_with_timeout(_run(), "search_knowledge")

    @tool(args_schema=RecentMessagesArgs)
    async def get_recent_messages(
        channel_name: str = "",
        hours: int = 24,
        limit: int = 20,
    ) -> str:
        """Get recent messages from a specific accessible channel."""

        async def _run() -> str:
            normalized_name = channel_name.lstrip("#") if channel_name else ""
            async with AsyncSessionLocal() as session:
                since = datetime.now(timezone.utc) - timedelta(hours=hours)

                result = await session.execute(
                    select(Channel).where(
                        Channel.workspace_id == workspace_id,
                        Channel.name.ilike(f"%{normalized_name}%"),
                    )
                )
                channel = result.scalar_one_or_none()
                if not channel:
                    return f"Channel '{channel_name}' not found."

                if not _can_read_channel(
                    channel, user_channel_ids, canonical_channel_ids
                ):
                    return (
                        f"You don't have access to #{channel.name}. "
                        f"It's a {channel.channel_type.value} channel."
                    )

                msg_query = (
                    select(Message)
                    .where(
                        Message.workspace_id == workspace_id,
                        Message.channel_id == channel.id,
                        or_(
                            Message.sent_at >= since,
                            Message.slack_sent_at >= since,
                        ),
                    )
                    .order_by(Message.slack_sent_at.desc())
                    .limit(limit)
                )
                msg_result = await session.execute(msg_query)
                messages = msg_result.scalars().all()

                if not messages:
                    return f"No messages in #{channel.name} in the last {hours} hours."

                formatted = []
                for msg in reversed(messages):
                    ts = msg.sent_at or msg.slack_sent_at
                    time_str = (
                        ts.strftime("%Y-%m-%d %H:%M UTC") if ts else "unknown time"
                    )
                    thread = f" thread={msg.thread_ts}" if msg.thread_ts else ""
                    content = msg.content[:500] if msg.content else "[no content]"
                    formatted.append(f"[{time_str}]{thread} {content}")

                return (
                    f"Recent messages in #{channel.name} "
                    f"(last {hours}h, {len(messages)} messages):\n\n"
                    + "\n".join(formatted)
                )

        return await _run_tool_with_timeout(_run(), "get_recent_messages")

    @tool
    async def list_channels() -> str:
        """List readable non-archived channels in the workspace."""

        async def _run() -> str:
            async with AsyncSessionLocal() as session:
                membership_conditions = [
                    Channel.channel_type == ChannelType.PUBLIC,
                ]
                if user_channel_ids:
                    membership_conditions.extend(
                        [
                            Channel.slack_channel_id.in_(user_channel_ids),
                            Channel.external_channel_id.in_(user_channel_ids),
                        ]
                    )
                if canonical_channel_ids:
                    membership_conditions.append(Channel.id.in_(canonical_channel_ids))

                result = await session.execute(
                    select(Channel)
                    .where(
                        Channel.workspace_id == workspace_id,
                        Channel.is_archived.is_(False),
                        Channel.channel_type.notin_(
                            [ChannelType.DM, ChannelType.GROUP_DM]
                        ),
                        or_(*membership_conditions),
                    )
                    .order_by(Channel.name)
                    .limit(50)
                )
                channels = result.scalars().all()

                if not channels:
                    return "No channels found."

                formatted = []
                for channel in channels:
                    purpose = f" - {channel.purpose[:60]}..." if channel.purpose else ""
                    member_indicator = (
                        " [member]"
                        if _is_member_channel(
                            channel, user_channel_ids, canonical_channel_ids
                        )
                        else ""
                    )
                    formatted.append(
                        f"- #{channel.name} ({channel.channel_type.value}, "
                        f"{channel.member_count} members){member_indicator}{purpose}"
                    )

                return f"Channels ({len(channels)}):\n" + "\n".join(formatted)

        return await _run_tool_with_timeout(_run(), "list_channels")

    @tool(args_schema=ChannelActivityArgs)
    async def get_channel_activity_summary(
        channel_name: str = "",
        hours: int = 24,
    ) -> str:
        """Get lightweight activity counts for a specific accessible channel."""

        async def _run() -> str:
            normalized_name = channel_name.lstrip("#") if channel_name else ""
            async with AsyncSessionLocal() as session:
                since = datetime.now(timezone.utc) - timedelta(hours=hours)

                result = await session.execute(
                    select(Channel).where(
                        Channel.workspace_id == workspace_id,
                        Channel.name.ilike(f"%{normalized_name}%"),
                    )
                )
                channel = result.scalar_one_or_none()
                if not channel:
                    return f"Channel '{channel_name}' not found."

                if not _can_read_channel(
                    channel, user_channel_ids, canonical_channel_ids
                ):
                    return (
                        f"You don't have access to #{channel.name}. "
                        f"It's a {channel.channel_type.value} channel."
                    )

                count_query = select(func.count(Message.id)).where(
                    Message.workspace_id == workspace_id,
                    Message.channel_id == channel.id,
                    or_(Message.sent_at >= since, Message.slack_sent_at >= since),
                )
                msg_count = (await session.execute(count_query)).scalar() or 0

                thread_query = select(
                    func.count(func.distinct(Message.thread_ts))
                ).where(
                    Message.workspace_id == workspace_id,
                    Message.channel_id == channel.id,
                    or_(Message.sent_at >= since, Message.slack_sent_at >= since),
                    Message.thread_ts.isnot(None),
                )
                thread_count = (await session.execute(thread_query)).scalar() or 0

                return (
                    f"#{channel.name} activity (last {hours}h):\n"
                    f"- Messages: {msg_count}\n"
                    f"- Active threads: {thread_count}\n"
                    f"- Channel type: {channel.channel_type.value}\n"
                    f"- Members: {channel.member_count}"
                )

        return await _run_tool_with_timeout(_run(), "get_channel_activity_summary")

    @tool(args_schema=GenerateDigestArgs)
    async def generate_digest(
        channel_name: str = "",
        hours: int = 24,
        personalized: bool = False,
    ) -> str:
        """Generate an LLM digest for a channel or accessible channel set."""

        async def _run() -> str:
            from app.services.digest_service import digest_service

            normalized_name = channel_name.lstrip("#") if channel_name else ""

            if personalized and not normalized_name:
                result = await digest_service.generate_personalized_digest(
                    user_slack_id=user_slack_id,
                    canonical_user_id=canonical_user_id,
                    workspace_id=workspace_id,
                    hours=hours,
                )
                if result:
                    return f"*Your Personalized Digest*\n\n{result}"
                return (
                    "No significant activity across your channels "
                    f"in the last {hours} hours."
                )

            if normalized_name:
                async with AsyncSessionLocal() as session:
                    workspace_exists = await session.get(Workspace, workspace_id)
                    if not workspace_exists:
                        return "No active workspace found."

                    result = await session.execute(
                        select(Channel).where(
                            Channel.workspace_id == workspace_id,
                            Channel.name.ilike(f"%{normalized_name}%"),
                        )
                    )
                    channel = result.scalar_one_or_none()
                    if not channel:
                        return f"Channel '{channel_name}' not found."

                    if not _can_read_channel(
                        channel, user_channel_ids, canonical_channel_ids
                    ):
                        return (
                            f"You don't have access to #{channel.name}. "
                            f"It's a {channel.channel_type.value} channel."
                        )

                    digest = await digest_service.generate_channel_digest(
                        channel_id=channel.id,
                        workspace_id=workspace_id,
                        hours=hours,
                    )

                if digest:
                    return f"Digest for #{channel.name}:\n\n{digest.content}"
                return (
                    f"No significant activity in #{channel.name} "
                    f"in the last {hours} hours."
                )

            digests = await digest_service.generate_daily_digest(
                workspace_id=workspace_id,
                hours=hours,
            )
            if digests:
                return "Daily Digest:\n\n" + "\n\n---\n\n".join(
                    digest.content for digest in digests
                )
            return f"No significant activity across channels in the last {hours} hours."

        return await _run_tool_with_timeout(_run(), "generate_digest")

    @tool(args_schema=SummarizeActivityArgs)
    async def summarize_activity(
        channel_name: str | None = None,
        hours: int = 24,
        topic: str | None = None,
        personalized: bool = True,
    ) -> str:
        """Summarize recent activity from direct message queries, not vector top-k.

        Use this for broad time-window summaries and recap requests such as
        "what did we discuss yesterday", "summarize my channels", or
        "give me a summary for the past week".
        """

        async def _run() -> str:
            from app.services.digest_service import digest_service

            result = await digest_service.summarize_activity(
                workspace_id=workspace_id,
                user_slack_id=user_slack_id,
                user_channel_ids=user_channel_ids,
                canonical_user_id=canonical_user_id,
                canonical_channel_ids=canonical_channel_ids,
                channel_name=channel_name,
                hours=hours,
                topic=topic,
                personalized=personalized,
            )
            if result:
                return result
            return "I do not have enough recent evidence in that time window."

        return await _run_tool_with_timeout(_run(), "summarize_activity")

    return [
        search_knowledge,
        get_recent_messages,
        list_channels,
        get_channel_activity_summary,
        generate_digest,
        summarize_activity,
    ]
