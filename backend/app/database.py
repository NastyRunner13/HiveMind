"""
HiveMind Database — async SQLAlchemy engine and session management.

Provides the core database infrastructure:
- Async engine with connection pooling
- Session factory for request-scoped DB sessions
- FastAPI dependency for injecting sessions into route handlers
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

settings = get_settings()

# ── Engine ───────────────────────────────────────────────────────
# The async engine manages a pool of database connections.
# pool_size=5 is conservative for local dev; scale up in production.
engine = create_async_engine(
    settings.database_url,
    echo=settings.is_development,  # Log SQL queries in dev mode
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,  # Verify connections before use
)

# ── Session Factory ──────────────────────────────────────────────
# Each request gets its own session; expire_on_commit=False lets us
# access object attributes after commit without re-querying.
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ── FastAPI Dependency ───────────────────────────────────────────
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Yield a database session for a single request.

    Usage in FastAPI routes:
        @router.get("/items")
        async def list_items(db: AsyncSession = Depends(get_db)):
            ...

    The session is automatically closed after the request completes,
    even if an exception occurs.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
