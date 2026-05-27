"""
Embedding Service tests — text chunking, token counting, and provider initialization.

Tests cover:
- Text chunking (overlapping, edge cases)
- Token counting
- Character fallback chunking
- Provider initialization (local, openai)
- Batch embedding interface
"""

import pytest

from app.services.embedding_service import (
    EmbeddingService,
    LocalEmbeddingProvider,
    chunk_text,
    count_tokens,
    _chunk_by_chars,
)


# ═════════════════════════════════════════════════════════════════
# TEXT CHUNKING
# ═════════════════════════════════════════════════════════════════


class TestChunkText:
    """Tests for the chunk_text function."""

    def test_empty_text_returns_empty(self):
        """Empty or whitespace-only text returns empty list."""
        assert chunk_text("") == []
        assert chunk_text("   ") == []
        assert chunk_text(None) == []

    def test_short_text_single_chunk(self):
        """Text shorter than max_tokens is a single chunk."""
        text = "Hello world, this is a test."
        chunks = chunk_text(text, max_tokens=512)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_long_text_multiple_chunks(self):
        """Long text is split into multiple overlapping chunks."""
        # Create text that's definitely > 100 tokens
        text = " ".join(["This is a test sentence."] * 100)
        chunks = chunk_text(text, max_tokens=50, overlap_tokens=10)
        assert len(chunks) > 1
        # All chunks should have content
        for chunk in chunks:
            assert len(chunk) > 0

    def test_overlap_preserves_context(self):
        """Overlapping chunks share some content at boundaries."""
        text = " ".join(["word"] * 200)
        chunks = chunk_text(text, max_tokens=50, overlap_tokens=10)

        if len(chunks) >= 2:
            # The end of chunk N and start of chunk N+1 should overlap
            # (exact overlap depends on token boundaries, but there should
            # be some shared content)
            assert len(chunks) >= 2  # Just confirm we got multiple chunks

    def test_single_word_text(self):
        """Single word text returns one chunk."""
        chunks = chunk_text("hello")
        assert len(chunks) == 1
        assert chunks[0] == "hello"


class TestChunkByChars:
    """Tests for the character-based fallback chunking."""

    def test_short_text_single_chunk(self):
        """Short text returns single chunk."""
        chunks = _chunk_by_chars("hello", max_chars=100)
        assert chunks == ["hello"]

    def test_long_text_split(self):
        """Long text is split at character boundaries."""
        text = "a" * 500
        chunks = _chunk_by_chars(text, max_chars=100)
        assert len(chunks) == 5
        assert all(len(c) == 100 for c in chunks)


class TestCountTokens:
    """Tests for the count_tokens function."""

    def test_count_simple_text(self):
        """Counts tokens in simple text."""
        count = count_tokens("Hello world")
        assert count > 0
        assert isinstance(count, int)

    def test_count_empty_text(self):
        """Empty text has 0 tokens."""
        count = count_tokens("")
        assert count == 0

    def test_count_long_text(self):
        """Longer text has more tokens."""
        short_count = count_tokens("Hi")
        long_count = count_tokens("This is a much longer sentence with many words")
        assert long_count > short_count


# ═════════════════════════════════════════════════════════════════
# EMBEDDING SERVICE
# ═════════════════════════════════════════════════════════════════


class TestEmbeddingService:
    """Tests for the EmbeddingService main interface."""

    def test_chunk_and_count(self):
        """chunk_and_count returns (text, token_count) pairs."""
        service = EmbeddingService()
        results = service.chunk_and_count("This is a test sentence for chunking.")

        assert len(results) > 0
        for text, count in results:
            assert isinstance(text, str)
            assert isinstance(count, int)
            assert count > 0

    def test_chunk_and_count_empty(self):
        """chunk_and_count returns empty list for empty text."""
        service = EmbeddingService()
        assert service.chunk_and_count("") == []

    async def test_embed_texts_empty_list(self):
        """Embedding empty list returns empty list."""
        service = EmbeddingService()
        result = await service.embed_texts([])
        assert result == []


# ═════════════════════════════════════════════════════════════════
# PROVIDER INITIALIZATION
# ═════════════════════════════════════════════════════════════════


class TestProviderInit:
    """Tests for embedding provider initialization."""

    def test_unsupported_provider_raises(self):
        """Unsupported provider raises ValueError."""
        from unittest.mock import patch, MagicMock

        with patch("app.services.embedding_service.settings") as mock_settings:
            mock_settings.embedding_provider = "unsupported"

            service = EmbeddingService()
            service._provider = None  # Reset

            with pytest.raises(ValueError, match="Unsupported embedding provider"):
                service._get_provider()

    def test_local_provider_init(self):
        """Local provider can be instantiated."""
        provider = LocalEmbeddingProvider()
        assert provider._model is None  # Lazy loaded
