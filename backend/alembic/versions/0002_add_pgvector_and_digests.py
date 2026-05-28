"""Add pgvector extension, document_chunks, and digests tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-25

Adds:
- pgvector extension for vector similarity search
- document_chunks: vector-embedded text chunks with ACL metadata
- digests: generated channel/workspace summaries
- HNSW index on embedding column for fast similarity search

Note: Vector dimensions are set to 384 for local sentence-transformers
(all-MiniLM-L6-v2). If using OpenAI embeddings (1536 dims), update the
vector(384) to vector(1536) before running the migration.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ── Configure dimensions here ────────────────────────────────────
# 384 = all-MiniLM-L6-v2 (local, free)
# 1536 = text-embedding-3-small (OpenAI, paid)
EMBEDDING_DIMENSIONS = 384


def upgrade() -> None:
    # ── Enable pgvector extension ────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── Enums ────────────────────────────────────────────────────
    source_type_enum = postgresql.ENUM(
        "message",
        "file",
        "channel_summary",
        name="source_type_enum",
        create_type=True,
    )
    acl_type_enum = postgresql.ENUM(
        "public",
        "channel",
        "role",
        "explicit",
        name="acl_type_enum",
        create_type=True,
    )
    confidentiality_enum = postgresql.ENUM(
        "public",
        "internal",
        "confidential",
        name="confidentiality_enum",
        create_type=True,
    )
    digest_type_enum = postgresql.ENUM(
        "daily",
        "weekly",
        "on_demand",
        name="digest_type_enum",
        create_type=True,
    )

    # ── Document Chunks (Knowledge Fabric) ───────────────────────
    op.create_table(
        "document_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_type", source_type_enum, nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        # ACL metadata
        sa.Column("acl_type", acl_type_enum, nullable=False, server_default="public"),
        sa.Column(
            "allowed_channel_ids",
            postgresql.ARRAY(sa.String(32)),
            nullable=True,
        ),
        sa.Column(
            "allowed_user_ids",
            postgresql.ARRAY(sa.String(32)),
            nullable=True,
        ),
        sa.Column("source_channel_id", sa.String(32), nullable=True),
        sa.Column(
            "confidentiality",
            confidentiality_enum,
            nullable=False,
            server_default="internal",
        ),
        sa.Column("acl_last_verified", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_document_chunks_workspace_id", "document_chunks", ["workspace_id"]
    )
    op.create_index("ix_document_chunks_source_id", "document_chunks", ["source_id"])
    op.create_index(
        "ix_document_chunks_source_channel_id",
        "document_chunks",
        ["source_channel_id"],
    )

    # Add the vector column using raw SQL (pgvector specific syntax)
    op.execute(
        f"ALTER TABLE document_chunks ADD COLUMN embedding vector({EMBEDDING_DIMENSIONS})"
    )

    # Create HNSW index for fast approximate nearest neighbor search
    op.execute(
        "CREATE INDEX ix_document_chunks_embedding_hnsw "
        "ON document_chunks "
        "USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )

    # ── Digests ──────────────────────────────────────────────────
    op.create_table(
        "digests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "channel_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("channels.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "digest_type", digest_type_enum, nullable=False, server_default="daily"
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("time_range_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("time_range_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "generated_by", sa.String(128), nullable=False, server_default="unknown"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_digests_workspace_id", "digests", ["workspace_id"])
    op.create_index("ix_digests_channel_id", "digests", ["channel_id"])


def downgrade() -> None:
    op.drop_table("digests")
    op.drop_table("document_chunks")

    # Drop enums
    op.execute("DROP TYPE IF EXISTS digest_type_enum")
    op.execute("DROP TYPE IF EXISTS confidentiality_enum")
    op.execute("DROP TYPE IF EXISTS acl_type_enum")
    op.execute("DROP TYPE IF EXISTS source_type_enum")

    # Drop extension
    op.execute("DROP EXTENSION IF EXISTS vector")
