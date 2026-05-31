"""
Knowledge Service tests — ACL computation and search result structure.

Tests cover:
- ACL computation for different channel types
- Search result data structure

Note: knowledge_service imports from app.database which needs asyncpg.
Tests are marked to skip if asyncpg is not available.
"""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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

    def test_group_dm_channel_acl(self):
        """Group DMs are not treated as public content."""
        from app.services.knowledge_service import compute_acl_for_channel

        channel = self._make_channel(ChannelType.GROUP_DM, slack_id="G123")
        acl = compute_acl_for_channel(channel)

        assert acl.acl_type == ACLType.EXPLICIT
        assert acl.confidentiality == Confidentiality.CONFIDENTIAL
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
            source_channel_name="backend",
            source_created_at=datetime.now(timezone.utc),
            source_author_external_id="U123",
            source_thread_id="1716382103.001234",
            source_permalink="https://example.slack.com/archives/C123/p1716382103",
        )

        assert result.score == 0.95
        assert result.source_type == "message"
        assert result.content == "Test content about auth migration"
        assert result.chunk_index == 0
        assert result.source_channel_name == "backend"
        assert result.source_author_external_id == "U123"

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


@skip_without_asyncpg
class TestSearchFilters:
    """Tests for workspace and source-time search filtering."""

    @pytest.mark.asyncio
    async def test_missing_workspace_fails_closed(self):
        """Search should not embed or query when workspace scope is missing."""
        from app.services.knowledge_service import KnowledgeService

        service = KnowledgeService()
        with patch("app.services.knowledge_service.embedding_service") as mock_embed:
            result = await service.search(
                query="auth",
                workspace_id=None,  # type: ignore[arg-type]
                user_channel_uuids=[uuid.uuid4()],
                user_id=uuid.uuid4(),
            )

        assert result == []
        mock_embed.embed_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_maps_source_metadata(self):
        """Search results include source metadata used for citations."""
        from app.models.embedding import SourceType
        from app.services.knowledge_service import KnowledgeService

        service = KnowledgeService()
        workspace_id = uuid.uuid4()
        source_created_at = datetime.now(timezone.utc) - timedelta(hours=1)
        row = SimpleNamespace(
            id=uuid.uuid4(),
            content="Auth rollout was discussed",
            source_type=SourceType.MESSAGE,
            source_id=uuid.uuid4(),
            source_channel_id="C123",
            source_channel_uuid=uuid.uuid4(),
            source_channel_name="backend",
            source_created_at=source_created_at,
            source_updated_at=source_created_at,
            source_author_id=uuid.uuid4(),
            source_author_external_id="U123",
            source_author_display_name="Priya",
            source_thread_id="1716382103.001234",
            source_permalink=None,
            chunk_index=0,
            distance=0.2,
        )

        with (
            patch("app.services.knowledge_service.embedding_service") as mock_embed,
            patch("app.services.knowledge_service.AsyncSessionLocal") as mock_factory,
            patch("app.services.knowledge_service.event_bus") as mock_bus,
        ):
            mock_embed.embed_query = AsyncMock(return_value=[0.1, 0.2])
            session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
            db_result = MagicMock()
            db_result.all.return_value = [row]
            session.execute = AsyncMock(return_value=db_result)
            mock_bus.publish = AsyncMock()

            results = await service.search(
                query="auth",
                workspace_id=workspace_id,
                user_channel_uuids=[uuid.uuid4()],
                user_id=uuid.uuid4(),
                since=source_created_at - timedelta(hours=1),
                until=source_created_at + timedelta(hours=1),
                top_k=5,
            )

        assert len(results) == 1
        assert results[0].source_channel_name == "backend"
        assert results[0].source_created_at == source_created_at
        assert results[0].source_author_display_name == "Priya"
        query_text = str(session.execute.call_args.args[0])
        assert "workspace_id" in query_text
        assert "source_created_at" in query_text


@skip_without_asyncpg
class TestChannelACLRevalidation:
    """Tests for channel ACL reclassification lifecycle."""

    @pytest.mark.asyncio
    async def test_revalidate_channel_acl_updates_existing_chunks(self):
        """Public/private channel changes should update chunk ACL metadata."""
        from app.services.knowledge_service import KnowledgeService

        service = KnowledgeService()
        workspace_id = uuid.uuid4()
        channel_id = uuid.uuid4()
        channel = SimpleNamespace(
            id=channel_id,
            workspace_id=workspace_id,
            slack_channel_id="C123",
            channel_type=ChannelType.PRIVATE,
        )
        update_result = MagicMock()
        update_result.rowcount = 4

        with patch("app.services.knowledge_service.AsyncSessionLocal") as mock_factory:
            session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
            session.get = AsyncMock(return_value=channel)
            session.execute = AsyncMock(return_value=update_result)
            session.commit = AsyncMock()

            result = await service.revalidate_channel_acl(
                channel_id,
                workspace_id=workspace_id,
            )

        assert result["action"] == "updated_acl"
        assert result["updated"] == 4
        session.commit.assert_awaited_once()
        query_text = str(session.execute.call_args.args[0])
        assert "document_chunks" in query_text
        assert "acl_last_verified" in query_text

    @pytest.mark.asyncio
    async def test_revalidate_channel_acl_deletes_group_dm_chunks(self):
        """DM/group-DM channel changes should remove indexed chunks."""
        from app.services.knowledge_service import KnowledgeService

        service = KnowledgeService()
        workspace_id = uuid.uuid4()
        channel_id = uuid.uuid4()
        channel = SimpleNamespace(
            id=channel_id,
            workspace_id=workspace_id,
            slack_channel_id="G123",
            channel_type=ChannelType.GROUP_DM,
        )
        delete_result = MagicMock()
        delete_result.rowcount = 2

        with patch("app.services.knowledge_service.AsyncSessionLocal") as mock_factory:
            session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
            session.get = AsyncMock(return_value=channel)
            session.execute = AsyncMock(return_value=delete_result)
            session.commit = AsyncMock()

            result = await service.revalidate_channel_acl(
                channel_id,
                workspace_id=workspace_id,
            )

        assert result["action"] == "deleted_dm_chunks"
        assert result["deleted"] == 2
        query_text = str(session.execute.call_args.args[0])
        assert "DELETE FROM document_chunks" in query_text
