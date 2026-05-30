"""Add source metadata to document_chunks.

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "document_chunks",
        sa.Column("source_created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("source_author_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("source_author_external_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("source_thread_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("source_permalink", sa.String(2048), nullable=True),
    )

    op.create_index(
        "ix_document_chunks_source_created_at",
        "document_chunks",
        ["source_created_at"],
    )
    op.create_index(
        "ix_document_chunks_source_author_id",
        "document_chunks",
        ["source_author_id"],
    )

    op.execute(
        """
        UPDATE document_chunks dc
        SET source_created_at = COALESCE(m.sent_at, m.slack_sent_at),
            source_updated_at = m.updated_at,
            source_author_id = m.sender_id,
            source_author_external_id = su.slack_user_id,
            source_thread_id = COALESCE(m.thread_ts, m.external_thread_id)
        FROM messages m
        LEFT JOIN slack_users su ON su.id = m.sender_id
        WHERE dc.source_type = 'message'
          AND dc.source_id = m.id
        """
    )
    op.execute(
        """
        UPDATE document_chunks dc
        SET source_created_at = COALESCE(
                f.external_created_at,
                f.slack_created_at,
                f.created_at
            ),
            source_updated_at = f.updated_at,
            source_author_id = f.shared_by_id,
            source_author_external_id = su.slack_user_id,
            source_permalink = f.permalink
        FROM file_metadata f
        LEFT JOIN slack_users su ON su.id = f.shared_by_id
        WHERE dc.source_type = 'file'
          AND dc.source_id = f.id
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_chunks_source_author_id", table_name="document_chunks"
    )
    op.drop_index(
        "ix_document_chunks_source_created_at", table_name="document_chunks"
    )
    op.drop_column("document_chunks", "source_permalink")
    op.drop_column("document_chunks", "source_thread_id")
    op.drop_column("document_chunks", "source_author_external_id")
    op.drop_column("document_chunks", "source_author_id")
    op.drop_column("document_chunks", "source_updated_at")
    op.drop_column("document_chunks", "source_created_at")
