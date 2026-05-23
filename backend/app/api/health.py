"""
Health Check Endpoint — system status and connectivity verification.

Returns the overall health of the HiveMind backend including
database connectivity and Slack connection status.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])
settings = get_settings()


class HealthResponse(BaseModel):
    """Health check response."""

    status: str  # "healthy" or "degraded"
    version: str
    environment: str
    timestamp: str
    checks: dict[str, str]


@router.get("/health", response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    """
    System health check.

    Verifies:
    - Database connectivity (PostgreSQL)
    - Slack bot status
    """
    checks: dict[str, str] = {}
    overall_status = "healthy"

    # ── Database Check ───────────────────────────────────────────
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "connected"
    except Exception as e:
        checks["database"] = f"error: {e}"
        overall_status = "degraded"
        logger.error(f"Health check — DB failed: {e}")

    # ── Slack Check ──────────────────────────────────────────────
    if settings.slack_configured:
        from app.slack.bot import get_slack_app

        slack_app = get_slack_app()
        if slack_app is not None:
            checks["slack"] = "connected"
        else:
            checks["slack"] = "initialized but not connected"
    else:
        checks["slack"] = "not configured"

    return HealthResponse(
        status=overall_status,
        version=settings.app_version,
        environment=settings.app_env,
        timestamp=datetime.now(timezone.utc).isoformat(),
        checks=checks,
    )
