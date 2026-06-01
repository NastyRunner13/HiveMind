"""
Agent Session and Agent Message models — stores interactive agent-user conversations.
"""

import uuid

from sqlalchemy import Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.identity import Platform


class AgentSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Conversation session for the AI Agent."""

    __tablename__ = "agent_sessions"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform: Mapped[Platform] = mapped_column(
        Enum(
            Platform,
            name="platform_enum",
            values_callable=lambda values: [value.value for value in values],
            inherit_schema=True,  # Reuses existing platform_enum
        ),
        nullable=False,
        index=True,
    )
    # The external session ID (thread_ts for Slack, conversationId for Teams)
    external_session_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )

    # Relationships
    messages = relationship(
        "AgentMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="AgentMessage.created_at.asc()",
    )

    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "platform",
            "external_session_id",
            name="uq_agent_session_external",
        ),
    )


class AgentMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single message exchanged inside an AgentSession."""

    __tablename__ = "agent_messages"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The role: human, ai, system
    role: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    # Text content of the message
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )

    # Relationships
    session = relationship("AgentSession", back_populates="messages")
