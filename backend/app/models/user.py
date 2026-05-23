"""
SlackUser model — represents a user in a connected Slack workspace.

This is the HiveMind-side record of a Slack user. It stores profile
info needed for display, attribution, and future RBAC role mapping.
Note: This is NOT the HiveMind user account — that comes later when
we add authentication. This is purely a mirror of Slack user data.
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SlackUser(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "slack_users"

    # ── Foreign Keys ─────────────────────────────────────────────
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Slack Identifiers ────────────────────────────────────────
    # Slack's user ID (e.g., "U024BE7LH") — unique within a workspace
    slack_user_id: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )

    # ── Profile Info ─────────────────────────────────────────────
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    real_name: Mapped[str] = mapped_column(
        String(255), nullable=False, default=""
    )
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ── Flags ────────────────────────────────────────────────────
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    is_owner: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    # ── Extra Profile ────────────────────────────────────────────
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ── Relationships ────────────────────────────────────────────
    workspace = relationship("Workspace", back_populates="users")
    messages = relationship("Message", back_populates="sender")
    shared_files = relationship("FileMetadata", back_populates="shared_by")

    # ── Constraints ──────────────────────────────────────────────
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "slack_user_id",
            name="uq_user_workspace_slack_id",
        ),
    )

    def __repr__(self) -> str:
        return f"<SlackUser name={self.display_name!r} slack_id={self.slack_user_id!r}>"
