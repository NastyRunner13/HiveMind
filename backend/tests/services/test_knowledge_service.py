"""
Knowledge Service tests — ACL computation and search result structure.

Tests cover:
- ACL computation for different channel types
- Search result data structure

Note: knowledge_service imports from app.database which needs asyncpg.
Tests are marked to skip if asyncpg is not available.
"""

import uuid
from unittest.mock import MagicMock

import pytest

from app.models.channel import ChannelType
from app.models.embedding import ACLType, Confidentiality

# Check if asyncpg is available
try:
    import asyncpg  # noqa: F401

    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False

skip_without_asyncpg = pytest.mark.skipif(
    not HAS_ASYNCPG,
    reason="asyncpg not installed — knowledge_service imports app.database",
)


# ═════════════════════════════════════════════════════════════════
# ACL COMPUTATION
# ═════════════════════════════════════════════════════════════════


@skip_without_asyncpg
class TestACLComputation:
    """Tests for ACL metadata derivation from channels."""

    def _make_channel(self, channel_type, slack_id="C123"):
        """Create a mock Channel object."""
        channel = MagicMock()
        channel.channel_type = channel_type
        channel.slack_channel_id = slack_id
        return channel

    def test_public_channel_acl(self):
        """Public channels get PUBLIC ACL."""
        from app.services.knowledge_service import compute_acl_for_channel

        channel = self._make_channel(ChannelType.PUBLIC)
        acl = compute_acl_for_channel(channel)

        assert acl.acl_type == ACLType.PUBLIC
        assert acl.confidentiality == Confidentiality.PUBLIC
        assert acl.allowed_channel_ids == ["C123"]
        assert acl.source_channel_id == "C123"

    def test_private_channel_acl(self):
        """Private channels get CHANNEL ACL (members only)."""
        from app.services.knowledge_service import compute_acl_for_channel

        channel = self._make_channel(ChannelType.PRIVATE)
        acl = compute_acl_for_channel(channel)

        assert acl.acl_type == ACLType.CHANNEL
        assert acl.confidentiality == Confidentiality.INTERNAL
        assert acl.allowed_channel_ids == ["C123"]

    def test_dm_channel_acl(self):
        """DMs get EXPLICIT ACL (participants only, confidential)."""
        from app.services.knowledge_service import compute_acl_for_channel

        channel = self._make_channel(ChannelType.DM)
        acl = compute_acl_for_channel(channel)

        assert acl.acl_type == ACLType.EXPLICIT
        assert acl.confidentiality == Confidentiality.CONFIDENTIAL
        assert acl.source_channel_id == "C123"
        assert acl.allowed_channel_ids is None


# ═════════════════════════════════════════════════════════════════
# ACL METADATA
# ═════════════════════════════════════════════════════════════════


@skip_without_asyncpg
class TestACLMetadata:
    """Tests for ACLMetadata data class."""

    def test_default_values(self):
        """ACLMetadata has sensible defaults."""
        from app.services.knowledge_service import ACLMetadata

        acl = ACLMetadata(acl_type=ACLType.PUBLIC)
        assert acl.allowed_channel_ids is None
        assert acl.allowed_user_ids is None
        assert acl.source_channel_id is None
        assert acl.confidentiality == Confidentiality.INTERNAL

    def test_explicit_values(self):
        """ACLMetadata stores explicit values correctly."""
        from app.services.knowledge_service import ACLMetadata

        acl = ACLMetadata(
            acl_type=ACLType.EXPLICIT,
            allowed_user_ids=["U1", "U2"],
            source_channel_id="D123",
            confidentiality=Confidentiality.CONFIDENTIAL,
        )
        assert acl.allowed_user_ids == ["U1", "U2"]
        assert acl.source_channel_id == "D123"


# ═════════════════════════════════════════════════════════════════
# SEARCH RESULT
# ═════════════════════════════════════════════════════════════════


@skip_without_asyncpg
class TestSearchResult:
    """Tests for SearchResult data class."""

    def test_search_result_fields(self):
        """SearchResult stores all fields correctly."""
        from app.services.knowledge_service import SearchResult

        result = SearchResult(
            chunk_id=uuid.uuid4(),
            content="Test content about auth migration",
            score=0.95,
            source_type="message",
            source_id=uuid.uuid4(),
            source_channel_id="C123",
            chunk_index=0,
        )

        assert result.score == 0.95
        assert result.source_type == "message"
        assert result.content == "Test content about auth migration"
        assert result.chunk_index == 0

    def test_search_result_without_channel(self):
        """SearchResult works without source_channel_id."""
        from app.services.knowledge_service import SearchResult

        result = SearchResult(
            chunk_id=uuid.uuid4(),
            content="Test",
            score=0.5,
            source_type="file",
            source_id=uuid.uuid4(),
            source_channel_id=None,
            chunk_index=0,
        )
        assert result.source_channel_id is None
