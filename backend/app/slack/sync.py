"""
Slack Sync Utilities — bulk data fetching for initial setup and backfill.

These functions are used to:
1. Initial workspace setup: sync all channels and users on first connect
2. History backfill: pull existing messages from channels the bot is in
3. Periodic refresh: re-sync channels/users to catch changes webhooks missed

All functions use pagination to handle large workspaces and respect
Slack's rate limits (built into the slack-sdk client).
"""

import logging
from datetime import datetime

from slack_sdk.web.async_client import AsyncWebClient

from app.services.ingestion import (
    get_or_create_workspace,
    ingest_channel_from_api,
    ingest_file_metadata,
    ingest_message_from_history,
    ingest_user,
)

logger = logging.getLogger(__name__)


async def _ensure_workspace(client: AsyncWebClient) -> None:
    """
    Ensure a workspace record exists in the database.

    Calls auth.test to get the team ID and name, then upserts
    the workspace. This MUST be called before any sync operation
    so that channels/users have a workspace_id to reference.
    """
    auth = await client.auth_test()
    team_id = auth.get("team_id", "")
    team_name = auth.get("team", "Unknown")
    team_url = auth.get("url", "")
    # Extract domain from team URL (e.g., "https://myteam.slack.com/" -> "myteam")
    domain = team_url.replace("https://", "").replace(".slack.com/", "")
    await get_or_create_workspace(slack_team_id=team_id, name=team_name, domain=domain)
    logger.info(f"Workspace ensured: {team_name} ({team_id})")


async def sync_channels(client: AsyncWebClient) -> dict:
    """
    Fetch all channels the bot is a member of and sync to database.
    Also syncs channel memberships for ACL enforcement.

    Returns a summary dict: {synced: int, new: int, updated: int, members_synced: int}
    """
    logger.info("Starting channel sync...")

    # Ensure workspace exists before syncing channels
    await _ensure_workspace(client)

    stats = {"synced": 0, "new": 0, "updated": 0, "members_synced": 0}
    cursor = None

    # Get workspace for membership sync
    from app.database import AsyncSessionLocal
    from app.models.workspace import Workspace

    async with AsyncSessionLocal() as session:
        from sqlalchemy import select

        ws_result = await session.execute(
            select(Workspace).where(Workspace.is_active.is_(True)).limit(1)
        )
        workspace = ws_result.scalar_one_or_none()

    while True:
        # conversations.list returns channels the bot can see
        result = await client.conversations_list(
            types="public_channel,private_channel",
            limit=200,
            cursor=cursor,
            exclude_archived=False,
        )

        if not result["ok"]:
            logger.error(f"conversations.list failed: {result['error']}")
            break

        channels = result.get("channels", [])
        for channel_data in channels:
            try:
                is_new = await ingest_channel_from_api(channel_data)
                stats["synced"] += 1
                if is_new:
                    stats["new"] += 1
                else:
                    stats["updated"] += 1

                # Sync channel members for ACL
                if workspace:
                    try:
                        await _sync_channel_members(
                            client=client,
                            slack_channel_id=channel_data.get("id", ""),
                            workspace_id=workspace.id,
                        )
                        stats["members_synced"] += 1
                    except Exception as e:
                        logger.warning(
                            f"Failed to sync members for "
                            f"{channel_data.get('id')}: {e}"
                        )
            except Exception as e:
                logger.error(
                    f"Failed to sync channel {channel_data.get('id')}: {e}",
                    exc_info=True,
                )

        # Handle pagination
        cursor = result.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    logger.info(
        f"Channel sync complete: {stats['synced']} synced "
        f"({stats['new']} new, {stats['updated']} updated, "
        f"{stats['members_synced']} with members)"
    )
    return stats


async def _sync_channel_members(
    client: AsyncWebClient,
    slack_channel_id: str,
    workspace_id,
) -> None:
    """
    Fetch and sync members for a single channel.

    Called during channel sync to populate the channel_memberships
    table for ACL enforcement.
    """
    from app.services.membership_service import membership_service

    member_ids = []
    cursor = None

    while True:
        kwargs = {"channel": slack_channel_id, "limit": 200}
        if cursor:
            kwargs["cursor"] = cursor

        result = await client.conversations_members(**kwargs)
        if not result["ok"]:
            logger.warning(
                f"conversations.members failed for "
                f"{slack_channel_id}: {result.get('error')}"
            )
            break

        member_ids.extend(result.get("members", []))
        cursor = result.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    if member_ids:
        await membership_service.sync_channel_members(
            slack_channel_id=slack_channel_id,
            member_slack_ids=member_ids,
            workspace_id=workspace_id,
        )


async def sync_users(client: AsyncWebClient) -> dict:
    """
    Fetch all workspace users and sync to database.

    Returns a summary dict: {synced: int, new: int, updated: int}
    """
    logger.info("Starting user sync...")
    stats = {"synced": 0, "new": 0, "updated": 0}
    cursor = None

    while True:
        result = await client.users_list(limit=200, cursor=cursor)

        if not result["ok"]:
            logger.error(f"users.list failed: {result['error']}")
            break

        members = result.get("members", [])
        for user_data in members:
            # Skip Slackbot and deactivated users
            if user_data.get("id") == "USLACKBOT":
                continue

            try:
                is_new = await ingest_user(user_data)
                stats["synced"] += 1
                if is_new:
                    stats["new"] += 1
                else:
                    stats["updated"] += 1
            except Exception as e:
                logger.error(
                    f"Failed to sync user {user_data.get('id')}: {e}",
                    exc_info=True,
                )

        cursor = result.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    logger.info(
        f"User sync complete: {stats['synced']} synced "
        f"({stats['new']} new, {stats['updated']} updated)"
    )
    return stats


async def sync_channel_history(
    client: AsyncWebClient,
    slack_channel_id: str,
    oldest: datetime | None = None,
    limit: int = 1000,
) -> dict:
    """
    Backfill message history for a specific channel.

    Args:
        client: Slack Web API client
        slack_channel_id: Slack channel ID to fetch history from
        oldest: Only fetch messages after this timestamp (for incremental sync)
        limit: Maximum number of messages to fetch

    Returns:
        Summary dict: {fetched: int, ingested: int, errors: int}
    """
    logger.info(
        f"Starting history sync for channel {slack_channel_id} "
        f"(oldest={oldest}, limit={limit})"
    )
    stats = {"fetched": 0, "ingested": 0, "errors": 0}
    cursor = None
    oldest_ts = str(oldest.timestamp()) if oldest else None

    while stats["fetched"] < limit:
        kwargs = {
            "channel": slack_channel_id,
            "limit": min(200, limit - stats["fetched"]),
        }
        if cursor:
            kwargs["cursor"] = cursor
        if oldest_ts:
            kwargs["oldest"] = oldest_ts

        result = await client.conversations_history(**kwargs)

        if not result["ok"]:
            logger.error(
                f"conversations.history failed for {slack_channel_id}: "
                f"{result.get('error')}"
            )
            break

        messages = result.get("messages", [])
        if not messages:
            break

        for msg in messages:
            stats["fetched"] += 1
            try:
                await ingest_message_from_history(
                    msg, slack_channel_id=slack_channel_id
                )
                stats["ingested"] += 1
            except Exception as e:
                stats["errors"] += 1
                logger.error(
                    f"Failed to ingest historical message: {e}",
                    exc_info=True,
                )

        cursor = result.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    logger.info(
        f"History sync complete for {slack_channel_id}: "
        f"{stats['fetched']} fetched, {stats['ingested']} ingested, "
        f"{stats['errors']} errors"
    )
    return stats


async def sync_workspace_files(
    client: AsyncWebClient,
    limit: int = 500,
) -> dict:
    """
    Fetch recent file metadata from the workspace.

    Only indexes metadata — never downloads file content.

    Returns:
        Summary dict: {fetched: int, ingested: int, errors: int}
    """
    logger.info("Starting workspace file metadata sync...")
    stats = {"fetched": 0, "ingested": 0, "errors": 0}
    page = 1

    while stats["fetched"] < limit:
        result = await client.files_list(
            count=min(100, limit - stats["fetched"]),
            page=page,
        )

        if not result["ok"]:
            logger.error(f"files.list failed: {result.get('error')}")
            break

        files = result.get("files", [])
        if not files:
            break

        for file_info in files:
            stats["fetched"] += 1
            try:
                # Determine the primary channel (first share channel)
                channels = list(
                    file_info.get("shares", {}).get("public", {}).keys()
                ) or list(file_info.get("shares", {}).get("private", {}).keys())
                channel_id = channels[0] if channels else None
                await ingest_file_metadata(file_info, channel_id)
                stats["ingested"] += 1
            except Exception as e:
                stats["errors"] += 1
                logger.error(f"Failed to ingest file metadata: {e}", exc_info=True)

        paging = result.get("paging", {})
        if page >= paging.get("pages", 1):
            break
        page += 1

    logger.info(
        f"File sync complete: {stats['fetched']} fetched, "
        f"{stats['ingested']} ingested, {stats['errors']} errors"
    )
    return stats
