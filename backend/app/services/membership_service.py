"""
Membership Service — manages channel membership records for ACL enforcement.

This service is the source of truth for "which channels can this user access?"
It provides the server-derived ACL context that replaces client-supplied
channel IDs in the Knowledge API and agent tools.

Data flows in via three paths:
1. Real-time: member_joined_channel / member_left_channel Slack events
2. Bulk sync: During initial setup and periodic refresh from Slack API
3. Daily cron: Safety net full-sync to catch any missed events

All ACL lookups use the denormalized slack_user_id/slack_channel_id columns
to avoid JOINs in the hot path.
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import AsyncSessionLocal
from app.events.bus import EventType, event_bus
from app.events.contracts import normalized_payload
from app.models.channel import Channel
from app.models.identity import Platform, UserPlatformMapping
from app.models.membership import ChannelMembership
from app.models.user import SlackUser
from app.models.workspace import Workspace

logger = logging.getLogger(__name__)


async def _publish_membership_updated(
    *,
    workspace_id: uuid.UUID,
    channel_id: uuid.UUID,
    slack_channel_id: str,
    slack_user_id: str | None = None,
    user_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    source: str,
    stats: dict | None = None,
) -> None:
    """Notify consumers that channel ACLs should be revalidated."""
    metadata = {
        "channel_id": slack_channel_id,
        "user_id": slack_user_id,
        "is_active": is_active,
        "source": source,
    }
    if stats:
        metadata["stats"] = stats

    await event_bus.publish(
        EventType.MEMBERSHIP_UPDATED,
        normalized_payload(
            platform=Platform.SLACK,
            workspace_id=workspace_id,
            workspace_integration_id=None,
            channel_id=channel_id,
            user_id=user_id,
            external_metadata=metadata,
        ),
    )


class MembershipService:
    """
    Manages channel membership records for server-derived ACL context.

    Usage:
        service = MembershipService()

        # Get user's accessible channels (for ACL filtering)
        channel_ids = await service.get_user_channel_ids("U12345")

        # Record a member joining/leaving
        await service.handle_member_joined("U12345", "C67890")
        await service.handle_member_left("U12345", "C67890")
    """

    async def get_user_channel_ids(
        self,
        slack_user_id: str,
        workspace_id: uuid.UUID | None = None,
    ) -> list[str]:
        """
        Get all Slack channel IDs a user is an active member of.

        This is the primary ACL lookup — called on every agent request
        and knowledge search to determine what the user can see.

        Args:
            slack_user_id: The Slack user ID to look up.
            workspace_id: Optional workspace scope.

        Returns:
            List of Slack channel IDs the user is a member of.
        """
        async with AsyncSessionLocal() as session:
            query = select(ChannelMembership.slack_channel_id).where(
                and_(
                    ChannelMembership.slack_user_id == slack_user_id,
                    ChannelMembership.is_active.is_(True),
                )
            )
            if workspace_id:
                query = query.where(ChannelMembership.workspace_id == workspace_id)

            result = await session.execute(query)
            return [row[0] for row in result.all()]

    async def get_user_channel_uuids(
        self,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID | None = None,
    ) -> list[uuid.UUID]:
        """Get all internal channel UUIDs a user is an active member of.

        This is the primary ACL lookup for agent tools, knowledge search,
        and digest scoping. Uses canonical_user_id for platform-neutral
        identity resolution.

        Args:
            user_id: Canonical user UUID (resolved via OIDC/Keycloak or SlackUser lookup).
            workspace_id: Optional workspace scope.

        Returns:
            List of internal channel UUIDs the user is a member of.
        """
        async with AsyncSessionLocal() as session:
            query = select(ChannelMembership.channel_id).where(
                and_(
                    ChannelMembership.canonical_user_id == user_id,
                    ChannelMembership.is_active.is_(True),
                )
            )
            if workspace_id:
                query = query.where(ChannelMembership.workspace_id == workspace_id)

            result = await session.execute(query)
            return [row[0] for row in result.all()]

    async def handle_member_joined(
        self,
        slack_user_id: str,
        slack_channel_id: str,
    ) -> None:
        """
        Handle a member_joined_channel event — add or reactivate membership.

        Uses upsert to handle the case where a user leaves and re-joins
        a channel (reactivates the existing record).

        Args:
            slack_user_id: Slack user ID of the member who joined.
            slack_channel_id: Slack channel ID they joined.
        """
        async with AsyncSessionLocal() as session:
            # Resolve workspace
            workspace_result = await session.execute(
                select(Workspace).where(Workspace.is_active.is_(True)).limit(1)
            )
            workspace = workspace_result.scalar_one_or_none()
            if not workspace:
                logger.warning("No active workspace — cannot record membership")
                return

            # Resolve internal channel ID
            ch_result = await session.execute(
                select(Channel.id).where(
                    Channel.slack_channel_id == slack_channel_id,
                    Channel.workspace_id == workspace.id,
                )
            )
            channel_id = ch_result.scalar_one_or_none()
            if not channel_id:
                logger.debug(
                    f"Channel {slack_channel_id} not found — skipping membership record"
                )
                return

            # Resolve internal user ID
            user_result = await session.execute(
                select(SlackUser.id).where(
                    SlackUser.slack_user_id == slack_user_id,
                    SlackUser.workspace_id == workspace.id,
                )
            )
            user_id = user_result.scalar_one_or_none()
            if not user_id:
                logger.debug(
                    f"User {slack_user_id} not found — skipping membership record"
                )
                return

            # Resolve canonical user ID via platform mapping
            canonical_result = await session.execute(
                select(UserPlatformMapping.user_id).where(
                    UserPlatformMapping.external_user_id == slack_user_id,
                    UserPlatformMapping.platform == Platform.SLACK,
                    UserPlatformMapping.is_active.is_(True),
                )
            )
            canonical_user_id = canonical_result.scalar_one_or_none()

            # Upsert: insert or reactivate on conflict
            stmt = pg_insert(ChannelMembership).values(
                workspace_id=workspace.id,
                channel_id=channel_id,
                user_id=user_id,
                canonical_user_id=canonical_user_id or user_id,
                slack_channel_id=slack_channel_id,
                slack_user_id=slack_user_id,
                is_active=True,
                joined_at=datetime.now(timezone.utc),
            )
            stmt = stmt.on_conflict_do_update(
                constraint="uq_membership_workspace_channel_user",
                set_={
                    "is_active": True,
                    "joined_at": stmt.excluded.joined_at,
                },
            )
            await session.execute(stmt)
            await session.commit()

            await _publish_membership_updated(
                workspace_id=workspace.id,
                channel_id=channel_id,
                slack_channel_id=slack_channel_id,
                slack_user_id=slack_user_id,
                user_id=canonical_user_id or user_id,
                is_active=True,
                source="member_joined_channel",
            )

            logger.info(
                f"Membership recorded: {slack_user_id} joined {slack_channel_id}"
            )

    async def handle_member_left(
        self,
        slack_user_id: str,
        slack_channel_id: str,
    ) -> None:
        """
        Handle a member_left_channel event — deactivate membership.

        Soft-deletes by setting is_active=False rather than removing
        the record, preserving historical membership data.

        Args:
            slack_user_id: Slack user ID of the member who left.
            slack_channel_id: Slack channel ID they left.
        """
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                update(ChannelMembership)
                .where(
                    and_(
                        ChannelMembership.slack_user_id == slack_user_id,
                        ChannelMembership.slack_channel_id == slack_channel_id,
                        ChannelMembership.is_active.is_(True),
                    )
                )
                .values(is_active=False)
                .returning(
                    ChannelMembership.workspace_id,
                    ChannelMembership.channel_id,
                    ChannelMembership.canonical_user_id,
                    ChannelMembership.user_id,
                )
            )
            row = result.one_or_none()
            await session.commit()

            if row is not None:
                await _publish_membership_updated(
                    workspace_id=row[0],
                    channel_id=row[1],
                    slack_channel_id=slack_channel_id,
                    slack_user_id=slack_user_id,
                    user_id=row[2] or row[3],
                    is_active=False,
                    source="member_left_channel",
                )

            logger.info(
                f"Membership deactivated: {slack_user_id} left {slack_channel_id}"
            )

    async def sync_channel_members(
        self,
        slack_channel_id: str,
        member_slack_ids: list[str],
        workspace_id: uuid.UUID,
    ) -> dict:
        """
        Bulk sync members for a single channel from Slack API data.

        This is called during initial sync and periodic refresh.
        It upserts all current members and deactivates any that
        are no longer in the member list.

        Args:
            slack_channel_id: Slack channel ID.
            member_slack_ids: List of Slack user IDs currently in the channel.
            workspace_id: The workspace UUID.

        Returns:
            Summary dict: {added: int, reactivated: int, deactivated: int}
        """
        stats = {"added": 0, "reactivated": 0, "deactivated": 0}

        async with AsyncSessionLocal() as session:
            # Resolve internal channel ID
            ch_result = await session.execute(
                select(Channel.id).where(
                    Channel.slack_channel_id == slack_channel_id,
                    Channel.workspace_id == workspace_id,
                )
            )
            channel_id = ch_result.scalar_one_or_none()
            if not channel_id:
                return stats

            # Get all user mappings in one query
            user_result = await session.execute(
                select(SlackUser.id, SlackUser.slack_user_id).where(
                    SlackUser.workspace_id == workspace_id,
                    SlackUser.slack_user_id.in_(member_slack_ids),
                )
            )
            user_map = {row.slack_user_id: row.id for row in user_result.all()}

            # Resolve canonical user IDs via platform mappings
            canonical_result = await session.execute(
                select(
                    UserPlatformMapping.external_user_id,
                    UserPlatformMapping.user_id,
                ).where(
                    UserPlatformMapping.external_user_id.in_(member_slack_ids),
                    UserPlatformMapping.platform == Platform.SLACK,
                    UserPlatformMapping.is_active.is_(True),
                )
            )
            canonical_map = {
                row.external_user_id: row.user_id for row in canonical_result.all()
            }

            # Upsert each member
            now = datetime.now(timezone.utc)
            for slack_uid in member_slack_ids:
                user_id = user_map.get(slack_uid)
                if not user_id:
                    continue  # User not synced yet — skip

                stmt = pg_insert(ChannelMembership).values(
                    workspace_id=workspace_id,
                    channel_id=channel_id,
                    user_id=user_id,
                    canonical_user_id=canonical_map.get(slack_uid, user_id),
                    slack_channel_id=slack_channel_id,
                    slack_user_id=slack_uid,
                    is_active=True,
                    joined_at=now,
                )
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_membership_workspace_channel_user",
                    set_={
                        "is_active": True,
                    },
                )
                await session.execute(stmt)
                stats["added"] += 1

            # Deactivate members no longer in the channel
            if member_slack_ids:
                deactivated_result = await session.execute(
                    update(ChannelMembership)
                    .where(
                        and_(
                            ChannelMembership.channel_id == channel_id,
                            ChannelMembership.workspace_id == workspace_id,
                            ChannelMembership.is_active.is_(True),
                            ChannelMembership.slack_user_id.notin_(member_slack_ids),
                        )
                    )
                    .values(is_active=False)
                )
                deactivated = deactivated_result.rowcount or 0
                stats["deactivated"] = (
                    deactivated if isinstance(deactivated, int) else 0
                )

            await session.commit()

        await _publish_membership_updated(
            workspace_id=workspace_id,
            channel_id=channel_id,
            slack_channel_id=slack_channel_id,
            is_active=None,
            source="bulk_membership_sync",
            stats=stats,
        )

        return stats

    async def full_sync_all_channels(
        self,
        workspace_id: uuid.UUID,
        slack_client,
    ) -> dict:
        """
        Full membership sync for all channels — called by daily cron.

        Iterates through all non-archived channels, fetches their member
        lists from Slack, and bulk-syncs each one.

        Args:
            workspace_id: The workspace UUID.
            slack_client: Slack AsyncWebClient instance.

        Returns:
            Summary dict: {channels_synced: int, total_members: int}
        """
        stats = {"channels_synced": 0, "total_members": 0}

        async with AsyncSessionLocal() as session:
            ch_result = await session.execute(
                select(Channel).where(
                    and_(
                        Channel.workspace_id == workspace_id,
                        Channel.is_archived.is_(False),
                    )
                )
            )
            channels = ch_result.scalars().all()

        for channel in channels:
            try:
                # Fetch members from Slack API with pagination
                member_ids = []
                cursor = None
                while True:
                    kwargs = {
                        "channel": channel.slack_channel_id,
                        "limit": 200,
                    }
                    if cursor:
                        kwargs["cursor"] = cursor

                    result = await slack_client.conversations_members(**kwargs)
                    if not result["ok"]:
                        logger.warning(
                            f"conversations.members failed for "
                            f"{channel.slack_channel_id}: {result.get('error')}"
                        )
                        break

                    member_ids.extend(result.get("members", []))
                    cursor = result.get("response_metadata", {}).get("next_cursor")
                    if not cursor:
                        break

                # Sync the members
                await self.sync_channel_members(
                    slack_channel_id=channel.slack_channel_id,
                    member_slack_ids=member_ids,
                    workspace_id=workspace_id,
                )
                stats["channels_synced"] += 1
                stats["total_members"] += len(member_ids)

            except Exception as e:
                logger.error(
                    f"Failed to sync members for #{channel.name}: {e}",
                    exc_info=True,
                )

        logger.info(
            f"Membership sync complete: {stats['channels_synced']} channels, "
            f"{stats['total_members']} total memberships"
        )
        return stats


# ── Module-level singleton ──────────────────────────────────────
membership_service = MembershipService()
