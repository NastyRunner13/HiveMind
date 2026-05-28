"""
FileMetadata model — the Metadata Index from the Knowledge Fabric.

This is the "lazy loading" design from the HiveMind concept:
we store ONLY metadata about files, not the file content itself.
Content is fetched on-demand when a user asks a question that
requires it (future RAG pipeline).

Metadata includes: who shared it, where, when, file type, size.
This enables file search, activity tracking, and context building
without downloading or storing any actual file content.
"""

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
from app.models.identity import Platform


class FileMetadata(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "file_metadata"

    # ── Foreign Keys ─────────────────────────────────────────────
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channels.id", ondelete="SET NULL"),
        nullable=True,  # File might be shared in multiple channels
        index=True,
    )
    shared_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("slack_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    workspace_integration_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspace_integrations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    platform: Mapped[Platform] = mapped_column(
        Enum(
            Platform,
            name="platform_enum",
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
        default=Platform.SLACK,
    )
    external_file_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )

    # ── Slack Identifiers ────────────────────────────────────────
    slack_file_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    # ── File Info ────────────────────────────────────────────────
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    filetype: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    mimetype: Mapped[str] = mapped_column(
        String(255), nullable=False, default="application/octet-stream"
    )
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── URLs ─────────────────────────────────────────────────────
    # Slack's private download URL (requires authentication)
    url_private: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    # Slack permalink for linking back to the file
    permalink: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    # ── Sharing Info ─────────────────────────────────────────────
    shares_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_external: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # When the file was created/uploaded in Slack
    slack_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    external_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Relationships ────────────────────────────────────────────
    workspace = relationship("Workspace", back_populates="files")
    channel = relationship("Channel", back_populates="files")
    shared_by = relationship("SlackUser", back_populates="shared_files")
    workspace_integration = relationship("WorkspaceIntegration")

    # ── Constraints ──────────────────────────────────────────────
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "slack_file_id",
            name="uq_file_workspace_slack_id",
        ),
        UniqueConstraint(
            "workspace_integration_id",
            "external_file_id",
            name="uq_file_integration_external_id",
        ),
    )

    @property
    def is_image(self) -> bool:
        return self.mimetype.startswith("image/")

    @property
    def is_document(self) -> bool:
        doc_types = {"pdf", "doc", "docx", "txt", "md", "rtf", "odt"}
        return self.filetype.lower() in doc_types

    def __repr__(self) -> str:
        return (
            f"<FileMetadata filename={self.filename!r} "
            f"type={self.filetype!r} size={self.size_bytes}>"
        )
