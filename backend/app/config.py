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
    app_env: Literal["development", "staging", "production", "testing"] = "development"
    app_name: str = "HiveMind"
    app_version: str = "0.1.0"
    log_level: str = "INFO"

    # ── Database ─────────────────────────────────────────────────
    # No default — DATABASE_URL must be set via .env or environment.
    # This ensures the app fails fast if the connection string is missing.
    database_url: str

    # For Alembic (sync driver needed for migrations)
    @property
    def database_url_sync(self) -> str:
        """Return a synchronous database URL for Alembic migrations."""
        return self.database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")

    # ── Redis ────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    redis_stream_max_len: int = 10000  # Cap stream length for memory

    @property
    def redis_configured(self) -> bool:
        """Check if Redis URL is provided."""
        return bool(self.redis_url)

    # ── Slack ────────────────────────────────────────────────────
    slack_bot_token: str = ""
    slack_signing_secret: str = ""
    slack_app_token: str = ""  # Required for Socket Mode
    slack_socket_mode: bool = True  # Use Socket Mode for local dev

    @property
    def slack_configured(self) -> bool:
        """Check if Slack credentials are provided."""
        return bool(self.slack_bot_token and self.slack_signing_secret)

    # ── OIDC Authentication (Keycloak / Auth0 / any OIDC provider) ──
    # Protected REST endpoints require a bearer token validated via OIDC.
    oidc_issuer_url: str = ""  # e.g., http://localhost:8080/realms/hivemind
    oidc_audience: str = ""  # Client ID / audience claim expected in tokens
    oidc_discovery_url: str = ""  # Optional; defaults to {issuer}/.well-known/openid-configuration

    @property
    def oidc_configured(self) -> bool:
        """Check whether OIDC access-token validation is configured."""
        return bool(self.oidc_issuer_url and self.oidc_audience)

    @property
    def effective_oidc_issuer(self) -> str:
        """Return the expected token issuer."""
        return self.oidc_issuer_url.rstrip("/")

    @property
    def oidc_discovery_url_resolved(self) -> str:
        """Return the OpenID Connect discovery URL for JWKS discovery."""
        if self.oidc_discovery_url:
            return self.oidc_discovery_url
        return f"{self.effective_oidc_issuer}/.well-known/openid-configuration"

    # ── LLM ──────────────────────────────────────────────────────
    # Supports: openai, google, anthropic, ollama, openrouter
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    llm_api_key: str = ""  # Read from env, NEVER hardcoded
    llm_base_url: str = ""  # Custom API base URL (e.g., OpenRouter, Azure)
    llm_temperature: float = 0.3
    llm_max_tokens: int = 2048

    @property
    def llm_configured(self) -> bool:
        """Check if LLM credentials are provided (Ollama doesn't need a key)."""
        return self.llm_provider == "ollama" or bool(self.llm_api_key)

    # ── Embeddings ───────────────────────────────────────────────
    # Defaults to free local model. Switch to openai for production quality.
    #
    # IMPORTANT: embedding_dimensions must match the database schema.
    # The Alembic migration (0002) creates the vector column with a fixed
    # dimension. If you change providers (e.g., local→openai), you MUST:
    #   1. Create a new migration to resize the vector column
    #   2. Update SCHEMA_EMBEDDING_DIMENSIONS to match
    # The app validates this at startup and refuses to start on mismatch.
    embedding_provider: str = "local"  # local, openai
    embedding_model: str = (
        "all-MiniLM-L6-v2"  # local: all-MiniLM-L6-v2, openai: text-embedding-3-small
    )
    embedding_api_key: str = ""  # Falls back to llm_api_key if empty (only for openai)
    embedding_dimensions: int = 384  # local: 384, openai: 1536

    # Schema-level dimension — must match the Alembic migration's vector(N).
    # This is the "source of truth" for what the DB expects.
    # Default: 384 (migration 0002 creates vector(384) for local embeddings).
    schema_embedding_dimensions: int = 384

    @property
    def effective_embedding_api_key(self) -> str:
        """Return the embedding API key, falling back to the LLM key."""
        return self.embedding_api_key or self.llm_api_key

    # ── Daily Digest ─────────────────────────────────────────────
    digest_enabled: bool = True
    digest_hour: int = 9  # 24h format, local time
    digest_minute: int = 0
    digest_timezone: str = "UTC"
    digest_channel: str = ""  # Slack channel to post digests (e.g., #hivemind-daily)

    # ── API ──────────────────────────────────────────────────────
    api_prefix: str = "/api/v1"
    api_page_size: int = 50
    api_max_page_size: int = 200

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    def validate_embedding_dimensions(self) -> None:
        """
        Validate that runtime embedding dimensions match the DB schema.

        The Alembic migration creates the vector column with a fixed
        dimension (schema_embedding_dimensions). If the runtime config
        specifies a different dimension, vectors will fail to insert.

        Raises:
            SystemExit: If dimensions don't match, with clear instructions.
        """
        if self.embedding_dimensions != self.schema_embedding_dimensions:
            raise SystemExit(
                f"\n{'=' * 60}\n"
                f"CRITICAL: Embedding dimension mismatch!\n"
                f"{'=' * 60}\n"
                f"Config: EMBEDDING_DIMENSIONS={self.embedding_dimensions}\n"
                f"Schema: SCHEMA_EMBEDDING_DIMENSIONS={self.schema_embedding_dimensions}\n\n"
                f"The database vector column was created with "
                f"vector({self.schema_embedding_dimensions}).\n"
                f"Inserting {self.embedding_dimensions}-dim vectors will fail.\n\n"
                f"To fix, create a new Alembic migration:\n"
                f"  ALTER TABLE document_chunks DROP COLUMN embedding;\n"
                f"  ALTER TABLE document_chunks ADD COLUMN embedding "
                f"vector({self.embedding_dimensions});\n"
                f"  -- Then rebuild the HNSW index\n\n"
                f"Then update .env:\n"
                f"  SCHEMA_EMBEDDING_DIMENSIONS={self.embedding_dimensions}\n"
                f"{'=' * 60}"
            )


@lru_cache
def get_settings() -> Settings:
    """
    Return cached application settings.

    Using lru_cache ensures the .env file is read only once,
    and the same Settings instance is reused across the app.
    """
    return Settings()
