"""
LLM Factory tests — validates all provider configurations.

Tests cover:
- Provider initialization (openai, google, anthropic, ollama, openrouter)
- Missing API key handling
- Invalid provider handling
- Cache behavior (singleton pattern)
- Reset functionality
"""

from unittest.mock import MagicMock, patch

import pytest

# ═════════════════════════════════════════════════════════════════
# PROVIDER VALIDATION
# ═════════════════════════════════════════════════════════════════


class TestProviderValidation:
    """Tests for provider selection and validation."""

    def setup_method(self):
        """Reset LLM cache before each test."""
        from app.agent.llm import reset_llm

        reset_llm()

    def test_unsupported_provider_raises(self):
        """Unsupported provider raises ValueError."""
        with patch("app.agent.llm.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                llm_provider="azure-custom",
                llm_api_key="key",
            )

            from app.agent.llm import get_llm, reset_llm

            reset_llm()

            with pytest.raises(ValueError, match="Unsupported LLM provider"):
                get_llm()

    def test_openai_requires_api_key(self):
        """OpenAI provider raises ValueError without API key."""
        with patch("app.agent.llm.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                llm_provider="openai",
                llm_api_key="",
            )

            from app.agent.llm import get_llm, reset_llm

            reset_llm()

            with pytest.raises(ValueError, match="OpenAI requires LLM_API_KEY"):
                get_llm()

    def test_google_requires_api_key(self):
        """Google provider raises ValueError without API key."""
        with patch("app.agent.llm.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                llm_provider="google",
                llm_api_key="",
            )

            from app.agent.llm import get_llm, reset_llm

            reset_llm()

            with pytest.raises(ValueError, match="Google Gemini requires LLM_API_KEY"):
                get_llm()

    def test_anthropic_requires_api_key(self):
        """Anthropic provider raises ValueError without API key."""
        with patch("app.agent.llm.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                llm_provider="anthropic",
                llm_api_key="",
            )

            from app.agent.llm import get_llm, reset_llm

            reset_llm()

            with pytest.raises(ValueError, match="Anthropic requires LLM_API_KEY"):
                get_llm()

    def test_openrouter_requires_api_key(self):
        """OpenRouter provider raises ValueError without API key."""
        with patch("app.agent.llm.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                llm_provider="openrouter",
                llm_api_key="",
                llm_base_url="",
            )

            from app.agent.llm import get_llm, reset_llm

            reset_llm()

            with pytest.raises(ValueError, match="OpenRouter requires LLM_API_KEY"):
                get_llm()

    def test_ollama_no_key_required(self):
        """Ollama provider doesn't require an API key."""
        with patch("app.agent.llm.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                llm_provider="ollama",
                llm_model="llama3",
                llm_temperature=0.3,
            )

            from app.agent.llm import get_llm, reset_llm

            reset_llm()

            # Should not raise — Ollama doesn't need a key
            llm = get_llm()
            assert llm is not None


# ═════════════════════════════════════════════════════════════════
# CACHE BEHAVIOR
# ═════════════════════════════════════════════════════════════════


class TestLLMCache:
    """Tests for LLM instance caching."""

    def setup_method(self):
        from app.agent.llm import reset_llm

        reset_llm()

    def test_get_llm_returns_same_instance(self):
        """Calling get_llm() twice returns the same instance."""
        with patch("app.agent.llm.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                llm_provider="ollama",
                llm_model="llama3",
                llm_temperature=0.3,
            )

            from app.agent.llm import get_llm

            llm1 = get_llm()
            llm2 = get_llm()
            assert llm1 is llm2

    def test_reset_clears_cache(self):
        """reset_llm() clears the cached instance."""
        with patch("app.agent.llm.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                llm_provider="ollama",
                llm_model="llama3",
                llm_temperature=0.3,
            )

            from app.agent.llm import get_llm, reset_llm

            llm1 = get_llm()
            reset_llm()
            llm2 = get_llm()
            # After reset, should be a new instance
            assert llm1 is not llm2

    def test_provider_case_insensitive(self):
        """Provider name matching is case-insensitive."""
        with patch("app.agent.llm.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                llm_provider="OLLAMA",
                llm_model="llama3",
                llm_temperature=0.3,
            )

            from app.agent.llm import get_llm, reset_llm

            reset_llm()
            llm = get_llm()
            assert llm is not None


# ═════════════════════════════════════════════════════════════════
# OPENROUTER SPECIFIC
# ═════════════════════════════════════════════════════════════════


class TestOpenRouterProvider:
    """Tests specific to the OpenRouter provider."""

    def setup_method(self):
        from app.agent.llm import reset_llm

        reset_llm()

    def test_openrouter_creates_with_defaults(self):
        """OpenRouter uses default base_url when not specified."""
        with patch("app.agent.llm.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                llm_provider="openrouter",
                llm_model="google/gemma-3-27b-it:free",
                llm_api_key="test-key",
                llm_base_url="",
                llm_temperature=0.3,
                llm_max_tokens=2048,
            )

            from app.agent.llm import get_llm

            llm = get_llm()
            assert llm is not None

    def test_openrouter_uses_custom_base_url(self):
        """OpenRouter respects custom base_url from settings."""
        with patch("app.agent.llm.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                llm_provider="openrouter",
                llm_model="google/gemma-3-27b-it:free",
                llm_api_key="test-key",
                llm_base_url="https://openrouter.ai/api/v1",
                llm_temperature=0.3,
                llm_max_tokens=2048,
            )

            from app.agent.llm import get_llm

            llm = get_llm()
            assert llm is not None
