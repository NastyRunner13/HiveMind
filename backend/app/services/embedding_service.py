"""
Embedding Service — provider-agnostic text embedding for the Knowledge Fabric.

Supports multiple embedding providers (OpenAI, local) through a
unified interface. Handles text chunking with overlap for optimal retrieval.

Design principles:
- Provider-agnostic: swap models via config, no code changes
- Batch-capable: embed multiple texts in one API call
- Token-aware: respects model context limits
- All API keys come from Settings — nothing hardcoded

Providers:
- local: sentence-transformers (all-MiniLM-L6-v2, 384 dims) — FREE, runs on CPU
- openai: OpenAI API (text-embedding-3-small, 1536 dims) — paid, highest quality
"""

import logging
from typing import Protocol

import tiktoken

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


# ═════════════════════════════════════════════════════════════════
# TEXT CHUNKING
# ═════════════════════════════════════════════════════════════════


def chunk_text(
    text: str,
    max_tokens: int = 512,
    overlap_tokens: int = 50,
    encoding_name: str = "cl100k_base",
) -> list[str]:
    """
    Split text into overlapping chunks sized for embedding models.

    Uses tiktoken for accurate token counting. Overlap ensures context
    isn't lost at chunk boundaries — critical for quality retrieval.

    Args:
        text: The text to chunk.
        max_tokens: Maximum tokens per chunk.
        overlap_tokens: Number of overlapping tokens between chunks.
        encoding_name: Tiktoken encoding to use.

    Returns:
        List of text chunks.
    """
    if not text or not text.strip():
        return []

    try:
        encoding = tiktoken.get_encoding(encoding_name)
    except Exception:
        # Fallback to simple character-based chunking
        logger.warning(
            "tiktoken encoding not available, using character-based chunking"
        )
        return _chunk_by_chars(text, max_chars=max_tokens * 4)

    tokens = encoding.encode(text)

    if len(tokens) <= max_tokens:
        return [text]

    chunks = []
    start = 0
    while start < len(tokens):
        end = min(start + max_tokens, len(tokens))
        chunk_tokens = tokens[start:end]
        chunk_text = encoding.decode(chunk_tokens)
        chunks.append(chunk_text)

        # Move forward by (max_tokens - overlap)
        start += max_tokens - overlap_tokens

    return chunks


def _chunk_by_chars(text: str, max_chars: int = 2000) -> list[str]:
    """Fallback character-based chunking."""
    chunks = []
    for i in range(0, len(text), max_chars):
        chunks.append(text[i : i + max_chars])
    return chunks


def count_tokens(text: str, encoding_name: str = "cl100k_base") -> int:
    """Count the number of tokens in a text string."""
    try:
        encoding = tiktoken.get_encoding(encoding_name)
        return len(encoding.encode(text))
    except Exception:
        # Rough estimate: 1 token ≈ 4 characters
        return len(text) // 4


# ═════════════════════════════════════════════════════════════════
# EMBEDDING PROVIDER INTERFACE
# ═════════════════════════════════════════════════════════════════


class EmbeddingProvider(Protocol):
    """Protocol for embedding providers."""

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts."""
        ...

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single search query."""
        ...


# ═════════════════════════════════════════════════════════════════
# LOCAL PROVIDER (sentence-transformers — FREE)
# ═════════════════════════════════════════════════════════════════


class LocalEmbeddingProvider:
    """
    Local embedding provider using sentence-transformers.

    Uses all-MiniLM-L6-v2 by default (384 dims, ~80MB download).
    Runs entirely on CPU — no API key needed, completely free.

    First call downloads the model if not cached locally.
    """

    def __init__(self) -> None:
        self._model = None

    def _get_model(self):
        """Lazy-load the sentence-transformers model."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError:
                raise ImportError(
                    "sentence-transformers is required for local embeddings. "
                    "Install it with: pip install sentence-transformers"
                )

            model_name = settings.embedding_model
            logger.info(f"Loading local embedding model: {model_name}...")
            self._model = SentenceTransformer(model_name)
            logger.info(
                f"Local embedding model loaded: {model_name} "
                f"(dimensions={self._model.get_sentence_embedding_dimension()})"
            )

        return self._model

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using the local model (runs synchronously on CPU)."""
        import asyncio

        model = self._get_model()
        # Run in executor to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(
            None, lambda: model.encode(texts, show_progress_bar=False).tolist()
        )
        return embeddings

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single search query."""
        results = await self.embed_texts([text])
        return results[0]


# ═════════════════════════════════════════════════════════════════
# OPENAI PROVIDER (paid, highest quality)
# ═════════════════════════════════════════════════════════════════


class OpenAIEmbeddingProvider:
    """OpenAI embedding provider using langchain-openai."""

    def __init__(self) -> None:
        from langchain_openai import OpenAIEmbeddings

        api_key = settings.effective_embedding_api_key
        if not api_key:
            raise ValueError(
                "OpenAI embedding requires an API key. "
                "Set LLM_API_KEY or EMBEDDING_API_KEY in .env"
            )

        self._embeddings = OpenAIEmbeddings(
            model=settings.embedding_model,
            api_key=api_key,
            dimensions=settings.embedding_dimensions,
        )

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using OpenAI API."""
        return await self._embeddings.aembed_documents(texts)

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single search query."""
        return await self._embeddings.aembed_query(text)


# ═════════════════════════════════════════════════════════════════
# EMBEDDING SERVICE (MAIN INTERFACE)
# ═════════════════════════════════════════════════════════════════


class EmbeddingService:
    """
    Main embedding service — provides text → vector conversion.

    Usage:
        service = EmbeddingService()
        vectors = await service.embed_texts(["Hello world", "Another text"])
        query_vec = await service.embed_query("search for something")
    """

    def __init__(self) -> None:
        self._provider: LocalEmbeddingProvider | OpenAIEmbeddingProvider | None = None

    def _get_provider(self) -> LocalEmbeddingProvider | OpenAIEmbeddingProvider:
        """Lazy-initialize the embedding provider."""
        if self._provider is None:
            provider_name = settings.embedding_provider.lower()

            if provider_name == "local":
                self._provider = LocalEmbeddingProvider()
            elif provider_name == "openai":
                self._provider = OpenAIEmbeddingProvider()
            else:
                raise ValueError(
                    f"Unsupported embedding provider: {provider_name}. "
                    f"Supported: local, openai"
                )

            logger.info(
                f"Initialized {provider_name} embedding provider "
                f"(model={settings.embedding_model}, "
                f"dimensions={settings.embedding_dimensions})"
            )

        return self._provider

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a list of texts into vectors.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors (same order as input texts).
        """
        if not texts:
            return []

        provider = self._get_provider()
        return await provider.embed_texts(texts)

    async def embed_query(self, query: str) -> list[float]:
        """
        Embed a single search query.

        Note: Some providers use different models/methods for queries
        vs. documents. This method handles that distinction.
        """
        provider = self._get_provider()
        return await provider.embed_query(query)

    def chunk_and_count(
        self, text: str, max_tokens: int = 512
    ) -> list[tuple[str, int]]:
        """
        Chunk text and return (chunk_text, token_count) pairs.

        Convenience method for the indexing pipeline.
        """
        chunks = chunk_text(text, max_tokens=max_tokens)
        return [(chunk, count_tokens(chunk)) for chunk in chunks]


# ── Module-level singleton ──────────────────────────────────────
embedding_service = EmbeddingService()
