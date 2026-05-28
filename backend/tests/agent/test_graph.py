"""
Agent Graph tests — validates the LangGraph workflow construction.

Tests cover:
- Graph building and compilation
- State definition
- Node routing (should_continue logic)
- Graph singleton behavior
"""

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

# ═════════════════════════════════════════════════════════════════
# STATE DEFINITION
# ═════════════════════════════════════════════════════════════════


class TestAgentState:
    """Tests for the AgentState TypedDict."""

    def test_state_has_required_fields(self):
        """AgentState has all required fields."""
        from app.agent.graph import AgentState

        # TypedDict annotations should have these keys
        annotations = AgentState.__annotations__
        assert "messages" in annotations
        assert "user_slack_id" in annotations
        assert "user_channel_ids" in annotations
        assert "canonical_user_id" in annotations
        assert "canonical_channel_ids" in annotations


# ═════════════════════════════════════════════════════════════════
# ROUTING LOGIC
# ═════════════════════════════════════════════════════════════════


class TestShouldContinue:
    """Tests for the should_continue edge function."""

    def test_continues_when_tool_calls_present(self):
        """Routes to tools when the last message has tool calls."""
        from app.agent.graph import should_continue

        # Create an AI message with tool calls
        ai_msg = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "search_knowledge",
                    "args": {"query": "test"},
                    "id": "call_123",
                }
            ],
        )
        state = {
            "messages": [HumanMessage(content="test"), ai_msg],
            "user_slack_id": "U123",
            "user_channel_ids": [],
            "canonical_user_id": None,
            "canonical_channel_ids": None,
        }

        result = should_continue(state)
        assert result == "tools"

    def test_ends_when_no_tool_calls(self):
        """Routes to END when the last message has no tool calls."""
        from langgraph.graph import END

        from app.agent.graph import should_continue

        ai_msg = AIMessage(content="Here's your answer!")
        state = {
            "messages": [HumanMessage(content="test"), ai_msg],
            "user_slack_id": "U123",
            "user_channel_ids": [],
            "canonical_user_id": None,
            "canonical_channel_ids": None,
        }

        result = should_continue(state)
        assert result == END

    def test_ends_when_last_is_human_message(self):
        """Routes to END when the last message is not an AI message."""
        from langgraph.graph import END

        from app.agent.graph import should_continue

        state = {
            "messages": [HumanMessage(content="test")],
            "user_slack_id": "U123",
            "user_channel_ids": [],
            "canonical_user_id": None,
            "canonical_channel_ids": None,
        }

        result = should_continue(state)
        assert result == END


# ═════════════════════════════════════════════════════════════════
# GRAPH CONSTRUCTION
# ═════════════════════════════════════════════════════════════════


class TestGraphConstruction:
    """Tests for agent graph building."""

    def test_build_agent_graph_compiles(self):
        """build_agent_graph() returns a compiled graph without error."""
        with patch("app.agent.graph.get_llm") as mock_get_llm:
            mock_llm = MagicMock()
            mock_llm.bind_tools = MagicMock(return_value=mock_llm)
            mock_get_llm.return_value = mock_llm

            from app.agent.graph import build_agent_graph

            graph = build_agent_graph(
                user_slack_id="U_TEST",
                user_channel_ids=["C_CHAN1"],
            )
            assert graph is not None

    def test_build_agent_graph_with_canonical_ids(self):
        """build_agent_graph() accepts canonical UUID parameters."""
        import uuid as uuid_mod

        with patch("app.agent.graph.get_llm") as mock_get_llm:
            mock_llm = MagicMock()
            mock_llm.bind_tools = MagicMock(return_value=mock_llm)
            mock_get_llm.return_value = mock_llm

            from app.agent.graph import build_agent_graph

            graph = build_agent_graph(
                user_slack_id="U_TEST",
                user_channel_ids=["C_CHAN1"],
                canonical_user_id=uuid_mod.uuid4(),
                canonical_channel_ids=[uuid_mod.uuid4()],
            )
            assert graph is not None

    def test_build_agent_graph_per_request(self):
        """build_agent_graph() returns unique instances per call (not singleton)."""
        with patch("app.agent.graph.get_llm") as mock_get_llm:
            mock_llm = MagicMock()
            mock_llm.bind_tools = MagicMock(return_value=mock_llm)
            mock_get_llm.return_value = mock_llm

            from app.agent.graph import build_agent_graph

            graph1 = build_agent_graph(
                user_slack_id="U_USER1",
                user_channel_ids=["C_CHAN1"],
            )
            graph2 = build_agent_graph(
                user_slack_id="U_USER2",
                user_channel_ids=["C_CHAN2"],
            )
            # Per-request graphs are NOT the same instance
            assert graph1 is not graph2
