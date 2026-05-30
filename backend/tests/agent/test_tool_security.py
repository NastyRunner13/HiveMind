"""
Tests for Agent Tool Security.

Verifies that agent tools enforce ACL by using server-derived context
(closed-over user identity and channel memberships) rather than
accepting LLM-controlled ACL arguments.

These are NEGATIVE security tests — they verify that data access
is properly denied when a user lacks authorization.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Check if asyncpg is available (needed by app.database → tools)
try:
    import asyncpg  # noqa: F401

    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False

skip_without_asyncpg = pytest.mark.skipif(
    not HAS_ASYNCPG,
    reason="asyncpg not installed — tools imports app.database",
)


@pytest.fixture
def workspace_id():
    """Workspace UUID that scopes all tool calls."""
    return uuid.uuid4()


@pytest.fixture
def user_channel_ids():
    """Channel IDs the test user is a member of."""
    return ["C_PUBLIC_1", "C_PUBLIC_2", "C_PRIVATE_1"]


@pytest.fixture
def tools(user_channel_ids, workspace_id):
    """Create tools scoped to our test user."""
    from app.agent.tools import create_tools

    return create_tools(
        user_slack_id="U_TEST_USER",
        user_channel_ids=user_channel_ids,
        workspace_id=workspace_id,
    )


@pytest.fixture
def tools_with_canonical(user_channel_ids, workspace_id):
    """Create tools scoped to our test user with canonical UUIDs."""
    import uuid as uuid_mod

    from app.agent.tools import create_tools

    return create_tools(
        user_slack_id="U_TEST_USER",
        user_channel_ids=user_channel_ids,
        workspace_id=workspace_id,
        canonical_user_id=uuid_mod.uuid4(),
        canonical_channel_ids=[uuid_mod.uuid4(), uuid_mod.uuid4()],
    )


def get_tool_by_name(tools, name):
    """Helper to find a tool by name."""
    for t in tools:
        if t.name == name:
            return t
    raise ValueError(f"Tool '{name}' not found")


@skip_without_asyncpg
class TestToolCreation:
    """Tests for the tool factory itself."""

    def test_creates_six_tools(self, tools):
        """create_tools should return the expected tool set."""
        assert len(tools) == 6

    def test_tool_names(self, tools):
        """Verify all expected tools are created."""
        names = {t.name for t in tools}
        assert names == {
            "search_knowledge",
            "get_recent_messages",
            "list_channels",
            "get_channel_activity_summary",
            "generate_digest",
            "summarize_activity",
        }

    def test_tools_do_not_expose_acl_params(self, tools):
        """Tools should NOT have user_channel_ids or user_slack_id as arguments."""
        for t in tools:
            args = t.args_schema.model_json_schema() if t.args_schema else {}
            properties = args.get("properties", {})
            assert "user_slack_id" not in properties, (
                f"Tool '{t.name}' exposes user_slack_id as an LLM argument"
            )
            assert "user_channel_ids" not in properties, (
                f"Tool '{t.name}' exposes user_channel_ids as an LLM argument"
            )
            assert "channel_ids" not in properties, (
                f"Tool '{t.name}' exposes channel_ids as an LLM argument"
            )
            assert "canonical_user_id" not in properties, (
                f"Tool '{t.name}' exposes canonical_user_id as an LLM argument"
            )
            assert "canonical_channel_ids" not in properties, (
                f"Tool '{t.name}' exposes canonical_channel_ids as an LLM argument"
            )

    def test_tools_with_canonical_do_not_expose_acl_params(self, tools_with_canonical):
        """Tools created with canonical UUIDs should also NOT expose ACL params."""
        for t in tools_with_canonical:
            args = t.args_schema.model_json_schema() if t.args_schema else {}
            properties = args.get("properties", {})
            assert "canonical_user_id" not in properties, (
                f"Tool '{t.name}' exposes canonical_user_id as an LLM argument"
            )
            assert "canonical_channel_ids" not in properties, (
                f"Tool '{t.name}' exposes canonical_channel_ids as an LLM argument"
            )


@skip_without_asyncpg
class TestSearchKnowledgeSecurity:
    """Tests that search_knowledge uses closed-over ACL context."""

    @pytest.mark.asyncio
    async def test_passes_user_context_to_service(self, tools, workspace_id):
        """search_knowledge should pass the closed-over user context."""
        search = get_tool_by_name(tools, "search_knowledge")

        with patch("app.agent.tools.knowledge_service") as mock_ks:
            mock_ks.search = AsyncMock(return_value=[])

            await search.ainvoke({"query": "test query"})

            # Verify the search was called with server-derived context
            mock_ks.search.assert_called_once()
            call_kwargs = mock_ks.search.call_args
            assert call_kwargs.kwargs["user_slack_id"] == "U_TEST_USER"
            assert call_kwargs.kwargs["user_channel_ids"] == [
                "C_PUBLIC_1",
                "C_PUBLIC_2",
                "C_PRIVATE_1",
            ]
            assert call_kwargs.kwargs["workspace_id"] == workspace_id

    @pytest.mark.asyncio
    async def test_search_accepts_bounded_time_window(self, tools, workspace_id):
        """search_knowledge should pass explicit time filters to the service."""
        search = get_tool_by_name(tools, "search_knowledge")

        with patch("app.agent.tools.knowledge_service") as mock_ks:
            mock_ks.search = AsyncMock(return_value=[])

            await search.ainvoke({"query": "test query", "hours": 168, "top_k": 10})

            call_kwargs = mock_ks.search.call_args.kwargs
            assert call_kwargs["workspace_id"] == workspace_id
            assert call_kwargs["since"] is not None
            assert call_kwargs["until"] is not None
            assert call_kwargs["top_k"] == 10

    @pytest.mark.asyncio
    async def test_rejects_oversized_search_window(self, tools):
        """Tool schemas should reject LLM-supplied values outside bounds."""
        search = get_tool_by_name(tools, "search_knowledge")

        with pytest.raises(Exception):
            await search.ainvoke({"query": "test query", "hours": 999})

    @pytest.mark.asyncio
    async def test_search_tool_times_out(self, tools):
        """Tool execution should return safely when a backend call hangs."""
        search = get_tool_by_name(tools, "search_knowledge")

        with (
            patch("app.agent.tools.knowledge_service") as mock_ks,
            patch("app.agent.tools.get_settings") as mock_get_settings,
        ):
            mock_ks.search = AsyncMock(side_effect=TimeoutError)
            mock_get_settings.return_value.agent_tool_timeout_seconds = 1

            response = await search.ainvoke({"query": "test query"})

            assert "timed out" in response


@skip_without_asyncpg
class TestGetRecentMessagesSecurity:
    """Tests that get_recent_messages enforces channel ACL."""

    @pytest.mark.asyncio
    async def test_denies_access_to_private_channel_user_is_not_in(self, tools):
        """Should deny access to a private channel the user is NOT a member of."""
        get_messages = get_tool_by_name(tools, "get_recent_messages")

        with patch("app.agent.tools.AsyncSessionLocal") as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            # Mock a private channel the user is NOT a member of
            private_ch = MagicMock()
            private_ch.id = uuid.uuid4()
            private_ch.name = "secret-channel"
            private_ch.slack_channel_id = "C_SECRET"  # Not in user_channel_ids
            private_ch.channel_type = MagicMock(value="private")

            # We need channel_type comparison to work
            from app.models.channel import ChannelType

            private_ch.channel_type = ChannelType.PRIVATE

            result = MagicMock()
            result.scalar_one_or_none.return_value = private_ch
            mock_session.execute = AsyncMock(return_value=result)

            response = await get_messages.ainvoke({"channel_name": "secret-channel"})

            # Should return an access denied message
            assert "don't have access" in response.lower()


@skip_without_asyncpg
class TestListChannelsSecurity:
    """Tests that list_channels filters to user's accessible channels."""

    @pytest.mark.asyncio
    async def test_filters_to_user_channels(self, tools):
        """list_channels should include user's channels and public channels."""
        list_ch = get_tool_by_name(tools, "list_channels")

        with patch("app.agent.tools.AsyncSessionLocal") as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result_mock = MagicMock()
            result_mock.scalars.return_value.all.return_value = []
            mock_session.execute = AsyncMock(return_value=result_mock)

            await list_ch.ainvoke({})

            # Verify the query was executed (it should filter by user channels)
            mock_session.execute.assert_called_once()


@skip_without_asyncpg
class TestGenerateDigestSecurity:
    """Tests that generate_digest respects channel ACL."""

    @pytest.mark.asyncio
    async def test_denies_digest_for_private_channel_user_is_not_in(self, tools):
        """Should deny digest generation for private channels user can't access."""
        digest = get_tool_by_name(tools, "generate_digest")

        with patch("app.agent.tools.AsyncSessionLocal") as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            from app.models.channel import ChannelType

            private_ch = MagicMock()
            private_ch.id = uuid.uuid4()
            private_ch.name = "secret-channel"
            private_ch.slack_channel_id = "C_SECRET"
            private_ch.channel_type = ChannelType.PRIVATE

            ws = MagicMock()
            ws.id = uuid.uuid4()

            ch_result = MagicMock()
            ch_result.scalar_one_or_none.return_value = private_ch

            mock_session.execute = AsyncMock(return_value=ch_result)
            mock_session.get = AsyncMock(return_value=ws)

            response = await digest.ainvoke({"channel_name": "secret-channel"})

            assert "don't have access" in response.lower()
