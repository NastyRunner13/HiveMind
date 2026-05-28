"""
Agent test fixtures — LLM and graph mocks for unit testing.

All tests use mocked LLM instances so no real API keys are needed.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage


@pytest.fixture
def mock_llm():
    """Create a mocked LLM that returns a simple AI response."""
    llm = MagicMock()
    response = AIMessage(content="I'm HiveMind, your AI team assistant!")
    llm.invoke = MagicMock(return_value=response)
    llm.ainvoke = AsyncMock(return_value=response)
    llm.bind_tools = MagicMock(return_value=llm)
    return llm


@pytest.fixture
def mock_settings():
    """Create mock settings for agent tests."""
    settings = MagicMock()
    settings.llm_provider = "openrouter"
    settings.llm_model = "google/gemma-3-27b-it:free"
    settings.llm_api_key = "test-key-123"
    settings.llm_base_url = "https://openrouter.ai/api/v1"
    settings.llm_temperature = 0.3
    settings.llm_max_tokens = 2048
    settings.llm_configured = True
    settings.is_development = True
    return settings
