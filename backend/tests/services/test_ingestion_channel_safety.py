"""
Tests for safe channel auto-creation in ingestion (Fix 3).

Verifies that _infer_channel_type():
- Returns DM for D-prefix channel IDs
- Returns PRIVATE for G-prefix channel IDs
- Returns PRIVATE (fail closed) for C-prefix channel IDs
- Returns PRIVATE for unknown prefixes

This ensures auto-created channels never default to PUBLIC,
preventing private/DM content from being indexed with public
ACL metadata.
"""

import pytest

# Check if asyncpg is available
try:
    import asyncpg

    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False

skip_without_asyncpg = pytest.mark.skipif(
    not HAS_ASYNCPG,
    reason="asyncpg not installed — ingestion imports app.database",
)


@skip_without_asyncpg
class TestInferChannelType:
    """Tests for _infer_channel_type() safe defaults."""

    def test_d_prefix_returns_dm(self):
        """D-prefix channels should be classified as DM."""
        from app.models.channel import ChannelType
        from app.services.ingestion import _infer_channel_type

        result = _infer_channel_type("D024BE91L")
        assert result == ChannelType.DM

    def test_g_prefix_returns_private(self):
        """G-prefix channels should be classified as PRIVATE."""
        from app.models.channel import ChannelType
        from app.services.ingestion import _infer_channel_type

        result = _infer_channel_type("G024BE91L")
        assert result == ChannelType.PRIVATE

    def test_c_prefix_returns_private_for_safety(self):
        """C-prefix channels should default to PRIVATE (fail closed).

        Even though C usually means public in Slack, we default to
        PRIVATE because the sync job will correct it. The inverse
        (defaulting to PUBLIC) would leak data for private channels
        that happen to have C-prefix IDs (newer Slack versions).
        """
        from app.models.channel import ChannelType
        from app.services.ingestion import _infer_channel_type

        result = _infer_channel_type("C024BE91L")
        assert result == ChannelType.PRIVATE

    def test_unknown_prefix_returns_private(self):
        """Unknown prefixes should default to PRIVATE (fail closed)."""
        from app.models.channel import ChannelType
        from app.services.ingestion import _infer_channel_type

        result = _infer_channel_type("X_UNKNOWN_123")
        assert result == ChannelType.PRIVATE

    def test_never_returns_public(self):
        """_infer_channel_type should NEVER return PUBLIC.

        Public classification must only come from a verified Slack
        API sync, not from prefix guessing. This is the core
        security property: fail closed.
        """
        from app.models.channel import ChannelType
        from app.services.ingestion import _infer_channel_type

        for prefix in ("C", "D", "G", "X", ""):
            channel_id = f"{prefix}TEST123"
            result = _infer_channel_type(channel_id)
            assert result != ChannelType.PUBLIC, (
                f"_infer_channel_type('{channel_id}') returned PUBLIC "
                f"— this is a data leak risk. Only verified Slack API "
                f"data should set PUBLIC."
            )
