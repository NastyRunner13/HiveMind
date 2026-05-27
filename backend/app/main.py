"""
HiveMind Backend — FastAPI Application Entry Point.

This is the main module that ties everything together:
- FastAPI app with lifespan management
- Slack bot startup/shutdown
- Redis Event Bus startup/shutdown
- Daily digest scheduler
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
      2. Connect Redis Event Bus
      3. Start knowledge indexing consumer (background task)
      4. Create Slack bot (if configured)
      5. Start Slack bot in Socket Mode (dev) or wait for HTTP events (prod)
      6. Start daily digest scheduler (if enabled)

    Shutdown:
      1. Stop digest scheduler
      2. Cancel knowledge consumer
      3. Disconnect Slack bot
      4. Disconnect Redis Event Bus
      5. Close database connections
    """
    import asyncio

    logger.info(
        f"🐝 Starting {settings.app_name} v{settings.app_version} ({settings.app_env})"
    )

    # Track background tasks for graceful shutdown
    consumer_task = None

    # ── Startup ──────────────────────────────────────────────────
    # 1. Database
    from app.database import engine

    try:
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        logger.info("✅ Database connected")
    except Exception as e:
        logger.error(f"❌ Database connection failed: {e}")
        logger.error("Make sure PostgreSQL is running. Try: docker-compose up -d db")

    # 1b. Validate embedding dimensions match the DB schema
    try:
        settings.validate_embedding_dimensions()
        logger.info(
            f"✅ Embedding dimensions validated: {settings.embedding_dimensions}d "
            f"({settings.embedding_provider}/{settings.embedding_model})"
        )
    except SystemExit:
        raise  # Let the SystemExit propagate to kill the app

    # 2. Redis Event Bus
    from app.events.bus import event_bus

    try:
        await event_bus.connect()
    except Exception as e:
        logger.warning(f"⚠️  Redis Event Bus not available: {e}")
        logger.warning("Events will be skipped. Try: docker-compose up -d redis")

    # 3. Knowledge indexing consumer (background task)
    if event_bus.is_connected:
        from app.events.consumers import start_knowledge_consumer

        consumer_task = asyncio.create_task(start_knowledge_consumer())
        logger.info("✅ Knowledge indexing consumer started")

    # 4. Slack bot
    from app.slack.bot import create_slack_app, start_slack_bot

    slack_app = create_slack_app()
    if slack_app:
        await start_slack_bot()
    else:
        logger.warning("⚠️  Slack bot not started — configure credentials in .env")

    # 5. Scheduler (always started — handles both digest + membership sync)
    from app.services.scheduler import scheduler_service

    try:
        scheduler_service.start()
        logger.info("✅ Scheduler started")
    except Exception as e:
        logger.warning(f"⚠️  Scheduler failed to start: {e}")

    logger.info(f"🚀 {settings.app_name} is ready!")
    logger.info("   API docs: http://localhost:8000/docs")

    yield  # ← App is running here

    # ── Shutdown ─────────────────────────────────────────────────
    logger.info(f"Shutting down {settings.app_name}...")

    # Stop scheduler
    try:
        scheduler_service.stop()
    except Exception:
        pass

    # Cancel knowledge consumer
    if consumer_task and not consumer_task.done():
        consumer_task.cancel()
        try:
            await asyncio.wait_for(consumer_task, timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        logger.info("Knowledge indexing consumer stopped")

    # Disconnect Slack
    from app.slack.bot import stop_slack_bot

    await stop_slack_bot()

    # Disconnect Redis
    await event_bus.disconnect()

    # Close DB
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
