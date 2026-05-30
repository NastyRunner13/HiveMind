"""
Agent Service tests — validates the orchestration layer.

Tests cover:
- Message processing flow
- Response extraction
- Tool call counting
- Error handling
- LLM not configured behavior
- Mention cleaning
"""

import uuid
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

# ═════════════════════════════════════════════════════════════════
# AGENT SERVICE
# ═════════════════════════════════════════════════════════════════


class TestAgentService:
    """Tests for the AgentService orchestrator."""

    async def test_process_message_when_llm_not_configured(self):
        """Returns a helpful message when LLM is not configured."""
        # Patch the module-level settings in agent_service
        with patch("app.services.agent_service.settings") as mock_settings:
            mock_settings.llm_configured = False

            from app.services.agent_service import AgentService

            service = AgentService()
            response = await service.process_message(
                user_slack_id="U123",
                message="Hello HiveMind",
            )

            assert "not fully set up" in response.content
            assert response.error == "LLM not configured"

    async def test_process_message_success(self):
        """Successfully processes a message through the agent."""
        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(
            return_value={
                "messages": [
                    SystemMessage(content="system"),
                    HumanMessage(content="test"),
                    AIMessage(content="Here's your answer!"),
                ],
            }
        )

        with (
            patch("app.services.agent_service.settings") as mock_settings,
            patch("app.agent.graph.build_agent_graph", return_value=mock_graph),
            patch("app.services.agent_service.event_bus") as mock_bus,
        ):
            mock_settings.llm_configured = True
            mock_settings.llm_provider = "openrouter"
            mock_settings.llm_model = "test-model"
            mock_bus.publish = AsyncMock()

            from app.services.agent_service import AgentService

            service = AgentService()
            response = await service.process_message(
                user_slack_id="U123",
                message="What happened today?",
                channel_id="C456",
                workspace_id=uuid.uuid4(),
            )

            assert response.content == "Here's your answer!"
            assert response.error is None
            assert mock_graph.ainvoke.call_args.kwargs["config"] == {
                "recursion_limit": 8
            }

    async def test_process_message_times_out(self):
        """Returns a bounded error when the graph exceeds runtime limits."""
        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(side_effect=TimeoutError)

        with (
            patch("app.services.agent_service.settings") as mock_settings,
            patch("app.agent.graph.build_agent_graph", return_value=mock_graph),
            patch("app.services.agent_service.event_bus") as mock_bus,
        ):
            mock_settings.llm_configured = True
            mock_settings.llm_provider = "openrouter"
            mock_settings.llm_model = "test-model"
            mock_settings.agent_max_iterations = 3
            mock_settings.agent_timeout_seconds = 1
            mock_bus.publish = AsyncMock()

            from app.services.agent_service import AgentService

            service = AgentService()
            response = await service.process_message(
                user_slack_id="U123",
                message="What happened today?",
                channel_id="C456",
                workspace_id=uuid.uuid4(),
            )

            assert "runtime limit" in response.content
            assert response.error == "Agent timeout"

    async def test_process_message_handles_exception(self):
        """Returns error message when agent raises an exception."""
        with (
            patch("app.services.agent_service.settings") as mock_settings,
            patch("app.agent.graph.build_agent_graph", side_effect=Exception("boom")),
            patch("app.services.agent_service.event_bus") as mock_bus,
        ):
            mock_settings.llm_configured = True
            mock_bus.publish = AsyncMock()

            from app.services.agent_service import AgentService

            service = AgentService()
            response = await service.process_message(
                user_slack_id="U123",
                message="Break things",
                workspace_id=uuid.uuid4(),
            )

            assert "Sorry" in response.content
            assert response.error is not None


# ═════════════════════════════════════════════════════════════════
# RESPONSE EXTRACTION
# ═════════════════════════════════════════════════════════════════


class TestResponseExtraction:
    """Tests for response extraction from agent results."""

    def test_extract_response_from_ai_message(self):
        """Extracts content from the last AI message without tool calls."""
        from app.services.agent_service import AgentService

        service = AgentService()

        result = {
            "messages": [
                HumanMessage(content="test"),
                AIMessage(
                    content="first response",
                    tool_calls=[{"name": "test", "args": {}, "id": "1"}],
                ),
                AIMessage(content="final answer"),
            ]
        }

        response = service._extract_response(result)
        assert response == "final answer"

    def test_extract_response_fallback(self):
        """Falls back to last message when no clean AI message."""
        from app.services.agent_service import AgentService

        service = AgentService()

        result = {"messages": [HumanMessage(content="just a question")]}
        response = service._extract_response(result)
        assert response == "just a question"

    def test_extract_response_empty_messages(self):
        """Returns fallback when messages list is empty."""
        from app.services.agent_service import AgentService

        service = AgentService()

        result = {"messages": []}
        response = service._extract_response(result)
        assert "couldn't generate" in response


# ═════════════════════════════════════════════════════════════════
# TOOL CALL COUNTING
# ═════════════════════════════════════════════════════════════════


class TestToolCallCounting:
    """Tests for tool call counting."""

    def test_count_tool_calls(self):
        """Counts tool calls across all AI messages."""
        from app.services.agent_service import AgentService

        service = AgentService()

        result = {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "search", "args": {}, "id": "1"},
                        {"name": "list", "args": {}, "id": "2"},
                    ],
                ),
                AIMessage(content="result"),
            ]
        }

        count = service._count_tool_calls(result)
        assert count == 2

    def test_count_tool_calls_no_calls(self):
        """Returns 0 when no tool calls were made."""
        from app.services.agent_service import AgentService

        service = AgentService()

        result = {"messages": [AIMessage(content="direct answer")]}
        assert service._count_tool_calls(result) == 0


# ═════════════════════════════════════════════════════════════════
# MENTION CLEANING
# ═════════════════════════════════════════════════════════════════


class TestMentionCleaning:
    """Tests for Slack mention cleaning."""

    def test_clean_mention(self):
        """Removes Slack user mentions from text."""
        from app.services.agent_service import AgentService

        service = AgentService()

        assert service._clean_mention("<@U123ABC> hello") == "hello"
        assert service._clean_mention("<@U999> what's up?") == "what's up?"

    def test_clean_mention_no_mention(self):
        """Returns original text when no mention present."""
        from app.services.agent_service import AgentService

        service = AgentService()

        assert service._clean_mention("just a message") == "just a message"

    def test_clean_mention_empty(self):
        """Returns original text when only mention with no other content."""
        from app.services.agent_service import AgentService

        service = AgentService()

        # Empty after cleaning → return original
        assert service._clean_mention("<@U123>") == "<@U123>"
