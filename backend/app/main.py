"""
HiveMind Backend — FastAPI Application Entry Point.

This is the main module that ties everything together:
- FastAPI app with lifespan management
- Slack bot startup/shutdown
- API route registration
- CORS middleware for future frontend

Start with: uvicorn app.main:app --reload
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings

settings = get_settings()

# ── Logging ──────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Application Lifespan ─────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application startup and shutdown.

    Startup:
      1. Initialize database connection
      2. Create Slack bot (if configured)
      3. Start Slack bot in Socket Mode (dev) or wait for HTTP events (prod)

    Shutdown:
      1. Disconnect Slack bot
      2. Close database connections
    """
    logger.info(
        f"🐝 Starting {settings.app_name} v{settings.app_version} ({settings.app_env})"
    )

    # ── Startup ──────────────────────────────────────────────────
    # Database engine is created on import in database.py
    # Just verify connectivity
    from app.database import engine

    try:
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        logger.info("✅ Database connected")
    except Exception as e:
        logger.error(f"❌ Database connection failed: {e}")
        logger.error("Make sure PostgreSQL is running. Try: docker-compose up -d db")

    # Initialize Slack bot
    from app.slack.bot import create_slack_app, start_slack_bot

    slack_app = create_slack_app()
    if slack_app:
        await start_slack_bot()
    else:
        logger.warning("⚠️  Slack bot not started — configure credentials in .env")

    logger.info(f"🚀 {settings.app_name} is ready!")
    logger.info("   API docs: http://localhost:8000/docs")

    yield  # ← App is running here

    # ── Shutdown ─────────────────────────────────────────────────
    logger.info(f"Shutting down {settings.app_name}...")

    from app.slack.bot import stop_slack_bot

    await stop_slack_bot()

    from app.database import engine

    await engine.dispose()

    logger.info(f"👋 {settings.app_name} stopped.")


# ── FastAPI App ──────────────────────────────────────────────────
app = FastAPI(
    title=settings.app_name,
    description=(
        "AI Team Intelligence Agent — connects to your team's tools, "
        "ingests conversations and files, and provides intelligent "
        "summaries, search, and task management."
    ),
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS Middleware ──────────────────────────────────────────────
# Allow all origins in dev, restrict in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.is_development else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register Routes ──────────────────────────────────────────────
from app.api.health import router as health_router  # noqa: E402
from app.api.router import api_router  # noqa: E402

# Health check at root level
app.include_router(health_router)

# All API routes under /api/v1
app.include_router(api_router, prefix=settings.api_prefix)


# ── Root Redirect ────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
async def root():
    """Root endpoint — redirect to API docs."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/health",
        "api": f"{settings.api_prefix}/channels",
    }
