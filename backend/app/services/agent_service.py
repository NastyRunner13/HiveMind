"""
Agent Service — orchestrates HiveMind's AI agent for user interactions.

This service bridges Slack events with the LangGraph agent. It:
1. Prepares user context (channel memberships, permissions)
2. Invokes the agent graph with the user's message
3. Extracts and returns the agent's response
4. Logs all interactions to the Event Bus for Phase 2 workflow tracing
5. Publishes per-tool audit events for individual tool invocations

All agent interactions are logged but never stored with sensitive content.
"""

import json
import logging
import uuid
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agent.prompts import SYSTEM_PROMPT
from app.config import get_settings
from app.events.bus import EventType, event_bus

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class ToolCallDetail:
    """Details of a single tool invocation for audit logging."""

    tool_name: str
    tool_args: dict
    timestamp: str | None = None


@dataclass
class AgentResponse:
    """Response from the AI agent."""

    content: str
    tool_calls_made: int = 0
    tool_call_details: list[ToolCallDetail] = field(default_factory=list)
    model_used: str = ""
    error: str | None = None


class AgentService:
    """
    Orchestrates the AI agent for user interactions.

    Usage:
        service = AgentService()
        response = await service.process_message(
            user_slack_id="U123",
            message="What was discussed in #backend-team today?",
            channel_id="C456",
        )
        print(response.content)
    """

    async def process_message(
        self,
        user_slack_id: str,
        message: str,
        channel_id: str | None = None,
        thread_ts: str | None = None,
        user_channel_ids: list[str] | None = None,
        canonical_user_id: uuid.UUID | None = None,
        workspace_id: uuid.UUID | None = None,
    ) -> AgentResponse:
        """
        Process a user message through the AI agent.

        Args:
            user_slack_id: The Slack user ID of the requester.
            message: The user's message text.
            channel_id: The channel where the message was sent.
            thread_ts: Thread timestamp for threaded replies.
            user_channel_ids: List of channel IDs the user is a member of.
            canonical_user_id: Internal user UUID, when mapped.
            workspace_id: Internal workspace UUID, when mapped.

        Returns:
            AgentResponse with the agent's reply.
        """
        if not settings.llm_configured:
            return AgentResponse(
                content=(
                    "🐝 I'm not fully set up yet! An LLM provider needs to be "
                    "configured. Ask your admin to set `LLM_API_KEY` in the "
                    "environment variables."
                ),
                error="LLM not configured",
            )

        # Log the incoming query
        await event_bus.publish(
            EventType.AGENT_QUERY,
            {
                "schema_version": 1,
                "platform": "slack",
                "requesting_user_id": (
                    str(canonical_user_id) if canonical_user_id else None
                ),
                "workspace_id": str(workspace_id) if workspace_id else None,
                "user_slack_id": user_slack_id,
                "channel_id": channel_id,
                "message_length": len(message),
                "thread_ts": thread_ts,
                "external_metadata": {
                    "user_id": user_slack_id,
                    "channel_id": channel_id,
                    "thread_ts": thread_ts,
                },
            },
        )

        try:
            # Build a per-request graph with user-scoped tools
            # The graph creates tools that close over trusted ACL context
            from app.agent.graph import build_agent_graph

            # Resolve canonical channel UUIDs when the caller is
            # authenticated via OIDC (canonical_user_id is set).
            canonical_channel_ids: list[uuid.UUID] | None = None
            if canonical_user_id and workspace_id:
                try:
                    from sqlalchemy import or_, select

                    from app.database import AsyncSessionLocal
                    from app.models.membership import ChannelMembership

                    async with AsyncSessionLocal() as session:
                        conditions = [
                            ChannelMembership.canonical_user_id == canonical_user_id,
                        ]
                        result = await session.execute(
                            select(ChannelMembership.channel_id).where(
                                ChannelMembership.workspace_id == workspace_id,
                                ChannelMembership.is_active.is_(True),
                                or_(*conditions),
                            )
                        )
                        canonical_channel_ids = [row[0] for row in result.all()]
                except Exception as e:
                    logger.warning("Failed to resolve canonical channel IDs: %s", e)

            graph = build_agent_graph(
                user_slack_id=user_slack_id,
                user_channel_ids=user_channel_ids or [],
                canonical_user_id=canonical_user_id,
                canonical_channel_ids=canonical_channel_ids,
            )

            # Clean the message (remove bot mention)
            clean_message = self._clean_mention(message)

            # Prepare initial state
            initial_state = {
                "messages": [
                    SystemMessage(content=SYSTEM_PROMPT),
                    HumanMessage(content=clean_message),
                ],
                "user_slack_id": user_slack_id,
                "user_channel_ids": user_channel_ids or [],
                "canonical_user_id": canonical_user_id,
                "canonical_channel_ids": canonical_channel_ids,
            }

            # Invoke the agent graph
            result = await graph.ainvoke(initial_state)

            # Extract the final response
            response_content = self._extract_response(result)
            tool_calls = self._count_tool_calls(result)
            tool_call_details = self._extract_tool_call_details(result)

            # Publish per-tool audit events
            for detail in tool_call_details:
                await event_bus.publish(
                    EventType.AGENT_TOOL_CALL,
                    {
                        "schema_version": 1,
                        "platform": "slack",
                        "requesting_user_id": (
                            str(canonical_user_id) if canonical_user_id else None
                        ),
                        "workspace_id": str(workspace_id) if workspace_id else None,
                        "user_slack_id": user_slack_id,
                        "tool_name": detail.tool_name,
                        "tool_args": self._sanitize_args(detail.tool_args),
                        "channel_id": channel_id,
                        "model": f"{settings.llm_provider}/{settings.llm_model}",
                        "external_metadata": {
                            "user_id": user_slack_id,
                            "channel_id": channel_id,
                        },
                    },
                )

            # Log the aggregate response
            await event_bus.publish(
                EventType.AGENT_RESPONSE,
                {
                    "schema_version": 1,
                    "platform": "slack",
                    "requesting_user_id": (
                        str(canonical_user_id) if canonical_user_id else None
                    ),
                    "workspace_id": str(workspace_id) if workspace_id else None,
                    "user_slack_id": user_slack_id,
                    "response_length": len(response_content),
                    "tool_calls_made": tool_calls,
                    "tools_used": [d.tool_name for d in tool_call_details],
                    "model": f"{settings.llm_provider}/{settings.llm_model}",
                    "external_metadata": {"user_id": user_slack_id},
                },
            )

            return AgentResponse(
                content=response_content,
                tool_calls_made=tool_calls,
                tool_call_details=tool_call_details,
                model_used=f"{settings.llm_provider}/{settings.llm_model}",
            )

        except Exception as e:
            logger.error(f"Agent error for user {user_slack_id}: {e}", exc_info=True)

            error_msg = (
                "🐝 Sorry, I ran into an issue processing your request. "
                "Please try again in a moment."
            )

            # Provide more detail in development
            if settings.is_development:
                error_msg += f"\n\n_Debug: {type(e).__name__}: {e}_"

            return AgentResponse(
                content=error_msg,
                error=str(e),
            )

    def _clean_mention(self, message: str) -> str:
        """Remove the @HiveMind mention from the message text."""
        import re

        # Slack formats mentions as <@U123ABC>
        cleaned = re.sub(r"<@[A-Z0-9]+>", "", message).strip()
        return cleaned or message

    def _extract_response(self, result: dict) -> str:
        """Extract the final text response from the agent graph result."""
        messages = result.get("messages", [])

        # Find the last AI message (the final response)
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
                return msg.content

        # Fallback: return the last message content
        if messages:
            last = messages[-1]
            if hasattr(last, "content") and last.content:
                return last.content

        return "🐝 I processed your request but couldn't generate a response. Please try rephrasing."

    def _count_tool_calls(self, result: dict) -> int:
        """Count how many tool calls were made during the agent run."""
        count = 0
        for msg in result.get("messages", []):
            if isinstance(msg, AIMessage) and msg.tool_calls:
                count += len(msg.tool_calls)
        return count

    def _extract_tool_call_details(self, result: dict) -> list[ToolCallDetail]:
        """
        Extract individual tool call details from the agent graph result.

        Walks the message history and extracts each tool invocation's
        name and arguments from AIMessage.tool_calls. This enables
        per-tool audit logging with full traceability.

        Args:
            result: The LangGraph agent result containing message history.

        Returns:
            List of ToolCallDetail objects, one per tool invocation.
        """
        details = []
        for msg in result.get("messages", []):
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    details.append(
                        ToolCallDetail(
                            tool_name=tc.get("name", "unknown"),
                            tool_args=tc.get("args", {}),
                        )
                    )
        return details

    def _sanitize_args(self, args: dict, max_value_length: int = 200) -> dict:
        """
        Sanitize tool arguments for audit logging.

        Truncates large string values to prevent bloated audit events
        while preserving enough context for debugging.

        Args:
            args: The raw tool arguments dictionary.
            max_value_length: Maximum character length for string values.

        Returns:
            Sanitized copy of the arguments.
        """
        sanitized = {}
        for key, value in args.items():
            if isinstance(value, str) and len(value) > max_value_length:
                sanitized[key] = value[:max_value_length] + "...[truncated]"
            else:
                # Ensure the value is JSON-serializable
                try:
                    json.dumps(value)
                    sanitized[key] = value
                except (TypeError, ValueError):
                    sanitized[key] = str(value)[:max_value_length]
        return sanitized


# ── Module-level singleton ──────────────────────────────────────
agent_service = AgentService()
