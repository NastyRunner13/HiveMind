"""Platform-neutral connector contracts."""

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.models.identity import Platform


@dataclass(frozen=True)
class NormalizedMessage:
    """A connector-produced message before persistence and event publication."""

    platform: Platform
    workspace_integration_id: uuid.UUID
    external_channel_id: str
    external_message_id: str
    text: str
    external_sender_id: str | None = None
    external_thread_id: str | None = None
    external_metadata: dict[str, Any] = field(default_factory=dict)


class BasePlatformConnector(Protocol):
    """Connector operations required by platform-neutral core services."""

    platform: Platform

    async def send_message(self, channel_id: uuid.UUID, text: str) -> None:
        """Send text to an internal channel target."""

    async def fetch_channel_history(
        self, channel_id: uuid.UUID
    ) -> list[NormalizedMessage]:
        """Read platform messages and normalize them for ingestion."""

    async def sync_channels(self) -> dict[str, int]:
        """Synchronize platform channels."""

    async def sync_users(self) -> dict[str, int]:
        """Synchronize platform users."""

    async def sync_memberships(self, workspace_id: uuid.UUID) -> dict[str, int]:
        """Synchronize platform membership records."""

    async def get_user_profile(self, user_id: uuid.UUID) -> dict[str, Any] | None:
        """Fetch a user profile using a canonical user UUID."""
