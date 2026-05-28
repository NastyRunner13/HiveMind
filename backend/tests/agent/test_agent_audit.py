"""
Tests for Agent Tool Audit Logging.

Verifies that:
- Individual tool call details are extracted from LangGraph message history
- AGENT_TOOL_CALL events are published per tool invocation
- No audit event is published when no tools are called
- Sensitive arguments are truncated in audit logs
"""

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

# Check if asyncpg is available (needed by app.database → agent_service)
try:
    import asyncpg

    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False

skip_without_asyncpg = pytest.mark.skipif(
    not HAS_ASYNCPG,
    reason="asyncpg not installed — agent_service imports app.database",
)


@skip_without_asyncpg
class TestExtractToolCallDetails:
    """Tests for _extract_tool_call_details()."""

    def test_extracts_single_tool_call(self):
        """Should extract one tool call from a single AIMessage."""
        from app.services.agent_service import AgentService

        service = AgentService()
        result = {
            "messages": [
                SystemMessage(content="system"),
                HumanMessage(content="search for auth"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "search_knowledge",
                            "args": {"query": "auth migration"},
                            "id": "tc_1",
                        }
                    ],
                ),
            ]
        }

        details = service._extract_tool_call_details(result)
        assert len(details) == 1
        assert details[0].tool_name == "search_knowledge"
        assert details[0].tool_args == {"query": "auth migration"}

    def test_extracts_multiple_tool_calls(self):
        """Should extract tool calls across multiple AIMessages."""
        from app.services.agent_service import AgentService

        service = AgentService()
        result = {
            "messages": [
                HumanMessage(content="what's happening?"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "search_knowledge",
                            "args": {"query": "recent updates"},
                            "id": "tc_1",
                        }
                    ],
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "get_recent_messages",
                            "args": {"channel_name": "backend-team", "hours": 24},
                            "id": "tc_2",
                        },
                        {
                            "name": "list_channels",
                            "args": {},
                            "id": "tc_3",
                        },
                    ],
                ),
            ]
        }

        details = service._extract_tool_call_details(result)
        assert len(details) == 3
        assert details[0].tool_name == "search_knowledge"
        assert details[1].tool_name == "get_recent_messages"
        assert details[2].tool_name == "list_channels"

    def test_returns_empty_when_no_tool_calls(self):
        """Should return empty list when agent didn't use any tools."""
        from app.services.agent_service import AgentService

        service = AgentService()
        result = {
            "messages": [
                HumanMessage(content="hello"),
                AIMessage(content="Hi there!"),
            ]
        }

        details = service._extract_tool_call_details(result)
        assert details == []

    def test_handles_empty_messages(self):
        """Should handle empty message list gracefully."""
        from app.services.agent_service import AgentService

        service = AgentService()
        result = {"messages": []}

        details = service._extract_tool_call_details(result)
        assert details == []


@skip_without_asyncpg
class TestSanitizeArgs:
    """Tests for _sanitize_args()."""

    def test_truncates_long_string_values(self):
        """Long string values should be truncated."""
        from app.services.agent_service import AgentService

        service = AgentService()
        long_text = "x" * 500
        args = {"query": long_text}

        sanitized = service._sanitize_args(args, max_value_length=200)
        assert len(sanitized["query"]) < 500
        assert sanitized["query"].endswith("...[truncated]")

    def test_preserves_short_string_values(self):
        """Short string values should be preserved unchanged."""
        from app.services.agent_service import AgentService

        service = AgentService()
        args = {"query": "auth migration", "hours": 24}

        sanitized = service._sanitize_args(args)
        assert sanitized["query"] == "auth migration"
        assert sanitized["hours"] == 24

    def test_handles_non_serializable_values(self):
        """Non-JSON-serializable values should be converted to strings."""
        from app.services.agent_service import AgentService

        service = AgentService()
        args = {"obj": object()}

        sanitized = service._sanitize_args(args)
        assert isinstance(sanitized["obj"], str)


@skip_without_asyncpg
class TestAuditEventPublishing:
    """Tests that AGENT_TOOL_CALL events are published correctly."""

    @pytest.mark.asyncio
    async def test_publishes_tool_call_events(self):
        """Should publish an AGENT_TOOL_CALL event for each tool invocation."""
        from app.services.agent_service import AgentService

        service = AgentService()

        # Mock the agent graph to return a result with tool calls
        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(
            return_value={
                "messages": [
                    SystemMessage(content="system"),
                    HumanMessage(content="search for auth"),
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "search_knowledge",
                                "args": {"query": "auth"},
                                "id": "tc_1",
                            }
                        ],
                    ),
                    AIMessage(content="Here's what I found about auth..."),
                ]
            }
        )

        with (
            patch("app.services.agent_service.settings") as mock_settings,
            patch("app.services.agent_service.event_bus") as mock_bus,
            patch("app.agent.graph.build_agent_graph", return_value=mock_graph),
        ):
            mock_settings.llm_configured = True
            mock_settings.llm_provider = "openai"
            mock_settings.llm_model = "gpt-4o-mini"
            mock_settings.is_development = False
            mock_bus.publish = AsyncMock()

            await service.process_message(
                user_slack_id="U_TEST",
                message="search for auth",
                channel_id="C_TEST",
                user_channel_ids=["C_TEST"],
            )

            # Verify AGENT_TOOL_CALL event was published
            tool_call_events = [
                call
                for call in mock_bus.publish.call_args_list
                if call.args[0].value == "agent.tool_call"
            ]
            assert len(tool_call_events) == 1
            event_data = tool_call_events[0].args[1]
            assert event_data["user_slack_id"] == "U_TEST"
            assert event_data["tool_name"] == "search_knowledge"
            assert event_data["tool_args"] == {"query": "auth"}

    @pytest.mark.asyncio
    async def test_no_tool_call_events_when_no_tools_used(self):
        """Should NOT publish AGENT_TOOL_CALL events when no tools were used."""
        from app.services.agent_service import AgentService

        service = AgentService()

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(
            return_value={
                "messages": [
                    SystemMessage(content="system"),
                    HumanMessage(content="hello"),
                    AIMessage(content="Hi there!"),
                ]
            }
        )

        with (
            patch("app.services.agent_service.settings") as mock_settings,
            patch("app.services.agent_service.event_bus") as mock_bus,
            patch("app.agent.graph.build_agent_graph", return_value=mock_graph),
        ):
            mock_settings.llm_configured = True
            mock_settings.llm_provider = "openai"
            mock_settings.llm_model = "gpt-4o-mini"
            mock_settings.is_development = False
            mock_bus.publish = AsyncMock()

            await service.process_message(
                user_slack_id="U_TEST",
                message="hello",
                channel_id="C_TEST",
                user_channel_ids=["C_TEST"],
            )

            # Should NOT have any AGENT_TOOL_CALL events
            tool_call_events = [
                call
                for call in mock_bus.publish.call_args_list
                if call.args[0].value == "agent.tool_call"
            ]
            assert len(tool_call_events) == 0

    @pytest.mark.asyncio
    async def test_tools_used_list_in_response_event(self):
        """AGENT_RESPONSE event should include list of tools used."""
        from app.services.agent_service import AgentService

        service = AgentService()

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(
            return_value={
                "messages": [
                    SystemMessage(content="system"),
                    HumanMessage(content="check backend"),
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "search_knowledge",
                                "args": {"query": "backend"},
                                "id": "tc_1",
                            },
                            {
                                "name": "list_channels",
                                "args": {},
                                "id": "tc_2",
                            },
                        ],
                    ),
                    AIMessage(content="Here's what I found..."),
                ]
            }
        )

        with (
            patch("app.services.agent_service.settings") as mock_settings,
            patch("app.services.agent_service.event_bus") as mock_bus,
            patch("app.agent.graph.build_agent_graph", return_value=mock_graph),
        ):
            mock_settings.llm_configured = True
            mock_settings.llm_provider = "openai"
            mock_settings.llm_model = "gpt-4o-mini"
            mock_settings.is_development = False
            mock_bus.publish = AsyncMock()

            await service.process_message(
                user_slack_id="U_TEST",
                message="check backend",
                channel_id="C_TEST",
                user_channel_ids=["C_TEST"],
            )

            # Find the AGENT_RESPONSE event
            response_events = [
                call
                for call in mock_bus.publish.call_args_list
                if call.args[0].value == "agent.response"
            ]
            assert len(response_events) == 1
            event_data = response_events[0].args[1]
            assert "tools_used" in event_data
            assert event_data["tools_used"] == [
                "search_knowledge",
                "list_channels",
            ]
