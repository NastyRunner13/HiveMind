"""Authorization service tests — channel access, member lookups, ACL conditions."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.security.auth import AuthenticatedPrincipal
from app.services.authorization_service import (
    accessible_channel_condition,
    get_member_channel_ids,
    require_channel_access,
)


def _principal(
    user_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    is_admin: bool = False,
    slack_user_id: str | None = None,
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id or uuid.uuid4(),
        workspace_id=workspace_id or uuid.uuid4(),
        email="test@example.com",
        display_name="Test",
        is_admin=is_admin,
        slack_user_id=slack_user_id,
    )


def _channel(
    channel_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    channel_type: str = "public",
):
    ch = MagicMock()
    ch.id = channel_id or uuid.uuid4()
    ch.workspace_id = workspace_id or uuid.uuid4()
    ch.channel_type = MagicMock(value=channel_type)
    # Make channel_type comparison work for ChannelType.PUBLIC check
    from app.models.channel import ChannelType

    ch.channel_type = (
        ChannelType.PUBLIC if channel_type == "public" else ChannelType.PRIVATE
    )
    return ch


class TestGetMemberChannelIds:
    @pytest.mark.asyncio
    async def test_returns_channel_ids_for_canonical_user(self):
        workspace_id = uuid.uuid4()
        ch1, ch2 = uuid.uuid4(), uuid.uuid4()
        principal = _principal(workspace_id=workspace_id)

        session = AsyncMock()
        result = MagicMock()
        result.all.return_value = [(ch1,), (ch2,)]
        session.execute = AsyncMock(return_value=result)

        ids = await get_member_channel_ids(session, principal)
        assert ch1 in ids
        assert ch2 in ids
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_memberships(self):
        principal = _principal()
        session = AsyncMock()
        result = MagicMock()
        result.all.return_value = []
        session.execute = AsyncMock(return_value=result)

        ids = await get_member_channel_ids(session, principal)
        assert ids == []


class TestRequireChannelAccess:
    @pytest.mark.asyncio
    async def test_public_channel_is_accessible(self):
        workspace_id = uuid.uuid4()
        channel = _channel(workspace_id=workspace_id, channel_type="public")
        principal = _principal(workspace_id=workspace_id)

        session = AsyncMock()
        query_result = MagicMock()
        query_result.scalar_one_or_none.return_value = channel
        session.execute = AsyncMock(return_value=query_result)

        result = await require_channel_access(session, principal, channel.id)
        assert result == channel

    @pytest.mark.asyncio
    async def test_private_channel_denied_for_non_member(self):
        workspace_id = uuid.uuid4()
        channel = _channel(workspace_id=workspace_id, channel_type="private")
        principal = _principal(workspace_id=workspace_id)

        session = AsyncMock()
        # First call: channel lookup
        channel_result = MagicMock()
        channel_result.scalar_one_or_none.return_value = channel
        # Second call: membership lookup (returns no memberships)
        member_result = MagicMock()
        member_result.all.return_value = []
        session.execute = AsyncMock(side_effect=[channel_result, member_result])

        with pytest.raises(HTTPException) as error:
            await require_channel_access(session, principal, channel.id)
        assert error.value.status_code == 403

    @pytest.mark.asyncio
    async def test_private_channel_allowed_for_member(self):
        workspace_id = uuid.uuid4()
        channel = _channel(workspace_id=workspace_id, channel_type="private")
        principal = _principal(workspace_id=workspace_id)

        session = AsyncMock()
        # First call: channel lookup
        channel_result = MagicMock()
        channel_result.scalar_one_or_none.return_value = channel
        # Second call: membership lookup (member of this channel)
        member_result = MagicMock()
        member_result.all.return_value = [(channel.id,)]
        session.execute = AsyncMock(side_effect=[channel_result, member_result])

        result = await require_channel_access(session, principal, channel.id)
        assert result == channel

    @pytest.mark.asyncio
    async def test_nonexistent_channel_returns_404(self):
        principal = _principal()
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result)

        with pytest.raises(HTTPException) as error:
            await require_channel_access(session, principal, uuid.uuid4())
        assert error.value.status_code == 404


class TestAccessibleChannelCondition:
    @pytest.mark.asyncio
    async def test_returns_sql_condition(self):
        principal = _principal()
        session = AsyncMock()
        member_result = MagicMock()
        member_result.all.return_value = []
        session.execute = AsyncMock(return_value=member_result)

        condition = await accessible_channel_condition(session, principal)
        # Should return an SQLAlchemy BooleanClauseList (AND condition)
        assert condition is not None
