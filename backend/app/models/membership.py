"""
ChannelMembership model — tracks which users belong to which channels.

This is the foundation for ACL enforcement. Without knowing channel
memberships, the system cannot answer "what channels can this user
access?" — and therefore cannot filter vector search results or
scope agent tool responses.

Design decisions:
- Denormalized slack_channel_id and slack_user_id avoid JOINs in the
  hot path (ACL lookup happens on every agent tool call and search)
- is_active flag supports soft-delete for member_left_channel events
- joined_at tracks when the membership was established
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ChannelMembership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    A record linking a user to a channel they are a member of.

    Used for:
    1. Deriving ACL context server-side (which channels can a user see?)
    2. Filtering vector search results at the database level
    3. Scoping agent tool responses to authorized channels
    """

    __tablename__ = "channel_memberships"

    # ── Foreign Keys ─────────────────────────────────────────────
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("slack_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    canonical_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # ── Denormalized Slack IDs (for fast ACL lookups) ────────────
    # These avoid JOINs when resolving "which channels can user X see?"
    slack_channel_id: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )

    slack_user_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    # ── Membership State ─────────────────────────────────────────
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    joined_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Relationships ────────────────────────────────────────────
    workspace = relationship("Workspace")
    channel = relationship("Channel")
    user = relationship("SlackUser")
    canonical_user = relationship("User")

    # ── Constraints ──────────────────────────────────────────────
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "channel_id",
            "user_id",
            name="uq_membership_workspace_channel_user",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ChannelMembership user={self.slack_user_id!r} "
            f"channel={self.slack_channel_id!r} "
            f"active={self.is_active}>"
        )
