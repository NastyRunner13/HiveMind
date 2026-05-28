"""
Tests for the Membership Service.

Tests the channel membership service that provides server-derived
ACL context for knowledge search and agent tool authorization.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Check if asyncpg is available (needed by app.database → membership_service)
try:
    import asyncpg

    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False

skip_without_asyncpg = pytest.mark.skipif(
    not HAS_ASYNCPG,
    reason="asyncpg not installed — membership_service imports app.database",
)


@pytest.fixture
def membership_service():
    """Create a fresh MembershipService instance."""
    from app.services.membership_service import MembershipService

    return MembershipService()


@pytest.fixture
def workspace_id():
    return uuid.uuid4()


@pytest.fixture
def channel_id():
    return uuid.uuid4()


@pytest.fixture
def user_id():
    return uuid.uuid4()


@skip_without_asyncpg
class TestGetUserChannelIds:
    """Tests for get_user_channel_ids."""

    @pytest.mark.asyncio
    async def test_returns_channel_ids_for_active_memberships(
        self, membership_service
    ):
        """Should return channel IDs where user has active membership."""
        with patch(
            "app.services.membership_service.AsyncSessionLocal"
        ) as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_factory.return_value.__aexit__ = AsyncMock(
                return_value=None
            )

            # Simulate DB returning channel IDs
            mock_result = MagicMock()
            mock_result.all.return_value = [
                ("C111",),
                ("C222",),
                ("C333",),
            ]
            mock_session.execute = AsyncMock(return_value=mock_result)

            result = await membership_service.get_user_channel_ids("U12345")

            assert result == ["C111", "C222", "C333"]

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_memberships(
        self, membership_service
    ):
        """Should return empty list when user has no memberships."""
        with patch(
            "app.services.membership_service.AsyncSessionLocal"
        ) as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_factory.return_value.__aexit__ = AsyncMock(
                return_value=None
            )

            mock_result = MagicMock()
            mock_result.all.return_value = []
            mock_session.execute = AsyncMock(return_value=mock_result)

            result = await membership_service.get_user_channel_ids("U99999")

            assert result == []


@skip_without_asyncpg
class TestHandleMemberJoined:
    """Tests for handle_member_joined."""

    @pytest.mark.asyncio
    async def test_records_membership_on_join(
        self, membership_service, workspace_id, channel_id, user_id
    ):
        """Should upsert a membership record when user joins a channel."""
        with patch(
            "app.services.membership_service.AsyncSessionLocal"
        ) as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_factory.return_value.__aexit__ = AsyncMock(
                return_value=None
            )

            # Mock workspace lookup
            ws = MagicMock()
            ws.id = workspace_id
            ws_result = MagicMock()
            ws_result.scalar_one_or_none.return_value = ws

            # Mock channel lookup
            ch_result = MagicMock()
            ch_result.scalar_one_or_none.return_value = channel_id

            # Mock user lookup
            user_result = MagicMock()
            user_result.scalar_one_or_none.return_value = user_id

            # Mock canonical user lookup (via UserPlatformMapping)
            canonical_result = MagicMock()
            canonical_result.scalar_one_or_none.return_value = user_id

            mock_session.execute = AsyncMock(
                side_effect=[ws_result, ch_result, user_result, canonical_result, MagicMock()]
            )
            mock_session.commit = AsyncMock()

            await membership_service.handle_member_joined(
                slack_user_id="U12345",
                slack_channel_id="C67890",
            )

            # Should have committed the upsert
            mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_join_when_no_workspace(self, membership_service):
        """Should skip if no active workspace exists."""
        with patch(
            "app.services.membership_service.AsyncSessionLocal"
        ) as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_factory.return_value.__aexit__ = AsyncMock(
                return_value=None
            )

            ws_result = MagicMock()
            ws_result.scalar_one_or_none.return_value = None
            mock_session.execute = AsyncMock(return_value=ws_result)

            # Should not raise
            await membership_service.handle_member_joined(
                slack_user_id="U12345",
                slack_channel_id="C67890",
            )

            # Should not commit
            mock_session.commit.assert_not_called()


@skip_without_asyncpg
class TestHandleMemberLeft:
    """Tests for handle_member_left."""

    @pytest.mark.asyncio
    async def test_deactivates_membership_on_leave(
        self, membership_service
    ):
        """Should set is_active=False when user leaves a channel."""
        with patch(
            "app.services.membership_service.AsyncSessionLocal"
        ) as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_factory.return_value.__aexit__ = AsyncMock(
                return_value=None
            )
            mock_session.execute = AsyncMock()
            mock_session.commit = AsyncMock()

            await membership_service.handle_member_left(
                slack_user_id="U12345",
                slack_channel_id="C67890",
            )

            # Should have issued an update and committed
            mock_session.execute.assert_called_once()
            mock_session.commit.assert_called_once()


@skip_without_asyncpg
class TestSyncChannelMembers:
    """Tests for sync_channel_members."""

    @pytest.mark.asyncio
    async def test_syncs_member_list(
        self, membership_service, workspace_id, channel_id
    ):
        """Should upsert all provided members for a channel."""
        with patch(
            "app.services.membership_service.AsyncSessionLocal"
        ) as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_factory.return_value.__aexit__ = AsyncMock(
                return_value=None
            )

            # Mock channel lookup
            ch_result = MagicMock()
            ch_result.scalar_one_or_none.return_value = channel_id

            # Mock user mapping
            user_id_1 = uuid.uuid4()
            user_id_2 = uuid.uuid4()
            user_row_1 = MagicMock()
            user_row_1.slack_user_id = "U111"
            user_row_1.id = user_id_1
            user_row_2 = MagicMock()
            user_row_2.slack_user_id = "U222"
            user_row_2.id = user_id_2
            user_result = MagicMock()
            user_result.all.return_value = [user_row_1, user_row_2]

            # Mock canonical user mapping lookup
            canonical_row_1 = MagicMock()
            canonical_row_1.external_user_id = "U111"
            canonical_row_1.user_id = user_id_1
            canonical_row_2 = MagicMock()
            canonical_row_2.external_user_id = "U222"
            canonical_row_2.user_id = user_id_2
            canonical_result = MagicMock()
            canonical_result.all.return_value = [canonical_row_1, canonical_row_2]

            mock_session.execute = AsyncMock(
                side_effect=[ch_result, user_result, canonical_result]
                + [MagicMock()] * 3  # upserts + deactivation
            )
            mock_session.commit = AsyncMock()

            stats = await membership_service.sync_channel_members(
                slack_channel_id="C67890",
                member_slack_ids=["U111", "U222"],
                workspace_id=workspace_id,
            )

            assert stats["added"] == 2
            mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_empty_stats_when_channel_not_found(
        self, membership_service, workspace_id
    ):
        """Should return empty stats when channel is not in DB."""
        with patch(
            "app.services.membership_service.AsyncSessionLocal"
        ) as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_factory.return_value.__aexit__ = AsyncMock(
                return_value=None
            )

            ch_result = MagicMock()
            ch_result.scalar_one_or_none.return_value = None
            mock_session.execute = AsyncMock(return_value=ch_result)

            stats = await membership_service.sync_channel_members(
                slack_channel_id="C99999",
                member_slack_ids=["U111"],
                workspace_id=workspace_id,
            )

            assert stats == {"added": 0, "reactivated": 0, "deactivated": 0}
