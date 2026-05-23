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
from datetime import datetime, timezone

from slack_sdk.web.async_client import AsyncWebClient

from app.database import AsyncSessionLocal
from app.services.ingestion import (
    ingest_channel_from_api,
    ingest_file_metadata,
    ingest_message_from_history,
    ingest_user,
)

logger = logging.getLogger(__name__)


async def sync_channels(client: AsyncWebClient) -> dict:
    """
    Fetch all channels the bot is a member of and sync to database.

    Returns a summary dict: {synced: int, new: int, updated: int}
    """
    logger.info("Starting channel sync...")
    stats = {"synced": 0, "new": 0, "updated": 0}
    cursor = None

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
        f"({stats['new']} new, {stats['updated']} updated)"
    )
    return stats


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
                    file_info.get("shares", {})
                    .get("public", {})
                    .keys()
                ) or list(
                    file_info.get("shares", {})
                    .get("private", {})
                    .keys()
                )
                channel_id = channels[0] if channels else None
                await ingest_file_metadata(file_info, channel_id)
                stats["ingested"] += 1
            except Exception as e:
                stats["errors"] += 1
                logger.error(
                    f"Failed to ingest file metadata: {e}", exc_info=True
                )

        paging = result.get("paging", {})
        if page >= paging.get("pages", 1):
            break
        page += 1

    logger.info(
        f"File sync complete: {stats['fetched']} fetched, "
        f"{stats['ingested']} ingested, {stats['errors']} errors"
    )
    return stats
