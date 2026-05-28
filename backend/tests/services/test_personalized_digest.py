"""
Tests for Personalized Digest generation.

Verifies that generate_personalized_digest():
- Includes private channels the user is a member of
- Excludes private channels the user is NOT a member of
- Returns None when user has no channel memberships
- Returns None when no channels have activity
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Check if asyncpg is available
try:
    import asyncpg  # noqa: F401

    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False

skip_without_asyncpg = pytest.mark.skipif(
    not HAS_ASYNCPG,
    reason="asyncpg not installed — digest_service imports app.database",
)


def _make_channel(name, slack_id, channel_type_value="public", is_archived=False):
    """Create a mock Channel object."""
    ch = MagicMock()
    ch.id = uuid.uuid4()
    ch.name = name
    ch.slack_channel_id = slack_id
    ch.is_archived = is_archived
    ch.workspace_id = uuid.uuid4()

    from app.models.channel import ChannelType

    ch.channel_type = ChannelType(channel_type_value)
    return ch


def _make_workspace():
    """Create a mock Workspace object."""
    ws = MagicMock()
    ws.id = uuid.uuid4()
    ws.is_active = True
    return ws


@skip_without_asyncpg
class TestGeneratePersonalizedDigest:
    """Tests for DigestService.generate_personalized_digest()."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_memberships(self):
        """Should return None when user has no channel memberships."""
        from app.services.digest_service import DigestService

        service = DigestService()

        with patch("app.services.membership_service.membership_service") as mock_ms:
            mock_ms.get_user_channel_ids = AsyncMock(return_value=[])

            result = await service.generate_personalized_digest("U_TEST")

            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_workspace(self):
        """Should return None when no active workspace exists."""
        from app.services.digest_service import DigestService

        service = DigestService()

        with (
            patch("app.services.membership_service.membership_service") as mock_ms,
            patch("app.services.digest_service.AsyncSessionLocal") as mock_factory,
        ):
            mock_ms.get_user_channel_ids = AsyncMock(
                return_value=["C_PUB_1", "C_PRIV_1"]
            )

            # Mock session — no workspace found
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            ws_result = MagicMock()
            ws_result.scalar_one_or_none.return_value = None
            mock_session.execute = AsyncMock(return_value=ws_result)

            result = await service.generate_personalized_digest("U_TEST")

            assert result is None

    @pytest.mark.asyncio
    async def test_queries_user_channels_from_membership_service(self):
        """Should call membership_service to get user's channel IDs."""
        from app.services.digest_service import DigestService

        service = DigestService()

        with (
            patch("app.services.membership_service.membership_service") as mock_ms,
            patch("app.services.digest_service.AsyncSessionLocal") as mock_factory,
        ):
            mock_ms.get_user_channel_ids = AsyncMock(
                return_value=["C_PUB_1", "C_PRIV_1"]
            )

            # Mock session — workspace found but no channels
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            ws = _make_workspace()
            ws_result = MagicMock()
            ws_result.scalar_one_or_none.return_value = ws

            ch_result = MagicMock()
            ch_result.scalars.return_value.all.return_value = []

            mock_session.execute = AsyncMock(side_effect=[ws_result, ch_result])

            await service.generate_personalized_digest("U_TEST")

            # Verify membership service was called with the user ID
            mock_ms.get_user_channel_ids.assert_called_once_with("U_TEST")

    @pytest.mark.asyncio
    async def test_returns_none_when_no_channels_have_activity(self):
        """Should return None when channels exist but have no activity."""
        from app.services.digest_service import DigestService

        service = DigestService()

        with (
            patch("app.services.membership_service.membership_service") as mock_ms,
            patch("app.services.digest_service.AsyncSessionLocal") as mock_factory,
        ):
            mock_ms.get_user_channel_ids = AsyncMock(return_value=["C_PUB_1"])

            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            ws = _make_workspace()
            ch = _make_channel("general", "C_PUB_1")
            ch.workspace_id = ws.id

            ws_result = MagicMock()
            ws_result.scalar_one_or_none.return_value = ws

            ch_result = MagicMock()
            ch_result.scalars.return_value.all.return_value = [ch]

            mock_session.execute = AsyncMock(side_effect=[ws_result, ch_result])

            # Mock _generate_channel_summary_only to return None (no activity)
            with patch.object(
                service,
                "_generate_channel_summary_only",
                new_callable=AsyncMock,
                return_value=None,
            ):
                result = await service.generate_personalized_digest("U_TEST")

            assert result is None

    @pytest.mark.asyncio
    async def test_includes_private_channel_user_is_member_of(self):
        """Should include private channels the user is a member of."""
        from app.services.digest_service import DigestService

        service = DigestService()

        with (
            patch("app.services.membership_service.membership_service") as mock_ms,
            patch("app.services.digest_service.AsyncSessionLocal") as mock_factory,
        ):
            mock_ms.get_user_channel_ids = AsyncMock(
                return_value=["C_PUB_1", "C_PRIV_1"]
            )

            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            ws = _make_workspace()
            public_ch = _make_channel("general", "C_PUB_1", "public")
            private_ch = _make_channel("secret-team", "C_PRIV_1", "private")

            ws_result = MagicMock()
            ws_result.scalar_one_or_none.return_value = ws

            ch_result = MagicMock()
            ch_result.scalars.return_value.all.return_value = [
                public_ch,
                private_ch,
            ]

            mock_session.execute = AsyncMock(side_effect=[ws_result, ch_result])

            # Mock _generate_channel_summary_only for both channels
            with patch.object(
                service,
                "_generate_channel_summary_only",
                new_callable=AsyncMock,
                side_effect=["Public channel summary", "Private channel summary"],
            ):
                result = await service.generate_personalized_digest("U_TEST")

            assert result is not None
            assert "general" in result
            assert "secret-team" in result
            assert "Public channel summary" in result
            assert "Private channel summary" in result


@skip_without_asyncpg
class TestGeneratePersonalizedDigestCanonical:
    """Tests for generate_personalized_digest() with canonical UUID path."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_canonical_memberships(self):
        """Should return None when canonical user has no channel memberships."""
        from app.services.digest_service import DigestService

        service = DigestService()

        with patch("app.services.digest_service.AsyncSessionLocal") as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            # Return empty membership list
            membership_result = MagicMock()
            membership_result.all.return_value = []
            mock_session.execute = AsyncMock(return_value=membership_result)

            result = await service.generate_personalized_digest(
                user_slack_id="U_TEST",
                canonical_user_id=uuid.uuid4(),
            )

            assert result is None

    @pytest.mark.asyncio
    async def test_canonical_path_queries_by_channel_uuid(self):
        """Should filter channels by Channel.id (UUID) when canonical_user_id is set."""
        from app.services.digest_service import DigestService

        service = DigestService()

        ch1_id = uuid.uuid4()
        ch2_id = uuid.uuid4()
        canonical_uid = uuid.uuid4()

        with patch("app.services.digest_service.AsyncSessionLocal") as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            # First call (membership lookup): return two channel UUIDs
            membership_result = MagicMock()
            membership_result.all.return_value = [(ch1_id,), (ch2_id,)]

            # Second call (workspace lookup): return workspace
            ws = _make_workspace()
            ws_result = MagicMock()
            ws_result.scalar_one_or_none.return_value = ws

            # Third call (channel query): return matching channels
            public_ch = _make_channel("general", "C_PUB_1", "public")
            public_ch.id = ch1_id
            private_ch = _make_channel("secret", "C_PRIV_1", "private")
            private_ch.id = ch2_id
            ch_result = MagicMock()
            ch_result.scalars.return_value.all.return_value = [
                public_ch,
                private_ch,
            ]

            mock_session.execute = AsyncMock(
                side_effect=[membership_result, ws_result, ch_result]
            )

            with patch.object(
                service,
                "_generate_channel_summary_only",
                new_callable=AsyncMock,
                side_effect=["General summary", "Secret summary"],
            ):
                result = await service.generate_personalized_digest(
                    user_slack_id="U_TEST",
                    canonical_user_id=canonical_uid,
                )

            assert result is not None
            assert "general" in result
            assert "secret" in result

    @pytest.mark.asyncio
    async def test_canonical_path_falls_back_to_slack_when_no_canonical_id(
        self,
    ):
        """Should use Slack membership path when canonical_user_id is None."""
        from app.services.digest_service import DigestService

        service = DigestService()

        with patch("app.services.membership_service.membership_service") as mock_ms:
            mock_ms.get_user_channel_ids = AsyncMock(return_value=["C_PUB_1"])

            with patch("app.services.digest_service.AsyncSessionLocal") as mock_factory:
                mock_session = AsyncMock()
                mock_factory.return_value.__aenter__ = AsyncMock(
                    return_value=mock_session
                )
                mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

                ws = _make_workspace()
                ws_result = MagicMock()
                ws_result.scalar_one_or_none.return_value = ws

                ch_result = MagicMock()
                ch_result.scalars.return_value.all.return_value = []

                mock_session.execute = AsyncMock(side_effect=[ws_result, ch_result])

                # No canonical_user_id → should call membership_service
                await service.generate_personalized_digest("U_TEST")

                mock_ms.get_user_channel_ids.assert_called_once_with("U_TEST")
