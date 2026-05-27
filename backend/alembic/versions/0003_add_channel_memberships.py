"""Add channel_memberships table

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-27

Adds:
- channel_memberships table: tracks which users belong to which channels
- This is the foundation for server-derived ACL enforcement
- Denormalized slack_channel_id and slack_user_id for fast ACL lookups
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "channel_memberships",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "channel_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("slack_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "slack_channel_id",
            sa.String(32),
            nullable=False,
        ),
        sa.Column(
            "slack_user_id",
            sa.String(32),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            nullable=True,
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
        sa.UniqueConstraint(
            "workspace_id",
            "channel_id",
            "user_id",
            name="uq_membership_workspace_channel_user",
        ),
    )

    # Indexes for fast ACL lookups
    op.create_index(
        "ix_channel_memberships_workspace_id",
        "channel_memberships",
        ["workspace_id"],
    )
    op.create_index(
        "ix_channel_memberships_channel_id",
        "channel_memberships",
        ["channel_id"],
    )
    op.create_index(
        "ix_channel_memberships_user_id",
        "channel_memberships",
        ["user_id"],
    )
    # Primary lookup path: "which channels can this Slack user see?"
    op.create_index(
        "ix_channel_memberships_slack_user_id",
        "channel_memberships",
        ["slack_user_id"],
    )
    op.create_index(
        "ix_channel_memberships_slack_channel_id",
        "channel_memberships",
        ["slack_channel_id"],
    )


def downgrade() -> None:
    op.drop_table("channel_memberships")
