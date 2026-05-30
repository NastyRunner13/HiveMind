"""
Agent Graph — LangGraph workflow for HiveMind's conversational AI.

Implements a ReAct-style agent that can:
1. Understand user intent from natural language
2. Search the Knowledge Fabric for relevant context
3. Use tools to gather information
4. Generate intelligent, context-aware responses

The graph follows the interaction model from the v3 concept:
  User Message → Intent Classification → Knowledge Retrieval → Response Generation

SECURITY: The graph is built per-request with user-scoped tools.
Tools close over server-derived ACL context — the LLM never controls
which channels or users the tools query.
"""

import logging
import uuid
from typing import Annotated, Any

from langchain_core.messages import AIMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict

from app.agent.llm import get_llm
from app.agent.prompts import SYSTEM_PROMPT

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════
# STATE DEFINITION
# ═════════════════════════════════════════════════════════════════


class AgentState(TypedDict):
    """State that flows through the agent graph."""

    # Conversation messages (accumulated via add_messages reducer)
    messages: Annotated[list, add_messages]

    # User context for ACL filtering
    user_slack_id: str
    user_channel_ids: list[str]
    workspace_id: uuid.UUID

    # Canonical identity (set when caller is OIDC-authenticated)
    canonical_user_id: uuid.UUID | None
    canonical_channel_ids: list[uuid.UUID] | None


# ═════════════════════════════════════════════════════════════════
# GRAPH NODES
# ═════════════════════════════════════════════════════════════════


def _create_agent_node(tools: list):
    """
    Create an agent node with user-scoped tools.

    Args:
        tools: List of LangChain tools scoped to the user's permissions.
    """

    async def agent_node(state: AgentState) -> dict[str, Any]:
        """
        The main agent node — calls the LLM with tools.

        The LLM decides whether to:
        - Call a tool (search, get messages, etc.)
        - Respond directly to the user
        """
        llm = get_llm()
        llm_with_tools = llm.bind_tools(tools)

        # Ensure system prompt is at the start
        messages = state["messages"]
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(messages)

        response = await llm_with_tools.ainvoke(messages)
        return {"messages": [response]}

    return agent_node


def should_continue(state: AgentState) -> str:
    """
    Edge function: decide whether to call tools or finish.

    If the last message has tool calls, route to the tool node.
    Otherwise, the agent is done — return the response.
    """
    last_message = state["messages"][-1]

    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"

    return END


# ═════════════════════════════════════════════════════════════════
# GRAPH CONSTRUCTION
# ═════════════════════════════════════════════════════════════════


def build_agent_graph(
    user_slack_id: str,
    user_channel_ids: list[str],
    workspace_id: uuid.UUID,
    canonical_user_id: uuid.UUID | None = None,
    canonical_channel_ids: list[uuid.UUID] | None = None,
) -> StateGraph:
    """
    Build a user-scoped HiveMind agent graph.

    The graph is built per-request with tools that close over the user's
    trusted ACL context. This ensures the LLM cannot control which
    channels or users the tools operate on.

    Graph structure:
      agent → (tool calls?) → tools → agent → ... → END

    This is a ReAct-style loop: the agent thinks, optionally acts
    (calls tools), observes the results, and responds.

    Args:
        user_slack_id: The authenticated user's Slack ID.
        user_channel_ids: Slack channel IDs the user has access to.
        workspace_id: Internal workspace UUID used to scope every retrieval.
        canonical_user_id: Internal user UUID (OIDC path).
        canonical_channel_ids: Internal channel UUIDs the user has access to.

    Returns:
        Compiled LangGraph graph ready for invocation.
    """
    from app.agent.tools import create_tools

    # Create user-scoped tools
    tools = create_tools(
        user_slack_id=user_slack_id,
        user_channel_ids=user_channel_ids,
        workspace_id=workspace_id,
        canonical_user_id=canonical_user_id,
        canonical_channel_ids=canonical_channel_ids,
    )

    # Create the tool node from scoped tools
    tool_node = ToolNode(tools)

    # Create the agent node with scoped tools
    agent_node = _create_agent_node(tools)

    # Build the graph
    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)

    # Set entry point
    graph.set_entry_point("agent")

    # Add conditional edges
    graph.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            END: END,
        },
    )

    # Tools always return to the agent
    graph.add_edge("tools", "agent")

    return graph.compile()
