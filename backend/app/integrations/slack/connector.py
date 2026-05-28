"""Adapter for Slack operations behind the platform connector boundary."""

import uuid
from typing import TYPE_CHECKING

from slack_sdk.web.async_client import AsyncWebClient
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.channel import Channel
from app.models.identity import Platform
from app.services.membership_service import membership_service

if TYPE_CHECKING:
    from app.integrations.base import NormalizedMessage


class SlackConnector:
    """Slack outbound and synchronization adapter."""

    platform = Platform.SLACK

    def __init__(self, client: AsyncWebClient):
        self.client = client

    async def send_message(self, channel_id: uuid.UUID, text: str) -> None:
        """Send a message using an internal channel UUID."""
        async with AsyncSessionLocal() as session:
            channel = await session.get(Channel, channel_id)
        if not channel or channel.platform != Platform.SLACK:
            raise ValueError("Slack channel target not found")
        external_id = channel.external_channel_id or channel.slack_channel_id
        await self.send_external_message(external_id, text)

    async def send_external_message(self, external_channel_id: str, text: str) -> None:
        """Send to an existing Slack ID during the compatibility period."""
        await self.client.chat_postMessage(
            channel=external_channel_id,
            text=text,
            unfurl_links=False,
        )

    async def fetch_channel_history(
        self, channel_id: uuid.UUID
    ) -> list["NormalizedMessage"]:
        """Fetch history using the current Slack sync implementation.

        Returns normalized messages suitable for platform-neutral ingestion.
        Also triggers the legacy sync path to persist data via the existing
        ingestion pipeline.
        """
        from app.integrations.base import NormalizedMessage
        from app.models.identity import WorkspaceIntegration
        from app.slack.sync import sync_channel_history

        async with AsyncSessionLocal() as session:
            channel = await session.get(Channel, channel_id)
            if not channel or channel.platform != Platform.SLACK:
                raise ValueError("Slack channel target not found")

            # Resolve workspace_integration_id for normalization
            wi_result = await session.execute(
                select(WorkspaceIntegration.id).where(
                    WorkspaceIntegration.workspace_id == channel.workspace_id,
                    WorkspaceIntegration.platform == Platform.SLACK,
                    WorkspaceIntegration.is_active.is_(True),
                )
            )
            wi_id = wi_result.scalar_one_or_none()

        external_id = channel.external_channel_id or channel.slack_channel_id

        # Persist via the legacy sync path
        await sync_channel_history(self.client, external_id)

        # Fetch raw messages from Slack API for normalization
        normalized: list[NormalizedMessage] = []
        if not wi_id:
            return normalized

        try:
            response = await self.client.conversations_history(
                channel=external_id, limit=100
            )
            if response.get("ok"):
                for msg in response.get("messages", []):
                    if msg.get("subtype") in ("channel_join", "channel_leave"):
                        continue
                    normalized.append(
                        NormalizedMessage(
                            platform=Platform.SLACK,
                            workspace_integration_id=wi_id,
                            external_channel_id=external_id,
                            external_message_id=msg.get("ts", ""),
                            text=msg.get("text", ""),
                            external_sender_id=msg.get("user"),
                            external_thread_id=msg.get("thread_ts"),
                        )
                    )
        except Exception:
            # If the API call fails, return whatever we could gather
            pass

        return normalized

    async def sync_channels(self) -> dict[str, int]:
        """Delegate channel synchronization to Slack synchronization."""
        from app.slack.sync import sync_channels

        return await sync_channels(self.client)

    async def sync_users(self) -> dict[str, int]:
        """Delegate user synchronization to Slack synchronization."""
        from app.slack.sync import sync_users

        return await sync_users(self.client)

    async def sync_memberships(self, workspace_id: uuid.UUID) -> dict[str, int]:
        """Synchronize Slack memberships into canonical records."""
        return await membership_service.full_sync_all_channels(
            workspace_id, self.client
        )

    async def get_user_profile(self, user_id: uuid.UUID) -> dict | None:
        """Fetch a Slack user profile using a canonical user UUID."""
        from app.models.identity import UserPlatformMapping

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserPlatformMapping.external_user_id).where(
                    UserPlatformMapping.user_id == user_id,
                    UserPlatformMapping.platform == Platform.SLACK,
                    UserPlatformMapping.is_active.is_(True),
                )
            )
            external_id = result.scalar_one_or_none()
            if not external_id:
                return None

        response = await self.client.users_info(user=external_id)
        if response.get("ok"):
            return response.get("user")
        return None
