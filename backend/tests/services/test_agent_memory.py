"""
Agent Conversation Memory tests — validates loading, saving, truncation, and isolation.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.models.identity import Platform

# Check if asyncpg is available (same as other service tests)
try:
    import asyncpg  # noqa: F401

    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False

skip_without_asyncpg = pytest.mark.skipif(
    not HAS_ASYNCPG,
    reason="asyncpg not installed — agent memory tests require database components",
)


@skip_without_asyncpg
class TestAgentConversationMemory:
    """Tests for the agent's database-backed conversation history (Memory Pillar)."""

    @pytest.mark.asyncio
    async def test_process_message_without_thread_ts_does_not_use_memory(self):
        """When thread_ts is missing, memory should neither be loaded nor saved."""
        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(
            return_value={
                "messages": [
                    SystemMessage(content="system"),
                    HumanMessage(content="Hello"),
                    AIMessage(content="Hi there!"),
                ],
            }
        )

        with (
            patch("app.services.agent_service.settings") as mock_settings,
            patch("app.agent.graph.build_agent_graph", return_value=mock_graph),
            patch("app.services.agent_service.event_bus") as mock_bus,
            patch("app.services.membership_service.membership_service") as mock_ms,
            patch("app.database.AsyncSessionLocal") as mock_session_local,
        ):
            mock_settings.llm_configured = True
            mock_settings.llm_provider = "openrouter"
            mock_settings.llm_model = "test-model"
            mock_bus.publish = AsyncMock()
            mock_ms.get_user_channel_uuids = AsyncMock(return_value=[uuid.uuid4()])

            from app.services.agent_service import AgentService

            service = AgentService()
            response = await service.process_message(
                user_slack_id="U123",
                message="Hello",
                channel_id="C456",
                thread_ts=None,  # No thread
                user_id=uuid.uuid4(),
                workspace_id=uuid.uuid4(),
            )

            assert response.content == "Hi there!"
            # AsyncSessionLocal should NOT have been called because thread_ts is None
            mock_session_local.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_message_saves_memory_successfully(self):
        """When thread_ts is present, user query and agent response are persisted to DB."""
        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(
            return_value={
                "messages": [
                    SystemMessage(content="system"),
                    HumanMessage(content="Who are you?"),
                    AIMessage(content="I am HiveMind."),
                ],
            }
        )

        # Mocks for database
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = None  # Lazily create session
        mock_session.execute = AsyncMock(return_value=mock_res)
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        mock_session_local = MagicMock()
        mock_session_local.return_value.__aenter__ = AsyncMock(
            return_value=mock_session
        )
        mock_session_local.return_value.__aexit__ = AsyncMock(return_value=None)

        workspace_id = uuid.uuid4()
        user_id = uuid.uuid4()
        thread_ts = "1716382103.001234"

        with (
            patch("app.services.agent_service.settings") as mock_settings,
            patch("app.agent.graph.build_agent_graph", return_value=mock_graph),
            patch("app.services.agent_service.event_bus") as mock_bus,
            patch("app.services.membership_service.membership_service") as mock_ms,
            patch("app.database.AsyncSessionLocal", new=mock_session_local),
        ):
            mock_settings.llm_configured = True
            mock_settings.llm_provider = "openrouter"
            mock_settings.llm_model = "test-model"
            mock_bus.publish = AsyncMock()
            mock_ms.get_user_channel_uuids = AsyncMock(return_value=[uuid.uuid4()])

            from app.services.agent_service import AgentService

            service = AgentService()
            response = await service.process_message(
                user_slack_id="U123",
                message="Who are you?",
                channel_id="C456",
                thread_ts=thread_ts,
                user_id=user_id,
                workspace_id=workspace_id,
            )

            assert response.content == "I am HiveMind."

            # Verify session and messages are added
            added_objects = [args[0] for args, _ in mock_session.add.call_args_list]

            # We expect:
            # 1. AgentSession (lazily created)
            # 2. AgentMessage (human)
            # 3. AgentMessage (ai)
            assert len(added_objects) == 3

            agent_session = added_objects[0]
            assert agent_session.workspace_id == workspace_id
            assert agent_session.user_id == user_id
            assert agent_session.platform == Platform.SLACK
            assert agent_session.external_session_id == thread_ts

            human_msg = added_objects[1]
            assert human_msg.role == "human"
            assert human_msg.content == "Who are you?"

            ai_msg = added_objects[2]
            assert ai_msg.role == "ai"
            assert ai_msg.content == "I am HiveMind."

            mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_process_message_loads_memory_successfully(self):
        """When thread_ts exists, past message history is loaded and fed to LangGraph."""
        # Create mock database messages
        mock_db_session = MagicMock()
        mock_db_session.id = uuid.uuid4()

        mock_msg1 = MagicMock()
        mock_msg1.role = "human"
        mock_msg1.content = "What is the capital of France?"
        mock_msg2 = MagicMock()
        mock_msg2.role = "ai"
        mock_msg2.content = "The capital of France is Paris."

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(
            return_value={
                "messages": [
                    SystemMessage(content="system"),
                    HumanMessage(content="France?"),
                    AIMessage(content="Yes, Paris is the capital."),
                ],
            }
        )

        # Mock query execution
        mock_session = AsyncMock()
        mock_session.add = MagicMock()

        # We execute two queries:
        # 1. Fetch AgentSession
        # 2. Fetch AgentMessages
        mock_session_res1 = MagicMock()
        mock_session_res1.scalar_one_or_none.return_value = mock_db_session

        mock_session_res2 = MagicMock()
        mock_session_res2.scalars.return_value = [
            mock_msg2,
            mock_msg1,
        ]  # desc limit order: AI, then Human

        mock_session.execute = AsyncMock(
            side_effect=[mock_session_res1, mock_session_res2, mock_session_res1]
        )
        mock_session.commit = AsyncMock()

        mock_session_local = MagicMock()
        mock_session_local.return_value.__aenter__ = AsyncMock(
            return_value=mock_session
        )
        mock_session_local.return_value.__aexit__ = AsyncMock(return_value=None)

        workspace_id = uuid.uuid4()
        user_id = uuid.uuid4()
        thread_ts = "1716382103.001234"

        with (
            patch("app.services.agent_service.settings") as mock_settings,
            patch("app.agent.graph.build_agent_graph", return_value=mock_graph),
            patch("app.services.agent_service.event_bus") as mock_bus,
            patch("app.services.membership_service.membership_service") as mock_ms,
            patch("app.database.AsyncSessionLocal", new=mock_session_local),
        ):
            mock_settings.llm_configured = True
            mock_settings.llm_provider = "openrouter"
            mock_settings.llm_model = "test-model"
            mock_bus.publish = AsyncMock()
            mock_ms.get_user_channel_uuids = AsyncMock(return_value=[uuid.uuid4()])

            from app.services.agent_service import AgentService

            service = AgentService()
            response = await service.process_message(
                user_slack_id="U123",
                message="And Germany?",
                channel_id="C456",
                thread_ts=thread_ts,
                user_id=user_id,
                workspace_id=workspace_id,
            )

            assert response.content == "Yes, Paris is the capital."

            # Verify graph invocation was given the loaded message history + the new prompt
            called_initial_state = mock_graph.ainvoke.call_args[0][0]
            messages = called_initial_state["messages"]

            # Check length: 1 system, 2 history ( Франции & Paris ), 1 new human message ( Germany )
            assert len(messages) == 4
            assert isinstance(messages[0], SystemMessage)
            assert isinstance(messages[1], HumanMessage)
            assert messages[1].content == "What is the capital of France?"
            assert isinstance(messages[2], AIMessage)
            assert messages[2].content == "The capital of France is Paris."
            assert isinstance(messages[3], HumanMessage)
            assert messages[3].content == "And Germany?"

    @pytest.mark.asyncio
    async def test_process_message_truncates_history_cleanly(self):
        """Graph loading is restricted to the last 10 messages of a conversation thread."""
        mock_db_session = MagicMock()
        mock_db_session.id = uuid.uuid4()

        # Build list of 12 historical messages
        mock_messages = []
        for i in range(12):
            msg = MagicMock()
            msg.role = "human" if i % 2 == 0 else "ai"
            msg.content = f"Message {i}"
            mock_messages.append(msg)

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(
            return_value={
                "messages": [
                    SystemMessage(content="system"),
                    HumanMessage(content="France?"),
                    AIMessage(content="Paris"),
                ],
            }
        )

        mock_session = AsyncMock()
        mock_session.add = MagicMock()

        mock_session_res1 = MagicMock()
        mock_session_res1.scalar_one_or_none.return_value = mock_db_session

        # When querying messages, we limit to 10. The DB returns them in desc order
        mock_session_res2 = MagicMock()
        mock_session_res2.scalars.return_value = mock_messages[:10]

        mock_session.execute = AsyncMock(
            side_effect=[mock_session_res1, mock_session_res2, mock_session_res1]
        )

        mock_session_local = MagicMock()
        mock_session_local.return_value.__aenter__ = AsyncMock(
            return_value=mock_session
        )
        mock_session_local.return_value.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("app.services.agent_service.settings") as mock_settings,
            patch("app.agent.graph.build_agent_graph", return_value=mock_graph),
            patch("app.services.agent_service.event_bus") as mock_bus,
            patch("app.services.membership_service.membership_service") as mock_ms,
            patch("app.database.AsyncSessionLocal", new=mock_session_local),
        ):
            mock_settings.llm_configured = True
            mock_ms.get_user_channel_uuids = AsyncMock(return_value=[uuid.uuid4()])
            mock_bus.publish = AsyncMock()

            from app.services.agent_service import AgentService

            service = AgentService()
            await service.process_message(
                user_slack_id="U123",
                message="Next question",
                channel_id="C456",
                thread_ts="123.456",
                user_id=uuid.uuid4(),
                workspace_id=uuid.uuid4(),
            )

            # Assert that the initial state loaded exactly 10 historical messages
            called_initial_state = mock_graph.ainvoke.call_args[0][0]
            messages = called_initial_state["messages"]

            # 1 system + 10 history + 1 new human prompt = 12 total messages
            assert len(messages) == 12
            assert (
                messages[1].content == "Message 9"
            )  # chronological first of the desc-sliced last-10
            assert (
                messages[10].content == "Message 0"
            )  # chronological last of the desc-sliced last-10
            assert messages[11].content == "Next question"
