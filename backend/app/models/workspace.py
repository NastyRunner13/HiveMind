"""
Workspace model — represents a connected Slack workspace (team).

In Slack's terminology, a "workspace" is a team/organization.
This is the top-level entity that all channels, users, messages,
and files belong to. Designed for future multi-tenancy.
"""

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Workspace(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspaces"

    # Slack's team ID (e.g., "T024BE7LD") — unique per workspace
    slack_team_id: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, index=True
    )

    # Human-readable workspace name
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Slack domain (e.g., "mycompany" for mycompany.slack.com)
    domain: Mapped[str] = mapped_column(String(255), nullable=True)

    # Whether this workspace is actively being monitored
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    # ── Relationships ────────────────────────────────────────────
    channels = relationship(
        "Channel", back_populates="workspace", lazy="selectin"
    )
    users = relationship(
        "SlackUser", back_populates="workspace", lazy="selectin"
    )
    messages = relationship("Message", back_populates="workspace")
    files = relationship("FileMetadata", back_populates="workspace")

    def __repr__(self) -> str:
        return f"<Workspace name={self.name!r} team_id={self.slack_team_id!r}>"
