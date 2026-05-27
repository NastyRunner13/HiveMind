"""
Digest model — stores generated channel and workspace summaries.

Digests are auto-generated daily (or on-demand) summaries of channel
activity. They capture key discussions, decisions, action items, and
file shares — providing the "morning briefing" feature from the v3 concept.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DigestType(str, enum.Enum):
    """Type of digest."""

    DAILY = "daily"
    WEEKLY = "weekly"
    ON_DEMAND = "on_demand"


class Digest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A generated summary digest for a channel or workspace."""

    __tablename__ = "digests"

    # ── References ───────────────────────────────────────────────
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Null = workspace-level digest (aggregated across channels)
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channels.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ── Digest Content ───────────────────────────────────────────
    digest_type: Mapped[DigestType] = mapped_column(
        Enum(
            DigestType,
            name="digest_type_enum",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=DigestType.DAILY,
    )

    content: Mapped[str] = mapped_column(Text, nullable=False)

    # ── Metadata ─────────────────────────────────────────────────
    message_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    time_range_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    time_range_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # Which LLM model generated this digest
    generated_by: Mapped[str] = mapped_column(
        String(128), nullable=False, default="unknown"
    )

    # ── Relationships ────────────────────────────────────────────
    workspace = relationship("Workspace")
    channel = relationship("Channel")

    def __repr__(self) -> str:
        return (
            f"<Digest type={self.digest_type.value!r} "
            f"messages={self.message_count}>"
        )
