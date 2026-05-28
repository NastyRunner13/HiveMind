"""
Event Bus test fixtures — Redis mocks for unit testing.

All tests use mocked Redis connections so no real Redis instance is needed.
"""

from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def mock_redis():
    """Create a mocked async Redis client."""
    redis_mock = AsyncMock()
    redis_mock.ping = AsyncMock(return_value=True)
    redis_mock.xadd = AsyncMock(return_value="1234567890-0")
    redis_mock.xinfo_stream = AsyncMock(return_value={
        "length": 42,
        "first-entry": None,
        "last-entry": None,
    })
    redis_mock.aclose = AsyncMock()
    return redis_mock


@pytest.fixture
def mock_event_bus(mock_redis):
    """Create an EventBus instance with a mocked Redis connection."""
    from app.events.bus import EventBus

    bus = EventBus()
    bus._redis = mock_redis
    return bus
