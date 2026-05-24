"""
Message model — stores ingested Slack messages.

This is the core data flowing into HiveMind. Every message from
channels the bot is in gets stored here. Thread structure is
preserved via thread_ts → parent message linkage.

Key design decisions:
- slack_message_ts is Slack's unique message ID (timestamp string)
- Content is stored as-is for now; future: vector embeddings
- reaction_count and reply_count are denormalized for quick access
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
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class MessageType(str, enum.Enum):
    """Message type classification."""

    USER = "user_message"
    BOT = "bot_message"
    SYSTEM = "system"  # channel join/leave, topic change, etc.


class Message(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "messages"

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
    sender_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("slack_users.id", ondelete="SET NULL"),
        nullable=True,  # System messages may not have a sender
        index=True,
    )

    # ── Slack Identifiers ────────────────────────────────────────
    # Slack's message timestamp — unique within a channel, serves as msg ID
    slack_message_ts: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )

    # Parent thread timestamp — if set, this message is a reply
    thread_ts: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # ── Content ──────────────────────────────────────────────────
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")

    message_type: Mapped[MessageType] = mapped_column(
        Enum(MessageType, name="message_type_enum"),
        nullable=False,
        default=MessageType.USER,
    )

    # ── Metadata ─────────────────────────────────────────────────
    has_attachments: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    has_files: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reaction_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reply_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_edited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # When the message was sent in Slack (not when HiveMind ingested it)
    slack_sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # ── Relationships ────────────────────────────────────────────
    workspace = relationship("Workspace", back_populates="messages")
    channel = relationship("Channel", back_populates="messages")
    sender = relationship("SlackUser", back_populates="messages")

    # ── Constraints ──────────────────────────────────────────────
    __table_args__ = (
        # A message is uniquely identified by workspace + channel + timestamp
        UniqueConstraint(
            "workspace_id",
            "channel_id",
            "slack_message_ts",
            name="uq_message_workspace_channel_ts",
        ),
    )

    @property
    def is_thread_reply(self) -> bool:
        """Check if this message is a reply in a thread."""
        return self.thread_ts is not None and self.thread_ts != self.slack_message_ts

    def __repr__(self) -> str:
        preview = self.content[:50] + "..." if len(self.content) > 50 else self.content
        return f"<Message ts={self.slack_message_ts!r} preview={preview!r}>"
