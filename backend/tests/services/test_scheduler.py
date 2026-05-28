"""
Scheduler Service tests — validates the job scheduling lifecycle.

Tests cover:
- Scheduler start/stop lifecycle
- Digest job registration
- Manual trigger
- Double-start prevention

Note: APScheduler's AsyncIOScheduler needs an event loop, so
scheduler.start() tests must be async.
"""

from unittest.mock import patch

# ═════════════════════════════════════════════════════════════════
# SCHEDULER LIFECYCLE
# ═════════════════════════════════════════════════════════════════


class TestSchedulerLifecycle:
    """Tests for the scheduler start/stop lifecycle."""

    def test_scheduler_not_running_initially(self):
        """Scheduler is not running when first created."""
        from app.services.scheduler import SchedulerService

        service = SchedulerService()
        assert service.is_running is False

    async def test_start_scheduler(self):
        """Starting the scheduler sets is_running to True."""
        with patch("app.services.scheduler.settings") as mock_settings:
            mock_settings.digest_enabled = True
            mock_settings.digest_hour = 9
            mock_settings.digest_minute = 0
            mock_settings.digest_timezone = "UTC"

            from app.services.scheduler import SchedulerService

            service = SchedulerService()
            service.start()

            assert service.is_running is True

            # Clean up
            service.stop()

    async def test_stop_scheduler(self):
        """Stopping the scheduler sets is_running to False."""
        with patch("app.services.scheduler.settings") as mock_settings:
            mock_settings.digest_enabled = True
            mock_settings.digest_hour = 9
            mock_settings.digest_minute = 0
            mock_settings.digest_timezone = "UTC"

            from app.services.scheduler import SchedulerService

            service = SchedulerService()
            service.start()
            service.stop()

            assert service.is_running is False

    async def test_double_start_is_noop(self):
        """Starting an already-running scheduler does nothing."""
        with patch("app.services.scheduler.settings") as mock_settings:
            mock_settings.digest_enabled = True
            mock_settings.digest_hour = 9
            mock_settings.digest_minute = 0
            mock_settings.digest_timezone = "UTC"

            from app.services.scheduler import SchedulerService

            service = SchedulerService()
            service.start()
            service.start()  # Should not raise

            assert service.is_running is True

            service.stop()

    def test_stop_when_not_running_is_noop(self):
        """Stopping a not-running scheduler does nothing."""
        from app.services.scheduler import SchedulerService

        service = SchedulerService()
        service.stop()  # Should not raise
        assert service.is_running is False


# ═════════════════════════════════════════════════════════════════
# DIGEST JOB
# ═════════════════════════════════════════════════════════════════


class TestDigestJob:
    """Tests for digest job registration."""

    async def test_digest_job_registered_when_enabled(self):
        """Digest job is registered when digest_enabled is True."""
        with patch("app.services.scheduler.settings") as mock_settings:
            mock_settings.digest_enabled = True
            mock_settings.digest_hour = 9
            mock_settings.digest_minute = 0
            mock_settings.digest_timezone = "UTC"

            from app.services.scheduler import SchedulerService

            service = SchedulerService()
            service.start()

            # Check that the job was registered
            jobs = service._scheduler.get_jobs()
            job_ids = [j.id for j in jobs]
            assert "daily_digest" in job_ids

            service.stop()

    async def test_digest_job_not_registered_when_disabled(self):
        """Digest job is not registered when digest_enabled is False.
        Membership sync should still be registered (always active)."""
        with patch("app.services.scheduler.settings") as mock_settings:
            mock_settings.digest_enabled = False
            mock_settings.digest_timezone = "UTC"

            from app.services.scheduler import SchedulerService

            service = SchedulerService()
            service.start()

            jobs = service._scheduler.get_jobs()
            job_ids = [j.id for j in jobs]
            assert "daily_digest" not in job_ids
            assert "membership_sync" in job_ids

            service.stop()

    async def test_membership_sync_always_registered(self):
        """Membership sync should be registered regardless of digest_enabled."""
        for digest_enabled in (True, False):
            with patch("app.services.scheduler.settings") as mock_settings:
                mock_settings.digest_enabled = digest_enabled
                mock_settings.digest_hour = 9
                mock_settings.digest_minute = 0
                mock_settings.digest_timezone = "UTC"

                from app.services.scheduler import SchedulerService

                service = SchedulerService()
                service.start()

                jobs = service._scheduler.get_jobs()
                job_ids = [j.id for j in jobs]
                assert "membership_sync" in job_ids, (
                    f"membership_sync missing when digest_enabled={digest_enabled}"
                )

                service.stop()

    async def test_scheduler_starts_without_digest_enabled(self):
        """Scheduler should start successfully even when digest is disabled."""
        with patch("app.services.scheduler.settings") as mock_settings:
            mock_settings.digest_enabled = False
            mock_settings.digest_timezone = "UTC"

            from app.services.scheduler import SchedulerService

            service = SchedulerService()
            service.start()

            assert service.is_running is True

            service.stop()
