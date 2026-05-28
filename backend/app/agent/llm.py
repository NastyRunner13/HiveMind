"""
LLM Factory — provider-agnostic LLM initialization for HiveMind.

Supports multiple LLM providers through LangChain's unified interface.
The provider and model are configured via environment variables:
  LLM_PROVIDER=openai|google|anthropic|ollama|openrouter
  LLM_MODEL=gpt-4o-mini|gemini-2.0-flash|claude-3-haiku|llama3|google/gemma-3-27b-it:free
  LLM_API_KEY=your-api-key  (not needed for Ollama)
  LLM_BASE_URL=https://openrouter.ai/api/v1  (only for OpenRouter/Azure)

All credentials come from Settings — nothing is ever hardcoded.
"""

import logging

from langchain_core.language_models.chat_models import BaseChatModel

from app.config import get_settings

logger = logging.getLogger(__name__)

# Cache the LLM instance
_llm_instance: BaseChatModel | None = None


def get_llm() -> BaseChatModel:
    """
    Return the configured LLM instance (cached after first call).

    Supports:
    - OpenAI (GPT-4o, GPT-4o-mini, etc.)
    - Google (Gemini 2.0 Flash, Pro)
    - Anthropic (Claude 3/4 Haiku, Sonnet, Opus)
    - Ollama (local models — Llama, Mistral, etc.)
    - OpenRouter (any model via OpenAI-compatible API)

    Returns:
        A LangChain BaseChatModel instance.

    Raises:
        ValueError: If the provider is unsupported or credentials are missing.
    """
    global _llm_instance

    if _llm_instance is not None:
        return _llm_instance

    settings = get_settings()
    provider = settings.llm_provider.lower()

    if provider == "openai":
        _llm_instance = _create_openai_llm(settings)
    elif provider == "google":
        _llm_instance = _create_google_llm(settings)
    elif provider == "anthropic":
        _llm_instance = _create_anthropic_llm(settings)
    elif provider == "ollama":
        _llm_instance = _create_ollama_llm(settings)
    elif provider == "openrouter":
        _llm_instance = _create_openrouter_llm(settings)
    else:
        raise ValueError(
            f"Unsupported LLM provider: {provider}. "
            f"Supported: openai, google, anthropic, ollama, openrouter"
        )

    logger.info(f"Initialized LLM: {provider}/{settings.llm_model}")
    return _llm_instance


def _create_openai_llm(settings) -> BaseChatModel:
    """Create an OpenAI LLM instance."""
    from langchain_openai import ChatOpenAI

    if not settings.llm_api_key:
        raise ValueError("OpenAI requires LLM_API_KEY. Set it in your .env file.")

    kwargs = {
        "model": settings.llm_model,
        "api_key": settings.llm_api_key,
        "temperature": settings.llm_temperature,
        "max_tokens": settings.llm_max_tokens,
    }
    # Support custom base URL (e.g., Azure OpenAI)
    if settings.llm_base_url:
        kwargs["base_url"] = settings.llm_base_url

    return ChatOpenAI(**kwargs)


def _create_google_llm(settings) -> BaseChatModel:
    """Create a Google Gemini LLM instance."""
    from langchain_google_genai import ChatGoogleGenerativeAI

    if not settings.llm_api_key:
        raise ValueError(
            "Google Gemini requires LLM_API_KEY. Set it in your .env file."
        )

    return ChatGoogleGenerativeAI(
        model=settings.llm_model,
        google_api_key=settings.llm_api_key,
        temperature=settings.llm_temperature,
        max_output_tokens=settings.llm_max_tokens,
    )


def _create_anthropic_llm(settings) -> BaseChatModel:
    """Create an Anthropic Claude LLM instance."""
    from langchain_anthropic import ChatAnthropic

    if not settings.llm_api_key:
        raise ValueError("Anthropic requires LLM_API_KEY. Set it in your .env file.")

    return ChatAnthropic(
        model=settings.llm_model,
        anthropic_api_key=settings.llm_api_key,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
    )


def _create_ollama_llm(settings) -> BaseChatModel:
    """Create an Ollama (local) LLM instance."""
    from langchain_ollama import ChatOllama

    return ChatOllama(
        model=settings.llm_model,
        temperature=settings.llm_temperature,
    )


def _create_openrouter_llm(settings) -> BaseChatModel:
    """
    Create an OpenRouter LLM instance.

    OpenRouter provides a unified API for hundreds of models
    (GPT, Claude, Gemma, Llama, etc.) using the OpenAI-compatible format.
    Set LLM_BASE_URL=https://openrouter.ai/api/v1 in .env.
    """
    from langchain_openai import ChatOpenAI

    if not settings.llm_api_key:
        raise ValueError(
            "OpenRouter requires LLM_API_KEY. Set it in your .env file. "
            "Get a key at https://openrouter.ai/keys"
        )

    base_url = settings.llm_base_url or "https://openrouter.ai/api/v1"

    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=base_url,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        default_headers={
            "HTTP-Referer": "https://github.com/HiveMind",
            "X-Title": "HiveMind",
        },
    )


def reset_llm() -> None:
    """Reset the cached LLM instance (useful for testing)."""
    global _llm_instance
    _llm_instance = None
