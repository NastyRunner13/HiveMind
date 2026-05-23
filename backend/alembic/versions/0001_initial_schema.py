"""Initial schema — workspaces, channels, users, messages, file_metadata

Revision ID: 0001
Revises: None
Create Date: 2026-05-23

Creates the five core tables for HiveMind's Slack integration:
- workspaces: Connected Slack workspaces
- channels: Slack channels (public, private, DM, group DM)
- slack_users: Mirrored Slack user profiles
- messages: Ingested messages with thread support
- file_metadata: File metadata index (Knowledge Fabric)
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Enums ────────────────────────────────────────────────────
    channel_type_enum = postgresql.ENUM(
        "public", "private", "dm", "group_dm",
        name="channel_type_enum",
        create_type=True,
    )
    message_type_enum = postgresql.ENUM(
        "user_message", "bot_message", "system",
        name="message_type_enum",
        create_type=True,
    )

    # ── Workspaces ───────────────────────────────────────────────
    op.create_table(
        "workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slack_team_id", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("domain", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
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
    op.create_index("ix_workspaces_slack_team_id", "workspaces", ["slack_team_id"])

    # ── Channels ─────────────────────────────────────────────────
    op.create_table(
        "channels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("slack_channel_id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "channel_type",
            channel_type_enum,
            nullable=False,
            server_default="public",
        ),
        sa.Column("topic", sa.String(2048), nullable=True),
        sa.Column("purpose", sa.String(2048), nullable=True),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("member_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
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
            "workspace_id", "slack_channel_id", name="uq_channel_workspace_slack_id"
        ),
    )
    op.create_index("ix_channels_workspace_id", "channels", ["workspace_id"])
    op.create_index("ix_channels_slack_channel_id", "channels", ["slack_channel_id"])

    # ── Slack Users ──────────────────────────────────────────────
    op.create_table(
        "slack_users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("slack_user_id", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("real_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("is_bot", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_owner", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("avatar_url", sa.String(1024), nullable=True),
        sa.Column("timezone", sa.String(64), nullable=True),
        sa.Column("status_text", sa.String(255), nullable=True),
        sa.Column("title", sa.String(255), nullable=True),
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
            "workspace_id", "slack_user_id", name="uq_user_workspace_slack_id"
        ),
    )
    op.create_index("ix_slack_users_workspace_id", "slack_users", ["workspace_id"])
    op.create_index("ix_slack_users_slack_user_id", "slack_users", ["slack_user_id"])

    # ── Messages ─────────────────────────────────────────────────
    op.create_table(
        "messages",
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
            sa.ForeignKey("channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sender_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("slack_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("slack_message_ts", sa.String(64), nullable=False),
        sa.Column("thread_ts", sa.String(64), nullable=True),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "message_type",
            message_type_enum,
            nullable=False,
            server_default="user_message",
        ),
        sa.Column(
            "has_attachments", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("has_files", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("reaction_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reply_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_edited", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("slack_sent_at", sa.DateTime(timezone=True), nullable=False),
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
            "slack_message_ts",
            name="uq_message_workspace_channel_ts",
        ),
    )
    op.create_index("ix_messages_workspace_id", "messages", ["workspace_id"])
    op.create_index("ix_messages_channel_id", "messages", ["channel_id"])
    op.create_index("ix_messages_sender_id", "messages", ["sender_id"])
    op.create_index("ix_messages_slack_message_ts", "messages", ["slack_message_ts"])
    op.create_index("ix_messages_thread_ts", "messages", ["thread_ts"])

    # ── File Metadata ────────────────────────────────────────────
    op.create_table(
        "file_metadata",
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
            "shared_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("slack_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("slack_file_id", sa.String(32), nullable=False),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("title", sa.String(512), nullable=True),
        sa.Column(
            "filetype", sa.String(64), nullable=False, server_default="unknown"
        ),
        sa.Column(
            "mimetype",
            sa.String(255),
            nullable=False,
            server_default="application/octet-stream",
        ),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("url_private", sa.String(2048), nullable=True),
        sa.Column("permalink", sa.String(2048), nullable=True),
        sa.Column("shares_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_external", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("slack_created_at", sa.DateTime(timezone=True), nullable=True),
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
            "workspace_id", "slack_file_id", name="uq_file_workspace_slack_id"
        ),
    )
    op.create_index("ix_file_metadata_workspace_id", "file_metadata", ["workspace_id"])
    op.create_index("ix_file_metadata_channel_id", "file_metadata", ["channel_id"])
    op.create_index("ix_file_metadata_shared_by_id", "file_metadata", ["shared_by_id"])
    op.create_index(
        "ix_file_metadata_slack_file_id", "file_metadata", ["slack_file_id"]
    )


def downgrade() -> None:
    op.drop_table("file_metadata")
    op.drop_table("messages")
    op.drop_table("slack_users")
    op.drop_table("channels")
    op.drop_table("workspaces")

    # Drop enums
    op.execute("DROP TYPE IF EXISTS message_type_enum")
    op.execute("DROP TYPE IF EXISTS channel_type_enum")
