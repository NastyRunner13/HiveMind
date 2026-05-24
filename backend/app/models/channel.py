"""
Channel model — represents a Slack channel (public, private, DM, or group DM).

Channels are the primary context boundary for messages and files.
The channel_type is critical for future RBAC — private channels and DMs
have different access control rules than public channels.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ChannelType(str, enum.Enum):
    """Slack channel types — drives RBAC behavior."""

    PUBLIC = "public"
    PRIVATE = "private"
    DM = "dm"
    GROUP_DM = "group_dm"


class Channel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "channels"

    # ── Foreign Keys ─────────────────────────────────────────────
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Slack Identifiers ────────────────────────────────────────
    # Slack's channel ID (e.g., "C024BE91L") — unique within a workspace
    slack_channel_id: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )

    # ── Channel Info ─────────────────────────────────────────────
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    channel_type: Mapped[ChannelType] = mapped_column(
        Enum(
            ChannelType,
            name="channel_type_enum",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=ChannelType.PUBLIC,
    )

    topic: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    purpose: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    member_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # When we last synced message history for this channel
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Relationships ────────────────────────────────────────────
    workspace = relationship("Workspace", back_populates="channels")
    messages = relationship(
        "Message", back_populates="channel", cascade="all, delete-orphan"
    )
    files = relationship("FileMetadata", back_populates="channel")

    # ── Constraints ──────────────────────────────────────────────
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "slack_channel_id",
            name="uq_channel_workspace_slack_id",
        ),
    )

    def __repr__(self) -> str:
        return f"<Channel name={self.name!r} type={self.channel_type.value!r}>"
