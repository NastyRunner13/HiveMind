"""
Tests for Embedding Dimension Safety validation.

Verifies that:
- validate_embedding_dimensions() passes when dimensions match
- validate_embedding_dimensions() raises SystemExit when dimensions mismatch
- Error message includes clear migration instructions
"""

from unittest.mock import patch

import pytest


class TestEmbeddingDimensionValidation:
    """Tests for Settings.validate_embedding_dimensions()."""

    def test_passes_when_dimensions_match(self):
        """Should not raise when embedding_dimensions == schema_embedding_dimensions."""
        from app.config import Settings

        settings = Settings(
            database_url="postgresql+asyncpg://test:test@localhost/test",
            embedding_dimensions=384,
            schema_embedding_dimensions=384,
        )

        # Should not raise
        settings.validate_embedding_dimensions()

    def test_raises_system_exit_on_mismatch(self):
        """Should raise SystemExit when dimensions don't match."""
        from app.config import Settings

        settings = Settings(
            database_url="postgresql+asyncpg://test:test@localhost/test",
            embedding_dimensions=1536,
            schema_embedding_dimensions=384,
        )

        with pytest.raises(SystemExit) as exc_info:
            settings.validate_embedding_dimensions()

        error_msg = str(exc_info.value)
        assert "CRITICAL" in error_msg
        assert "1536" in error_msg
        assert "384" in error_msg

    def test_error_message_includes_migration_instructions(self):
        """Error message should include Alembic migration instructions."""
        from app.config import Settings

        settings = Settings(
            database_url="postgresql+asyncpg://test:test@localhost/test",
            embedding_dimensions=1536,
            schema_embedding_dimensions=384,
        )

        with pytest.raises(SystemExit) as exc_info:
            settings.validate_embedding_dimensions()

        error_msg = str(exc_info.value)
        assert "ALTER TABLE" in error_msg
        assert "document_chunks" in error_msg
        assert "vector(1536)" in error_msg
        assert "SCHEMA_EMBEDDING_DIMENSIONS=1536" in error_msg

    def test_passes_with_openai_dimensions_when_schema_matches(self):
        """Should pass when both are set to OpenAI dimensions (1536)."""
        from app.config import Settings

        settings = Settings(
            database_url="postgresql+asyncpg://test:test@localhost/test",
            embedding_dimensions=1536,
            schema_embedding_dimensions=1536,
        )

        # Should not raise
        settings.validate_embedding_dimensions()

    def test_default_dimensions_match(self):
        """Default settings should have matching dimensions (384)."""
        from app.config import Settings

        settings = Settings(
            database_url="postgresql+asyncpg://test:test@localhost/test",
        )

        assert settings.embedding_dimensions == 384
        assert settings.schema_embedding_dimensions == 384

        # Should not raise
        settings.validate_embedding_dimensions()
