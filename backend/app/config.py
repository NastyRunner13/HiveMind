"""
HiveMind Configuration — loads and validates environment variables at startup.

Uses pydantic-settings for type-safe config with .env file support.
All required settings are validated on import — the app fails fast if
anything is missing rather than crashing at runtime.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────
    app_env: Literal["development", "staging", "production"] = "development"
    app_name: str = "HiveMind"
    app_version: str = "0.1.0"
    log_level: str = "INFO"

    # ── Database ─────────────────────────────────────────────────
    database_url: str = (
        "postgresql+asyncpg://hivemind:hivemind_dev@localhost:5432/hivemind"
    )

    # For Alembic (sync driver needed for migrations)
    @property
    def database_url_sync(self) -> str:
        """Return a synchronous database URL for Alembic migrations."""
        return self.database_url.replace(
            "postgresql+asyncpg", "postgresql+psycopg2"
        ).replace("postgresql+asyncpg", "postgresql")

    # ── Slack ────────────────────────────────────────────────────
    slack_bot_token: str = ""
    slack_signing_secret: str = ""
    slack_app_token: str = ""  # Required for Socket Mode
    slack_socket_mode: bool = True  # Use Socket Mode for local dev

    @property
    def slack_configured(self) -> bool:
        """Check if Slack credentials are provided."""
        return bool(self.slack_bot_token and self.slack_signing_secret)

    # ── API ──────────────────────────────────────────────────────
    api_prefix: str = "/api/v1"
    api_page_size: int = 50
    api_max_page_size: int = 200

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


@lru_cache
def get_settings() -> Settings:
    """
    Return cached application settings.

    Using lru_cache ensures the .env file is read only once,
    and the same Settings instance is reused across the app.
    """
    return Settings()
