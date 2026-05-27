"""
DocumentChunk model — vector-embedded chunks for the Knowledge Fabric.

This is the core storage for HiveMind's semantic search. Messages and
file content are chunked, embedded, and stored here with ACL metadata
for permission-aware retrieval.

Design decisions:
- Uses pgvector for embeddings (co-located with relational data)
- ACL metadata is stored alongside each chunk for DB-level filtering
- Source attribution is preserved for generating citations
- Embedding dimensions are a SCHEMA-LEVEL decision: the vector(N) column
  size is set in the Alembic migration (0002) and must match
  settings.embedding_dimensions. Changing providers (e.g., local→openai)
  requires a new migration — see config.py for validation details.

Current defaults:
- local: sentence-transformers (all-MiniLM-L6-v2) → 384 dimensions
- openai: text-embedding-3-small → 1536 dimensions (requires migration)
"""

import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.config import get_settings
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SourceType(str, enum.Enum):
    """What kind of content this chunk came from."""

    MESSAGE = "message"
    FILE = "file"
    CHANNEL_SUMMARY = "channel_summary"


class ACLType(str, enum.Enum):
    """Access control type for the chunk."""

    PUBLIC = "public"  # Anyone in the org can see
    CHANNEL = "channel"  # Only channel members
    ROLE = "role"  # Role-based (admin, lead, etc.)
    EXPLICIT = "explicit"  # Specific user IDs only


class Confidentiality(str, enum.Enum):
    """Confidentiality level of the content."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"


settings = get_settings()


class DocumentChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    A vector-embedded chunk of text from a message or file.

    Each chunk carries its own ACL metadata so that vector search
    can filter at the database level — never returning chunks the
    requesting user shouldn't see.
    """

    __tablename__ = "document_chunks"

    # ── Source Reference ─────────────────────────────────────────
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    source_type: Mapped[SourceType] = mapped_column(
        Enum(
            SourceType,
            name="source_type_enum",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )

    # UUID of the source record (message.id or file_metadata.id)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    chunk_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    # ── Content ──────────────────────────────────────────────────
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Vector embedding — dimensions configured via settings
    embedding = mapped_column(
        Vector(settings.embedding_dimensions),
        nullable=True,  # Null until embedding is generated
    )

    token_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    # ── ACL Metadata ─────────────────────────────────────────────
    # These fields enable DB-level filtering in vector search queries
    acl_type: Mapped[ACLType] = mapped_column(
        Enum(
            ACLType,
            name="acl_type_enum",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=ACLType.PUBLIC,
    )

    # Slack channel IDs that grant access to this chunk
    allowed_channel_ids: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(32)),
        nullable=True,
    )

    # Slack user IDs with explicit access (DMs, private shares)
    allowed_user_ids: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(32)),
        nullable=True,
    )

    # The channel this content originated from (for membership checks)
    source_channel_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True
    )

    confidentiality: Mapped[Confidentiality] = mapped_column(
        Enum(
            Confidentiality,
            name="confidentiality_enum",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=Confidentiality.INTERNAL,
    )

    # When the ACL was last verified against the source system
    acl_last_verified: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        preview = self.content[:50] + "..." if len(self.content) > 50 else self.content
        return (
            f"<DocumentChunk source={self.source_type.value!r} "
            f"index={self.chunk_index} preview={preview!r}>"
        )
