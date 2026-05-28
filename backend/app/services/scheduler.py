"""
Scheduler Service — manages cron-like scheduled tasks for HiveMind.

Handles:
- Daily digest generation (configurable time and timezone, guarded by digest_enabled)
- Daily membership sync (always active — safety net for missed Slack events)

The scheduler is always started by the FastAPI lifespan, regardless of
whether digest_enabled is True. This ensures the membership sync cron
runs even when digests are disabled.

Uses APScheduler for reliable job scheduling with timezone support.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class SchedulerService:
    """
    Manages scheduled background tasks.

    Usage:
        scheduler = SchedulerService()
        scheduler.start()  # Call during app startup
        scheduler.stop()   # Call during app shutdown
    """

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()
        self._is_running = False

    def start(self) -> None:
        """Start the scheduler and register all jobs."""
        if self._is_running:
            return

        # Register daily digest job
        if settings.digest_enabled:
            self._scheduler.add_job(
                self._run_daily_digest,
                trigger=CronTrigger(
                    hour=settings.digest_hour,
                    minute=settings.digest_minute,
                    timezone=settings.digest_timezone,
                ),
                id="daily_digest",
                name="Daily Digest Generator",
                replace_existing=True,
            )
            logger.info(
                f"Scheduled daily digest at "
                f"{settings.digest_hour:02d}:{settings.digest_minute:02d} "
                f"{settings.digest_timezone}"
            )

        # Register daily membership sync (safety net for missed events)
        self._scheduler.add_job(
            self._run_membership_sync,
            trigger=CronTrigger(
                hour=3,
                minute=0,
                timezone=settings.digest_timezone,
            ),
            id="membership_sync",
            name="Daily Membership Sync",
            replace_existing=True,
        )
        logger.info("Scheduled daily membership sync at 03:00")

        self._scheduler.start()
        self._is_running = True
        logger.info("Scheduler started")

    def stop(self) -> None:
        """Stop the scheduler gracefully."""
        if self._is_running:
            self._scheduler.shutdown(wait=False)
            self._is_running = False
            logger.info("Scheduler stopped")

    @property
    def is_running(self) -> bool:
        return self._is_running

    async def _run_daily_digest(self) -> None:
        """Job: generate and deliver daily digests for all channels."""
        logger.info("🌅 Starting daily digest generation...")

        try:
            from app.services.digest_service import digest_service

            digests = await digest_service.generate_daily_digest()

            # Deliver each digest to Slack
            delivered = 0
            for digest in digests:
                success = await digest_service.deliver_to_slack(digest)
                if success:
                    delivered += 1

            logger.info(
                f"Daily digest complete: {len(digests)} generated, "
                f"{delivered} delivered to Slack"
            )

        except Exception as e:
            logger.error(f"Daily digest job failed: {e}", exc_info=True)

    async def _run_membership_sync(self) -> None:
        """
        Job: full membership sync for all channels from Slack API.

        Safety net that catches any membership changes missed by
        real-time events (member_joined_channel / member_left_channel).
        """
        logger.info("🔄 Starting daily membership sync...")

        try:
            from sqlalchemy import select

            from app.database import AsyncSessionLocal
            from app.models.workspace import Workspace
            from app.services.membership_service import membership_service

            async with AsyncSessionLocal() as session:
                ws_result = await session.execute(
                    select(Workspace).where(Workspace.is_active.is_(True)).limit(1)
                )
                workspace = ws_result.scalar_one_or_none()

            if not workspace:
                logger.warning("No active workspace — skipping membership sync")
                return

            # Get Slack client
            from app.slack.bot import get_slack_app

            slack_app = get_slack_app()
            if not slack_app:
                logger.warning("Slack not configured — skipping membership sync")
                return

            stats = await membership_service.full_sync_all_channels(
                workspace_id=workspace.id,
                slack_client=slack_app.client,
            )

            logger.info(
                f"Membership sync complete: {stats['channels_synced']} channels, "
                f"{stats['total_members']} memberships"
            )

        except Exception as e:
            logger.error(f"Membership sync job failed: {e}", exc_info=True)

    async def trigger_digest_now(self) -> list:
        """Manually trigger a digest generation (for on-demand requests)."""
        from app.services.digest_service import digest_service

        return await digest_service.generate_daily_digest()


# ── Module-level singleton ──────────────────────────────────────
scheduler_service = SchedulerService()
