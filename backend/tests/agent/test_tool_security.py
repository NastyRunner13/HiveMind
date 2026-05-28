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
    import asyncpg

    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False

skip_without_asyncpg = pytest.mark.skipif(
    not HAS_ASYNCPG,
    reason="asyncpg not installed — tools imports app.database",
)


@pytest.fixture
def user_channel_ids():
    """Channel IDs the test user is a member of."""
    return ["C_PUBLIC_1", "C_PUBLIC_2", "C_PRIVATE_1"]


@pytest.fixture
def tools(user_channel_ids):
    """Create tools scoped to our test user."""
    from app.agent.tools import create_tools

    return create_tools(
        user_slack_id="U_TEST_USER",
        user_channel_ids=user_channel_ids,
    )


@pytest.fixture
def tools_with_canonical(user_channel_ids):
    """Create tools scoped to our test user with canonical UUIDs."""
    import uuid as uuid_mod

    from app.agent.tools import create_tools

    return create_tools(
        user_slack_id="U_TEST_USER",
        user_channel_ids=user_channel_ids,
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

    def test_creates_five_tools(self, tools):
        """create_tools should return exactly 5 tools."""
        assert len(tools) == 5

    def test_tool_names(self, tools):
        """Verify all expected tools are created."""
        names = {t.name for t in tools}
        assert names == {
            "search_knowledge",
            "get_recent_messages",
            "list_channels",
            "get_channel_activity_summary",
            "generate_digest",
        }

    def test_tools_do_not_expose_acl_params(self, tools):
        """Tools should NOT have user_channel_ids or user_slack_id as arguments."""
        for t in tools:
            args = t.args_schema.schema() if t.args_schema else {}
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

    def test_tools_with_canonical_do_not_expose_acl_params(
        self, tools_with_canonical
    ):
        """Tools created with canonical UUIDs should also NOT expose ACL params."""
        for t in tools_with_canonical:
            args = t.args_schema.schema() if t.args_schema else {}
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
    async def test_passes_user_context_to_service(self, tools):
        """search_knowledge should pass the closed-over user context."""
        search = get_tool_by_name(tools, "search_knowledge")

        with patch(
            "app.agent.tools.knowledge_service"
        ) as mock_ks:
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


@skip_without_asyncpg
class TestGetRecentMessagesSecurity:
    """Tests that get_recent_messages enforces channel ACL."""

    @pytest.mark.asyncio
    async def test_denies_access_to_private_channel_user_is_not_in(
        self, tools
    ):
        """Should deny access to a private channel the user is NOT a member of."""
        get_messages = get_tool_by_name(tools, "get_recent_messages")

        with patch(
            "app.agent.tools.AsyncSessionLocal"
        ) as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_factory.return_value.__aexit__ = AsyncMock(
                return_value=None
            )

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

            response = await get_messages.ainvoke(
                {"channel_name": "secret-channel"}
            )

            # Should return an access denied message
            assert "don't have access" in response.lower()


@skip_without_asyncpg
class TestListChannelsSecurity:
    """Tests that list_channels filters to user's accessible channels."""

    @pytest.mark.asyncio
    async def test_filters_to_user_channels(self, tools):
        """list_channels should include user's channels and public channels."""
        list_ch = get_tool_by_name(tools, "list_channels")

        with patch(
            "app.agent.tools.AsyncSessionLocal"
        ) as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_factory.return_value.__aexit__ = AsyncMock(
                return_value=None
            )

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
    async def test_denies_digest_for_private_channel_user_is_not_in(
        self, tools
    ):
        """Should deny digest generation for private channels user can't access."""
        digest = get_tool_by_name(tools, "generate_digest")

        with patch(
            "app.agent.tools.AsyncSessionLocal"
        ) as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_factory.return_value.__aexit__ = AsyncMock(
                return_value=None
            )

            from app.models.channel import ChannelType

            private_ch = MagicMock()
            private_ch.id = uuid.uuid4()
            private_ch.name = "secret-channel"
            private_ch.slack_channel_id = "C_SECRET"
            private_ch.channel_type = ChannelType.PRIVATE

            # First execute returns workspace, second returns channel
            ws_result = MagicMock()
            ws = MagicMock()
            ws.id = uuid.uuid4()
            ws_result.scalar_one_or_none.return_value = ws

            ch_result = MagicMock()
            ch_result.scalar_one_or_none.return_value = private_ch

            mock_session.execute = AsyncMock(
                side_effect=[ws_result, ch_result]
            )
            mock_session.get = AsyncMock(return_value=None)

            response = await digest.ainvoke(
                {"channel_name": "secret-channel"}
            )

            assert "don't have access" in response.lower()
