"""Canonical identities and platform-integration mappings."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Platform(str, enum.Enum):
    """Supported external platform families."""

    SLACK = "slack"
    TEAMS = "teams"
    DISCORD = "discord"
    EMAIL = "email"
    JIRA = "jira"
    NOTION = "notion"


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Canonical person record shared across external platforms."""

    __tablename__ = "users"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    workspace = relationship("Workspace", back_populates="canonical_users")
    platform_mappings = relationship(
        "UserPlatformMapping", back_populates="user", cascade="all, delete-orphan"
    )
    auth_identities = relationship(
        "AuthIdentity", back_populates="user", cascade="all, delete-orphan"
    )


class WorkspaceIntegration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A platform tenant/account connected to one HiveMind workspace."""

    __tablename__ = "workspace_integrations"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform: Mapped[Platform] = mapped_column(
        Enum(
            Platform,
            name="platform_enum",
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
        index=True,
    )
    external_workspace_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    workspace = relationship("Workspace", back_populates="integrations")
    user_mappings = relationship(
        "UserPlatformMapping",
        back_populates="workspace_integration",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "platform",
            "external_workspace_id",
            name="uq_workspace_integration_external",
        ),
    )


class UserPlatformMapping(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Links one canonical user to an account on an external platform."""

    __tablename__ = "user_platform_mappings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_integration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspace_integrations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform: Mapped[Platform] = mapped_column(
        Enum(
            Platform,
            name="platform_enum",
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
        index=True,
    )
    external_user_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    external_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user = relationship("User", back_populates="platform_mappings")
    workspace_integration = relationship(
        "WorkspaceIntegration", back_populates="user_mappings"
    )

    __table_args__ = (
        UniqueConstraint(
            "workspace_integration_id",
            "external_user_id",
            name="uq_user_platform_external",
        ),
    )


class AuthIdentity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Verified external authentication subject mapped to a canonical user."""

    __tablename__ = "auth_identities"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    issuer: Mapped[str] = mapped_column(String(512), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_authenticated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user = relationship("User", back_populates="auth_identities")

    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_auth_identity_subject"),
    )
