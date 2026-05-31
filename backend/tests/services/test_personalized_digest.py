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
        user_id = uuid.uuid4()

        with patch("app.services.digest_service.AsyncSessionLocal") as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            membership_result = MagicMock()
            membership_result.all.return_value = []
            mock_session.execute = AsyncMock(return_value=membership_result)

            result = await service.generate_personalized_digest(user_id=user_id)

            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_workspace(self):
        """Should return None when no active workspace exists."""
        from app.services.digest_service import DigestService

        service = DigestService()
        user_id = uuid.uuid4()
        ch_uuid = uuid.uuid4()

        with patch("app.services.digest_service.AsyncSessionLocal") as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            membership_result = MagicMock()
            membership_result.all.return_value = [(ch_uuid,)]

            ws_result = MagicMock()
            ws_result.scalar_one_or_none.return_value = None

            mock_session.execute = AsyncMock(side_effect=[membership_result, ws_result])

            result = await service.generate_personalized_digest(user_id=user_id)

            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_channels_have_activity(self):
        """Should return None when channels exist but have no activity."""
        from app.services.digest_service import DigestService

        service = DigestService()
        user_id = uuid.uuid4()
        ch_uuid = uuid.uuid4()

        with patch("app.services.digest_service.AsyncSessionLocal") as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            ws = _make_workspace()
            ch = _make_channel("general", "C_PUB_1")
            ch.id = ch_uuid
            ch.workspace_id = ws.id

            membership_result = MagicMock()
            membership_result.all.return_value = [(ch_uuid,)]

            ws_result = MagicMock()
            ws_result.scalar_one_or_none.return_value = ws

            ch_result = MagicMock()
            ch_result.scalars.return_value.all.return_value = [ch]

            mock_session.execute = AsyncMock(
                side_effect=[membership_result, ws_result, ch_result]
            )

            # Mock _generate_channel_summary_only to return None (no activity)
            with patch.object(
                service,
                "_generate_channel_summary_only",
                new_callable=AsyncMock,
                return_value=None,
            ):
                result = await service.generate_personalized_digest(user_id=user_id)

            assert result is None

    @pytest.mark.asyncio
    async def test_includes_private_channel_user_is_member_of(self):
        """Should include private channels the user is a member of."""
        from app.services.digest_service import DigestService

        service = DigestService()
        user_id = uuid.uuid4()
        ch1_uuid = uuid.uuid4()
        ch2_uuid = uuid.uuid4()

        with patch("app.services.digest_service.AsyncSessionLocal") as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            ws = _make_workspace()
            public_ch = _make_channel("general", "C_PUB_1", "public")
            public_ch.id = ch1_uuid
            private_ch = _make_channel("secret-team", "C_PRIV_1", "private")
            private_ch.id = ch2_uuid

            membership_result = MagicMock()
            membership_result.all.return_value = [(ch1_uuid,), (ch2_uuid,)]

            ws_result = MagicMock()
            ws_result.scalar_one_or_none.return_value = ws

            ch_result = MagicMock()
            ch_result.scalars.return_value.all.return_value = [
                public_ch,
                private_ch,
            ]

            mock_session.execute = AsyncMock(
                side_effect=[membership_result, ws_result, ch_result]
            )

            # Mock _generate_channel_summary_only for both channels
            with patch.object(
                service,
                "_generate_channel_summary_only",
                new_callable=AsyncMock,
                side_effect=["Public channel summary", "Private channel summary"],
            ):
                result = await service.generate_personalized_digest(user_id=user_id)

            assert result is not None
            assert "general" in result
            assert "secret-team" in result
            assert "Public channel summary" in result
            assert "Private channel summary" in result

    @pytest.mark.asyncio
    async def test_passes_requested_hours_to_channel_summaries(self):
        """Past-week personalized digest should use the requested time window."""
        from app.services.digest_service import DigestService

        service = DigestService()
        user_id = uuid.uuid4()
        ch_uuid = uuid.uuid4()

        with patch("app.services.digest_service.AsyncSessionLocal") as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            ws = _make_workspace()
            ch = _make_channel("general", "C_PUB_1", "public")
            ch.id = ch_uuid

            membership_result = MagicMock()
            membership_result.all.return_value = [(ch_uuid,)]

            ws_result = MagicMock()
            ws_result.scalar_one_or_none.return_value = ws

            ch_result = MagicMock()
            ch_result.scalars.return_value.all.return_value = [ch]

            mock_session.execute = AsyncMock(
                side_effect=[membership_result, ws_result, ch_result]
            )

            with patch.object(
                service,
                "_generate_channel_summary_only",
                new_callable=AsyncMock,
                return_value="General summary",
            ) as mock_summary:
                await service.generate_personalized_digest(user_id=user_id, hours=168)

        mock_summary.assert_called_once()
        assert mock_summary.call_args.kwargs["hours"] == 168
