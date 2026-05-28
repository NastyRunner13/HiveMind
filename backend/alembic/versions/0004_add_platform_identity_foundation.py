"""Add canonical platform identities and normalized compatibility columns.

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    platform_enum = postgresql.ENUM(
        "slack",
        "teams",
        "discord",
        "email",
        "jira",
        "notion",
        name="platform_enum",
        create_type=True,
    )
    platform_enum.create(op.get_bind(), checkfirst=True)
    platform_column_enum = postgresql.ENUM(
        "slack",
        "teams",
        "discord",
        "email",
        "jira",
        "notion",
        name="platform_enum",
        create_type=False,
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        *_timestamps(),
    )
    op.create_index("ix_users_workspace_id", "users", ["workspace_id"])
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "workspace_integrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("platform", platform_column_enum, nullable=False),
        sa.Column("external_workspace_id", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        *_timestamps(),
        sa.UniqueConstraint(
            "workspace_id",
            "platform",
            "external_workspace_id",
            name="uq_workspace_integration_external",
        ),
    )
    op.create_index(
        "ix_workspace_integrations_workspace_id",
        "workspace_integrations",
        ["workspace_id"],
    )
    op.create_index(
        "ix_workspace_integrations_platform", "workspace_integrations", ["platform"]
    )
    op.create_index(
        "ix_workspace_integrations_external_workspace_id",
        "workspace_integrations",
        ["external_workspace_id"],
    )

    op.create_table(
        "user_platform_mappings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_integration_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspace_integrations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("platform", platform_column_enum, nullable=False),
        sa.Column("external_user_id", sa.String(255), nullable=False),
        sa.Column("external_email", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        *_timestamps(),
        sa.UniqueConstraint(
            "workspace_integration_id",
            "external_user_id",
            name="uq_user_platform_external",
        ),
    )
    op.create_index(
        "ix_user_platform_mappings_user_id", "user_platform_mappings", ["user_id"]
    )
    op.create_index(
        "ix_user_platform_mappings_workspace_integration_id",
        "user_platform_mappings",
        ["workspace_integration_id"],
    )
    op.create_index(
        "ix_user_platform_mappings_external_user_id",
        "user_platform_mappings",
        ["external_user_id"],
    )

    op.create_table(
        "auth_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("issuer", sa.String(512), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("last_authenticated_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("issuer", "subject", name="uq_auth_identity_subject"),
    )
    op.create_index("ix_auth_identities_user_id", "auth_identities", ["user_id"])
    op.create_index("ix_auth_identities_tenant_id", "auth_identities", ["tenant_id"])

    op.add_column(
        "channels",
        sa.Column(
            "workspace_integration_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspace_integrations.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "channels",
        sa.Column(
            "platform", platform_column_enum, nullable=False, server_default="slack"
        ),
    )
    op.add_column(
        "channels", sa.Column("external_channel_id", sa.String(255), nullable=True)
    )
    op.create_index(
        "ix_channels_workspace_integration_id", "channels", ["workspace_integration_id"]
    )
    op.create_index(
        "ix_channels_external_channel_id", "channels", ["external_channel_id"]
    )
    op.create_unique_constraint(
        "uq_channel_integration_external_id",
        "channels",
        ["workspace_integration_id", "external_channel_id"],
    )

    op.add_column(
        "messages",
        sa.Column(
            "workspace_integration_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspace_integrations.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "messages",
        sa.Column(
            "platform", platform_column_enum, nullable=False, server_default="slack"
        ),
    )
    op.add_column(
        "messages", sa.Column("external_message_id", sa.String(255), nullable=True)
    )
    op.add_column(
        "messages", sa.Column("external_thread_id", sa.String(255), nullable=True)
    )
    op.add_column(
        "messages", sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        "ix_messages_workspace_integration_id", "messages", ["workspace_integration_id"]
    )
    op.create_index(
        "ix_messages_external_message_id", "messages", ["external_message_id"]
    )
    op.create_index(
        "ix_messages_external_thread_id", "messages", ["external_thread_id"]
    )
    op.create_index("ix_messages_sent_at", "messages", ["sent_at"])
    op.create_unique_constraint(
        "uq_message_integration_channel_external_id",
        "messages",
        ["workspace_integration_id", "channel_id", "external_message_id"],
    )

    op.add_column(
        "file_metadata",
        sa.Column(
            "workspace_integration_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspace_integrations.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "file_metadata",
        sa.Column(
            "platform", platform_column_enum, nullable=False, server_default="slack"
        ),
    )
    op.add_column(
        "file_metadata", sa.Column("external_file_id", sa.String(255), nullable=True)
    )
    op.add_column(
        "file_metadata",
        sa.Column("external_created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_file_metadata_workspace_integration_id",
        "file_metadata",
        ["workspace_integration_id"],
    )
    op.create_index(
        "ix_file_metadata_external_file_id", "file_metadata", ["external_file_id"]
    )
    op.create_unique_constraint(
        "uq_file_integration_external_id",
        "file_metadata",
        ["workspace_integration_id", "external_file_id"],
    )

    op.add_column(
        "channel_memberships",
        sa.Column(
            "canonical_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_channel_memberships_canonical_user_id",
        "channel_memberships",
        ["canonical_user_id"],
    )

    op.add_column(
        "document_chunks",
        sa.Column(
            "allowed_channel_uuids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=True,
        ),
    )
    op.add_column(
        "document_chunks",
        sa.Column(
            "allowed_user_uuids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=True,
        ),
    )
    op.add_column(
        "document_chunks",
        sa.Column("source_channel_uuid", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_document_chunks_source_channel_uuid",
        "document_chunks",
        ["source_channel_uuid"],
    )

    # Backfill existing Slack-backed data without removing compatibility fields.
    op.execute(
        """
        INSERT INTO workspace_integrations
            (id, workspace_id, platform, external_workspace_id, display_name, is_active, created_at, updated_at)
        SELECT id, id, 'slack', slack_team_id, name, is_active, created_at, updated_at
        FROM workspaces
        ON CONFLICT (workspace_id, platform, external_workspace_id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO users
            (id, workspace_id, email, display_name, is_admin, is_active, created_at, updated_at)
        SELECT id, workspace_id, email, display_name, is_admin, is_active, created_at, updated_at
        FROM slack_users
        ON CONFLICT (id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO user_platform_mappings
            (id, user_id, workspace_integration_id, platform, external_user_id,
             external_email, is_active, created_at, updated_at)
        SELECT su.id, su.id, wi.id, 'slack', su.slack_user_id,
               su.email, su.is_active, su.created_at, su.updated_at
        FROM slack_users su
        JOIN workspace_integrations wi
          ON wi.workspace_id = su.workspace_id AND wi.platform = 'slack'
        ON CONFLICT (workspace_integration_id, external_user_id) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE channels c
        SET workspace_integration_id = wi.id,
            external_channel_id = c.slack_channel_id,
            platform = 'slack'
        FROM workspace_integrations wi
        WHERE wi.workspace_id = c.workspace_id AND wi.platform = 'slack'
        """
    )
    op.execute(
        """
        UPDATE messages m
        SET workspace_integration_id = wi.id,
            external_message_id = m.slack_message_ts,
            external_thread_id = m.thread_ts,
            sent_at = m.slack_sent_at,
            platform = 'slack'
        FROM workspace_integrations wi
        WHERE wi.workspace_id = m.workspace_id AND wi.platform = 'slack'
        """
    )
    op.execute(
        """
        UPDATE file_metadata f
        SET workspace_integration_id = wi.id,
            external_file_id = f.slack_file_id,
            external_created_at = f.slack_created_at,
            platform = 'slack'
        FROM workspace_integrations wi
        WHERE wi.workspace_id = f.workspace_id AND wi.platform = 'slack'
        """
    )
    op.execute("UPDATE channel_memberships SET canonical_user_id = user_id")
    op.execute(
        """
        UPDATE document_chunks dc
        SET source_channel_uuid = c.id
        FROM channels c
        WHERE dc.workspace_id = c.workspace_id
          AND dc.source_channel_id = c.slack_channel_id
        """
    )
    op.execute(
        """
        UPDATE document_chunks dc
        SET allowed_channel_uuids = mapped.channel_ids
        FROM (
            SELECT dc_inner.id, array_agg(c.id) AS channel_ids
            FROM document_chunks dc_inner
            JOIN channels c
              ON c.workspace_id = dc_inner.workspace_id
             AND c.slack_channel_id = ANY(dc_inner.allowed_channel_ids)
            GROUP BY dc_inner.id
        ) mapped
        WHERE dc.id = mapped.id
        """
    )
    op.execute(
        """
        UPDATE document_chunks dc
        SET allowed_user_uuids = mapped.user_ids
        FROM (
            SELECT dc_inner.id, array_agg(upm.user_id) AS user_ids
            FROM document_chunks dc_inner
            JOIN user_platform_mappings upm
              ON upm.platform = 'slack'
             AND upm.external_user_id = ANY(dc_inner.allowed_user_ids)
            GROUP BY dc_inner.id
        ) mapped
        WHERE dc.id = mapped.id
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_chunks_source_channel_uuid", table_name="document_chunks"
    )
    op.drop_column("document_chunks", "source_channel_uuid")
    op.drop_column("document_chunks", "allowed_user_uuids")
    op.drop_column("document_chunks", "allowed_channel_uuids")

    op.drop_index(
        "ix_channel_memberships_canonical_user_id", table_name="channel_memberships"
    )
    op.drop_column("channel_memberships", "canonical_user_id")

    op.drop_constraint(
        "uq_file_integration_external_id", "file_metadata", type_="unique"
    )
    op.drop_index("ix_file_metadata_external_file_id", table_name="file_metadata")
    op.drop_index(
        "ix_file_metadata_workspace_integration_id", table_name="file_metadata"
    )
    op.drop_column("file_metadata", "external_created_at")
    op.drop_column("file_metadata", "external_file_id")
    op.drop_column("file_metadata", "platform")
    op.drop_column("file_metadata", "workspace_integration_id")

    op.drop_constraint(
        "uq_message_integration_channel_external_id", "messages", type_="unique"
    )
    op.drop_index("ix_messages_sent_at", table_name="messages")
    op.drop_index("ix_messages_external_thread_id", table_name="messages")
    op.drop_index("ix_messages_external_message_id", table_name="messages")
    op.drop_index("ix_messages_workspace_integration_id", table_name="messages")
    op.drop_column("messages", "sent_at")
    op.drop_column("messages", "external_thread_id")
    op.drop_column("messages", "external_message_id")
    op.drop_column("messages", "platform")
    op.drop_column("messages", "workspace_integration_id")

    op.drop_constraint("uq_channel_integration_external_id", "channels", type_="unique")
    op.drop_index("ix_channels_external_channel_id", table_name="channels")
    op.drop_index("ix_channels_workspace_integration_id", table_name="channels")
    op.drop_column("channels", "external_channel_id")
    op.drop_column("channels", "platform")
    op.drop_column("channels", "workspace_integration_id")

    op.drop_table("auth_identities")
    op.drop_table("user_platform_mappings")
    op.drop_table("workspace_integrations")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS platform_enum")
