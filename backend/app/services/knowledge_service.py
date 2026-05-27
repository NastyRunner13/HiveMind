"""
Knowledge Service — the Knowledge Fabric core for HiveMind.

This service manages the semantic search pipeline:
1. Indexing: chunk content → embed → store with ACL metadata
2. Search: embed query → vector search with ACL filtering → return results

Security model (from v3 concept):
- Layer 1: ACL metadata is attached at ingestion time
- Layer 2: Every search query includes DB-level ACL filters
- Layer 3: Post-retrieval verification (future — OBO token exchange)

ACL filters use PostgreSQL array overlap operators to restrict results
at the database level, not post-query. This prevents information leakage
even through similarity scores or timing attacks.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import and_, delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.events.bus import EventType, event_bus
from app.models.channel import Channel, ChannelType
from app.models.embedding import (
    ACLType,
    Confidentiality,
    DocumentChunk,
    SourceType,
)
from app.models.message import Message
from app.services.embedding_service import embedding_service

logger = logging.getLogger(__name__)
settings = get_settings()


# ═════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═════════════════════════════════════════════════════════════════


@dataclass
class ACLMetadata:
    """Access control metadata for a document chunk."""

    acl_type: ACLType
    allowed_channel_ids: list[str] | None = None
    allowed_user_ids: list[str] | None = None
    source_channel_id: str | None = None
    confidentiality: Confidentiality = Confidentiality.INTERNAL


@dataclass
class SearchResult:
    """A single search result with source attribution."""

    chunk_id: uuid.UUID
    content: str
    score: float
    source_type: str
    source_id: uuid.UUID
    source_channel_id: str | None
    chunk_index: int


# ═════════════════════════════════════════════════════════════════
# ACL COMPUTATION
# ═════════════════════════════════════════════════════════════════


def compute_acl_for_channel(channel: Channel) -> ACLMetadata:
    """
    Derive ACL metadata from the channel where content originated.

    Public channels → anyone in org can see
    Private channels → only channel members
    DMs → only the DM participants (indexed only with consent)
    """
    if channel.channel_type == ChannelType.DM:
        return ACLMetadata(
            acl_type=ACLType.EXPLICIT,
            source_channel_id=channel.slack_channel_id,
            confidentiality=Confidentiality.CONFIDENTIAL,
        )
    elif channel.channel_type == ChannelType.PRIVATE:
        return ACLMetadata(
            acl_type=ACLType.CHANNEL,
            allowed_channel_ids=[channel.slack_channel_id],
            source_channel_id=channel.slack_channel_id,
            confidentiality=Confidentiality.INTERNAL,
        )
    else:
        # Public channels — accessible to all org members
        return ACLMetadata(
            acl_type=ACLType.PUBLIC,
            allowed_channel_ids=[channel.slack_channel_id],
            source_channel_id=channel.slack_channel_id,
            confidentiality=Confidentiality.PUBLIC,
        )


# ═════════════════════════════════════════════════════════════════
# INDEXING
# ═════════════════════════════════════════════════════════════════


class KnowledgeService:
    """
    Knowledge Fabric — indexing and semantic search with ACL awareness.

    Usage:
        service = KnowledgeService()
        await service.index_message(message, channel)
        results = await service.search("auth migration", user_channel_ids=["C123"])
    """

    async def index_message(
        self,
        message: Message,
        channel: Channel,
    ) -> int:
        """
        Index a message into the Knowledge Fabric.

        Chunks the message content, generates embeddings, and stores
        them with ACL metadata derived from the channel.

        Args:
            message: The message to index.
            channel: The channel the message belongs to.

        Returns:
            Number of chunks created.
        """
        if not message.content or not message.content.strip():
            return 0

        # Skip very short messages (single words, reactions, etc.)
        if len(message.content.strip()) < 20:
            return 0

        acl = compute_acl_for_channel(channel)
        chunks_with_counts = embedding_service.chunk_and_count(message.content)

        if not chunks_with_counts:
            return 0

        # Embed all chunks in one batch
        chunk_texts = [c[0] for c in chunks_with_counts]

        try:
            embeddings = await embedding_service.embed_texts(chunk_texts)
        except Exception as e:
            logger.error(f"Failed to embed message {message.id}: {e}")
            return 0

        # Store chunks with embeddings and ACL metadata
        async with AsyncSessionLocal() as session:
            for i, ((chunk_text, token_count), embedding) in enumerate(
                zip(chunks_with_counts, embeddings)
            ):
                chunk = DocumentChunk(
                    workspace_id=message.workspace_id,
                    source_type=SourceType.MESSAGE,
                    source_id=message.id,
                    chunk_index=i,
                    content=chunk_text,
                    embedding=embedding,
                    token_count=token_count,
                    acl_type=acl.acl_type,
                    allowed_channel_ids=acl.allowed_channel_ids,
                    allowed_user_ids=acl.allowed_user_ids,
                    source_channel_id=acl.source_channel_id,
                    confidentiality=acl.confidentiality,
                    acl_last_verified=datetime.now(timezone.utc),
                )
                session.add(chunk)

            await session.commit()

        await event_bus.publish(EventType.DOCUMENT_INDEXED, {
            "source_type": "message",
            "source_id": str(message.id),
            "chunks_created": len(chunks_with_counts),
        })

        logger.debug(
            f"Indexed message {message.id}: "
            f"{len(chunks_with_counts)} chunks"
        )
        return len(chunks_with_counts)

    async def index_file_content(
        self,
        file_id: uuid.UUID,
        workspace_id: uuid.UUID,
        content: str,
        channel: Channel | None = None,
    ) -> int:
        """
        Index file content into the Knowledge Fabric.

        Called when file content is fetched on-demand for a user query,
        or during batch indexing of file content.

        Args:
            file_id: The file_metadata.id to reference.
            workspace_id: The workspace this file belongs to.
            content: The extracted text content of the file.
            channel: The channel where the file was shared (for ACL).

        Returns:
            Number of chunks created.
        """
        if not content or not content.strip():
            return 0

        # Determine ACL
        if channel:
            acl = compute_acl_for_channel(channel)
        else:
            acl = ACLMetadata(
                acl_type=ACLType.PUBLIC,
                confidentiality=Confidentiality.INTERNAL,
            )

        chunks_with_counts = embedding_service.chunk_and_count(content)
        if not chunks_with_counts:
            return 0

        chunk_texts = [c[0] for c in chunks_with_counts]

        try:
            embeddings = await embedding_service.embed_texts(chunk_texts)
        except Exception as e:
            logger.error(f"Failed to embed file {file_id}: {e}")
            return 0

        async with AsyncSessionLocal() as session:
            for i, ((chunk_text, token_count), embedding) in enumerate(
                zip(chunks_with_counts, embeddings)
            ):
                chunk = DocumentChunk(
                    workspace_id=workspace_id,
                    source_type=SourceType.FILE,
                    source_id=file_id,
                    chunk_index=i,
                    content=chunk_text,
                    embedding=embedding,
                    token_count=token_count,
                    acl_type=acl.acl_type,
                    allowed_channel_ids=acl.allowed_channel_ids,
                    allowed_user_ids=acl.allowed_user_ids,
                    source_channel_id=acl.source_channel_id,
                    confidentiality=acl.confidentiality,
                    acl_last_verified=datetime.now(timezone.utc),
                )
                session.add(chunk)

            await session.commit()

        await event_bus.publish(EventType.DOCUMENT_INDEXED, {
            "source_type": "file",
            "source_id": str(file_id),
            "chunks_created": len(chunks_with_counts),
        })

        return len(chunks_with_counts)

    # ═════════════════════════════════════════════════════════════
    # SEMANTIC SEARCH
    # ═════════════════════════════════════════════════════════════

    async def search(
        self,
        query: str,
        user_channel_ids: list[str] | None = None,
        user_slack_id: str | None = None,
        workspace_id: uuid.UUID | None = None,
        top_k: int = 10,
    ) -> list[SearchResult]:
        """
        Semantic search with ACL filtering at the database level.

        The ACL filter is applied as a WHERE clause in the SQL query,
        not post-retrieval. This prevents information leakage through
        similarity scores or timing attacks.

        Args:
            query: The natural language search query.
            user_channel_ids: Slack channel IDs the user is a member of.
            user_slack_id: The user's Slack ID (for explicit access checks).
            workspace_id: Limit search to a specific workspace.
            top_k: Number of results to return.

        Returns:
            List of SearchResult objects with relevance scores.
        """
        # Embed the query
        try:
            query_embedding = await embedding_service.embed_query(query)
        except Exception as e:
            logger.error(f"Failed to embed search query: {e}")
            return []

        async with AsyncSessionLocal() as session:
            # Build the ACL filter (OR conditions — user can see if ANY match)
            acl_conditions = [
                # Condition 1: Public content
                DocumentChunk.confidentiality == Confidentiality.PUBLIC,
            ]

            if user_channel_ids:
                # Condition 2: User is a member of the source channel
                acl_conditions.append(
                    DocumentChunk.source_channel_id.in_(user_channel_ids)
                )
                # Condition 3: Channel is in the allowed list
                acl_conditions.append(
                    DocumentChunk.allowed_channel_ids.overlap(user_channel_ids)
                )

            if user_slack_id:
                # Condition 4: User has explicit access
                acl_conditions.append(
                    DocumentChunk.allowed_user_ids.contains([user_slack_id])
                )

            # Build the query with ACL filter and vector similarity
            stmt = (
                select(
                    DocumentChunk.id,
                    DocumentChunk.content,
                    DocumentChunk.source_type,
                    DocumentChunk.source_id,
                    DocumentChunk.source_channel_id,
                    DocumentChunk.chunk_index,
                    DocumentChunk.embedding.cosine_distance(query_embedding).label(
                        "distance"
                    ),
                )
                .where(
                    and_(
                        or_(*acl_conditions),
                        DocumentChunk.embedding.isnot(None),
                        (
                            DocumentChunk.workspace_id == workspace_id
                            if workspace_id
                            else True
                        ),
                    )
                )
                .order_by("distance")
                .limit(top_k)
            )

            result = await session.execute(stmt)
            rows = result.all()

            results = []
            for row in rows:
                # Convert cosine distance to similarity score (1 - distance)
                similarity = 1.0 - (row.distance or 0.0)
                results.append(
                    SearchResult(
                        chunk_id=row.id,
                        content=row.content,
                        score=round(similarity, 4),
                        source_type=row.source_type.value if row.source_type else "unknown",
                        source_id=row.source_id,
                        source_channel_id=row.source_channel_id,
                        chunk_index=row.chunk_index,
                    )
                )

            await event_bus.publish(EventType.SEARCH_PERFORMED, {
                "query_length": len(query),
                "results_count": len(results),
                "user_slack_id": user_slack_id,
            })

            return results

    async def get_indexing_status(
        self, workspace_id: uuid.UUID | None = None
    ) -> dict:
        """Get stats about the indexing state of the Knowledge Fabric."""
        async with AsyncSessionLocal() as session:
            base_query = select(func.count(DocumentChunk.id))
            if workspace_id:
                base_query = base_query.where(
                    DocumentChunk.workspace_id == workspace_id
                )

            total_chunks = (await session.execute(base_query)).scalar() or 0

            # Count by source type
            type_counts = {}
            for source_type in SourceType:
                count_query = base_query.where(
                    DocumentChunk.source_type == source_type
                )
                count = (await session.execute(count_query)).scalar() or 0
                type_counts[source_type.value] = count

            return {
                "total_chunks": total_chunks,
                "by_source_type": type_counts,
                "embedding_model": settings.embedding_model,
                "embedding_dimensions": settings.embedding_dimensions,
            }

    # ═════════════════════════════════════════════════════════════
    # IDEMPOTENCY HELPERS
    # ═════════════════════════════════════════════════════════════

    async def is_already_indexed(self, source_id: uuid.UUID) -> bool:
        """
        Check if a source has already been indexed into document_chunks.

        Used by the event consumer to avoid double-indexing the same
        message when an event is re-delivered.

        Args:
            source_id: The UUID of the source record (message.id or file.id).

        Returns:
            True if at least one chunk exists for this source.
        """
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(func.count(DocumentChunk.id)).where(
                    DocumentChunk.source_id == source_id
                )
            )
            return (result.scalar() or 0) > 0

    async def delete_chunks_for_source(self, source_id: uuid.UUID) -> int:
        """
        Delete all chunks for a source (for re-indexing edited messages).

        Args:
            source_id: The UUID of the source record.

        Returns:
            Number of chunks deleted.
        """
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                delete(DocumentChunk).where(
                    DocumentChunk.source_id == source_id
                )
            )
            await session.commit()
            return result.rowcount


# ── Module-level singleton ──────────────────────────────────────
knowledge_service = KnowledgeService()
