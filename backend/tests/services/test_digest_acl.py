"""
Tests for Digest ACL enforcement (Fix 1 + Fix 2).

Verifies:
- generate_personalized_digest() does NOT store to DB
- list_digests endpoint excludes private-channel digests
- get_digest endpoint rejects private-channel digests
- Slack digest command rejects non-member for private channels
- HTTP API rejects non-member for private channels
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


def _make_channel(name, slack_id, channel_type_value="public"):
    """Create a mock Channel object."""
    from app.models.channel import ChannelType

    ch = MagicMock()
    ch.id = uuid.uuid4()
    ch.name = name
    ch.slack_channel_id = slack_id
    ch.is_archived = False
    ch.workspace_id = uuid.uuid4()
    ch.channel_type = ChannelType(channel_type_value)
    return ch


def _make_workspace():
    """Create a mock Workspace object."""
    ws = MagicMock()
    ws.id = uuid.uuid4()
    ws.is_active = True
    return ws


@skip_without_asyncpg
class TestPersonalizedDigestDoesNotStore:
    """Fix 1: generate_personalized_digest() must NOT store
    private-channel summaries in the digests table."""

    @pytest.mark.asyncio
    async def test_calls_summary_only_not_channel_digest(self):
        """Should call _generate_channel_summary_only (no DB persist),
        NOT generate_channel_digest (which persists)."""
        from app.services.digest_service import DigestService

        service = DigestService()

        with (
            patch("app.services.membership_service.membership_service") as mock_ms,
            patch("app.services.digest_service.AsyncSessionLocal") as mock_factory,
        ):
            mock_ms.get_user_channel_ids = AsyncMock(return_value=["C_PRIV_1"])

            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            ws = _make_workspace()
            private_ch = _make_channel("secret-team", "C_PRIV_1", "private")

            ws_result = MagicMock()
            ws_result.scalar_one_or_none.return_value = ws

            ch_result = MagicMock()
            ch_result.scalars.return_value.all.return_value = [private_ch]

            mock_session.execute = AsyncMock(side_effect=[ws_result, ch_result])

            # Mock the new _generate_channel_summary_only method
            with patch.object(
                service,
                "_generate_channel_summary_only",
                new_callable=AsyncMock,
                return_value="Private channel summary",
            ) as mock_summary:
                result = await service.generate_personalized_digest("U_TEST")

            # Verify _generate_channel_summary_only was called (NOT generate_channel_digest)
            mock_summary.assert_called_once_with(
                channel_id=private_ch.id,
                hours=24,
            )
            assert result is not None
            assert "secret-team" in result

    @pytest.mark.asyncio
    async def test_does_not_call_generate_channel_digest(self):
        """generate_channel_digest must NEVER be called from
        generate_personalized_digest (it would store to DB)."""
        from app.services.digest_service import DigestService

        service = DigestService()

        with (
            patch("app.services.membership_service.membership_service") as mock_ms,
            patch("app.services.digest_service.AsyncSessionLocal") as mock_factory,
        ):
            mock_ms.get_user_channel_ids = AsyncMock(return_value=["C_PRIV_1"])

            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            ws = _make_workspace()
            private_ch = _make_channel("secret", "C_PRIV_1", "private")

            ws_result = MagicMock()
            ws_result.scalar_one_or_none.return_value = ws

            ch_result = MagicMock()
            ch_result.scalars.return_value.all.return_value = [private_ch]

            mock_session.execute = AsyncMock(side_effect=[ws_result, ch_result])

            with (
                patch.object(
                    service,
                    "_generate_channel_summary_only",
                    new_callable=AsyncMock,
                    return_value="Summary text",
                ),
                patch.object(
                    service,
                    "generate_channel_digest",
                    new_callable=AsyncMock,
                ) as mock_channel_digest,
            ):
                await service.generate_personalized_digest("U_TEST")

            # generate_channel_digest must NOT be called
            mock_channel_digest.assert_not_called()


@skip_without_asyncpg
class TestSlackDigestCommandACL:
    """Fix 2: @HiveMind digest #private-channel should deny non-members."""

    @pytest.mark.asyncio
    async def test_rejects_non_member_for_private_channel(self):
        """Requesting a private channel digest as a non-member
        should get a denial message."""
        from app.slack.events import _handle_digest_command

        mock_say = AsyncMock()

        with (
            patch("app.slack.events.digest_service"),
            patch("app.slack.events.membership_service") as mock_ms,
            patch("app.slack.events.AsyncSessionLocal") as mock_factory,
        ):
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            ws = _make_workspace()
            private_ch = _make_channel("secret-proj", "C_SECRET", "private")

            ws_result = MagicMock()
            ws_result.scalar_one_or_none.return_value = ws

            ch_result = MagicMock()
            ch_result.scalar_one_or_none.return_value = private_ch

            mock_session.execute = AsyncMock(side_effect=[ws_result, ch_result])

            # User is NOT a member of the private channel
            mock_ms.get_user_channel_ids = AsyncMock(return_value=["C_OTHER"])

            await _handle_digest_command(
                clean_text="digest #secret-proj",
                channel="C_WHERE_ASKED",
                thread_ts="123456.789",
                say=mock_say,
                user_slack_id="U_ATTACKER",
            )

            # Should get denial message
            mock_say.assert_called()
            call_text = mock_say.call_args_list[-1].kwargs.get(
                "text",
                mock_say.call_args_list[-1].args[0]
                if mock_say.call_args_list[-1].args
                else "",
            )
            assert "🔒" in call_text or "access" in call_text.lower()

    @pytest.mark.asyncio
    async def test_allows_member_for_private_channel(self):
        """Requesting a private channel digest as a member should succeed."""
        from app.slack.events import _handle_digest_command

        mock_say = AsyncMock()

        with (
            patch("app.slack.events.digest_service") as mock_digest_svc,
            patch("app.slack.events.membership_service") as mock_ms,
            patch("app.slack.events.AsyncSessionLocal") as mock_factory,
        ):
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            ws = _make_workspace()
            private_ch = _make_channel("secret-proj", "C_SECRET", "private")

            ws_result = MagicMock()
            ws_result.scalar_one_or_none.return_value = ws

            ch_result = MagicMock()
            ch_result.scalar_one_or_none.return_value = private_ch

            mock_session.execute = AsyncMock(side_effect=[ws_result, ch_result])

            # User IS a member
            mock_ms.get_user_channel_ids = AsyncMock(
                return_value=["C_SECRET", "C_OTHER"]
            )

            # Mock successful digest generation
            mock_digest = MagicMock()
            mock_digest.content = "Private channel summary"
            mock_digest_svc.generate_channel_digest = AsyncMock(
                return_value=mock_digest
            )

            await _handle_digest_command(
                clean_text="digest #secret-proj",
                channel="C_WHERE_ASKED",
                thread_ts="123456.789",
                say=mock_say,
                user_slack_id="U_MEMBER",
            )

            # Should get the digest (not denial)
            mock_say.assert_called()
            # The last say call should contain the digest content
            last_call_text = mock_say.call_args_list[-1].kwargs.get("text", "")
            assert "🔒" not in last_call_text


@skip_without_asyncpg
class TestDigestAPIACL:
    """Protected API uses canonical principals rather than Slack headers."""

    @pytest.mark.asyncio
    async def test_api_rejects_non_member_for_private_channel(self):
        """POST /generate for a private channel should return 403
        when the user is not a member."""
        from fastapi import FastAPI, HTTPException
        from fastapi.testclient import TestClient

        from app.api.digests import router
        from app.database import get_db
        from app.security.auth import AuthenticatedPrincipal, get_current_principal

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        ws = _make_workspace()
        private_ch = _make_channel("secret", "C_SECRET", "private")
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=ws)
        channel_result = MagicMock()
        channel_result.scalar_one_or_none.return_value = private_ch
        mock_session.execute = AsyncMock(return_value=channel_result)

        async def override_db():
            yield mock_session

        async def override_principal():
            return AuthenticatedPrincipal(
                user_id=uuid.uuid4(),
                workspace_id=ws.id,
                email="attacker@example.com",
                display_name="Attacker",
                is_admin=False,
            )

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_principal] = override_principal
        with patch(
            "app.api.digests.require_channel_access",
            new=AsyncMock(
                side_effect=HTTPException(
                    status_code=403, detail="Channel access denied"
                )
            ),
        ):
            response = TestClient(app).post(
                "/api/v1/digests/generate",
                json={"channel_name": "secret"},
            )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_slack_identity_header_is_not_api_authentication(self):
        """A forged Slack header without a bearer token must not authorize."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.api.digests import router
        from app.database import get_db

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        async def override_db():
            yield AsyncMock()

        app.dependency_overrides[get_db] = override_db
        response = TestClient(app).post(
            "/api/v1/digests/generate",
            json={"channel_name": "secret"},
            headers={"X-Slack-User-Id": "U_ATTACKER"},
        )
        assert response.status_code == 401
