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

from sqlalchemy import and_, delete, func, or_, select, update

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
from app.models.file_metadata import FileMetadata
from app.models.message import Message
from app.models.user import SlackUser
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
    allowed_channel_uuids: list[uuid.UUID] | None = None
    allowed_user_uuids: list[uuid.UUID] | None = None
    source_channel_uuid: uuid.UUID | None = None
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
    source_channel_uuid: uuid.UUID | None = None
    source_channel_name: str | None = None
    source_created_at: datetime | None = None
    source_updated_at: datetime | None = None
    source_author_id: uuid.UUID | None = None
    source_author_external_id: str | None = None
    source_author_display_name: str | None = None
    source_thread_id: str | None = None
    source_permalink: str | None = None
    retrieval_method: str = "vector"


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
    if channel.channel_type in (ChannelType.DM, ChannelType.GROUP_DM):
        return ACLMetadata(
            acl_type=ACLType.EXPLICIT,
            source_channel_id=channel.slack_channel_id,
            source_channel_uuid=channel.id,
            confidentiality=Confidentiality.CONFIDENTIAL,
        )
    elif channel.channel_type == ChannelType.PRIVATE:
        return ACLMetadata(
            acl_type=ACLType.CHANNEL,
            allowed_channel_ids=[channel.slack_channel_id],
            source_channel_id=channel.slack_channel_id,
            allowed_channel_uuids=[channel.id],
            source_channel_uuid=channel.id,
            confidentiality=Confidentiality.INTERNAL,
        )
    else:
        # Public channels — accessible to all org members
        return ACLMetadata(
            acl_type=ACLType.PUBLIC,
            allowed_channel_ids=[channel.slack_channel_id],
            source_channel_id=channel.slack_channel_id,
            allowed_channel_uuids=[channel.id],
            source_channel_uuid=channel.id,
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
        results = await service.search(
            "auth migration",
            workspace_id=workspace_id,
            user_channel_ids=["C123"],
        )
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

        if channel.channel_type in (ChannelType.DM, ChannelType.GROUP_DM):
            logger.info(
                "Skipping %s message %s; explicit opt-in indexing is not enabled",
                channel.channel_type.value,
                message.id,
            )
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
            source_author_external_id = None
            if message.sender_id:
                author = await session.get(SlackUser, message.sender_id)
                if author:
                    source_author_external_id = author.slack_user_id

            source_created_at = message.sent_at or message.slack_sent_at
            source_thread_id = message.thread_ts or message.external_thread_id

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
                    allowed_channel_uuids=acl.allowed_channel_uuids,
                    allowed_user_uuids=acl.allowed_user_uuids,
                    source_channel_uuid=acl.source_channel_uuid,
                    source_created_at=source_created_at,
                    source_updated_at=message.updated_at,
                    source_author_id=message.sender_id,
                    source_author_external_id=source_author_external_id,
                    source_thread_id=source_thread_id,
                    source_permalink=None,
                    confidentiality=acl.confidentiality,
                    acl_last_verified=datetime.now(timezone.utc),
                )
                session.add(chunk)

            await session.commit()

        await event_bus.publish(
            EventType.DOCUMENT_INDEXED,
            {
                "source_type": "message",
                "source_id": str(message.id),
                "chunks_created": len(chunks_with_counts),
            },
        )

        logger.debug(f"Indexed message {message.id}: {len(chunks_with_counts)} chunks")
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

        if channel and channel.channel_type in (ChannelType.DM, ChannelType.GROUP_DM):
            logger.info(
                "Skipping file %s shared in %s; explicit opt-in indexing is not enabled",
                file_id,
                channel.channel_type.value,
            )
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
            file_metadata = await session.get(FileMetadata, file_id)
            source_author_external_id = None
            if file_metadata and file_metadata.shared_by_id:
                author = await session.get(SlackUser, file_metadata.shared_by_id)
                if author:
                    source_author_external_id = author.slack_user_id

            source_created_at = None
            source_updated_at = None
            source_author_id = None
            source_permalink = None
            if file_metadata:
                source_created_at = (
                    file_metadata.external_created_at
                    or file_metadata.slack_created_at
                    or file_metadata.created_at
                )
                source_updated_at = file_metadata.updated_at
                source_author_id = file_metadata.shared_by_id
                source_permalink = file_metadata.permalink

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
                    allowed_channel_uuids=acl.allowed_channel_uuids,
                    allowed_user_uuids=acl.allowed_user_uuids,
                    source_channel_uuid=acl.source_channel_uuid,
                    source_created_at=source_created_at,
                    source_updated_at=source_updated_at,
                    source_author_id=source_author_id,
                    source_author_external_id=source_author_external_id,
                    source_thread_id=None,
                    source_permalink=source_permalink,
                    confidentiality=acl.confidentiality,
                    acl_last_verified=datetime.now(timezone.utc),
                )
                session.add(chunk)

            await session.commit()

        await event_bus.publish(
            EventType.DOCUMENT_INDEXED,
            {
                "source_type": "file",
                "source_id": str(file_id),
                "chunks_created": len(chunks_with_counts),
            },
        )

        return len(chunks_with_counts)

    # ═════════════════════════════════════════════════════════════
    # SEMANTIC SEARCH
    # ═════════════════════════════════════════════════════════════

    async def search(
        self,
        query: str,
        *,
        workspace_id: uuid.UUID,
        user_channel_ids: list[str] | None = None,
        user_slack_id: str | None = None,
        user_channel_uuids: list[uuid.UUID] | None = None,
        user_id: uuid.UUID | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        source_types: list[SourceType] | None = None,
        channel_ids: list[uuid.UUID] | None = None,
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
            user_channel_uuids: Internal channel IDs for an authenticated API user.
            user_id: Internal authenticated user ID for explicit access checks.
            workspace_id: Limit search to a specific workspace.
            since: Include only chunks whose source timestamp is at or after this.
            until: Include only chunks whose source timestamp is at or before this.
            source_types: Optional source type filter.
            channel_ids: Optional source channel UUID filter.
            top_k: Number of results to return.

        Returns:
            List of SearchResult objects with relevance scores.
        """
        if not workspace_id:
            logger.warning("Knowledge search denied: missing workspace_id")
            return []

        if since and until and until < since:
            logger.warning("Knowledge search denied: until is before since")
            return []

        top_k = max(1, min(top_k, 50))

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

            if user_channel_uuids:
                acl_conditions.append(
                    DocumentChunk.source_channel_uuid.in_(user_channel_uuids)
                )
                acl_conditions.append(
                    DocumentChunk.allowed_channel_uuids.overlap(user_channel_uuids)
                )

            if user_id:
                acl_conditions.append(
                    DocumentChunk.allowed_user_uuids.contains([user_id])
                )

            filters = [
                DocumentChunk.workspace_id == workspace_id,
                or_(*acl_conditions),
                DocumentChunk.embedding.isnot(None),
                or_(
                    and_(
                        DocumentChunk.source_channel_uuid.is_(None),
                        DocumentChunk.source_channel_id.is_(None),
                    ),
                    Channel.channel_type.notin_([ChannelType.DM, ChannelType.GROUP_DM]),
                ),
            ]
            if since or until:
                filters.append(DocumentChunk.source_created_at.isnot(None))
            if since:
                filters.append(DocumentChunk.source_created_at >= since)
            if until:
                filters.append(DocumentChunk.source_created_at <= until)
            if source_types:
                filters.append(DocumentChunk.source_type.in_(source_types))
            if channel_ids:
                filters.append(DocumentChunk.source_channel_uuid.in_(channel_ids))

            # Build the query with ACL filter and vector similarity
            stmt = (
                select(
                    DocumentChunk.id,
                    DocumentChunk.content,
                    DocumentChunk.source_type,
                    DocumentChunk.source_id,
                    DocumentChunk.source_channel_id,
                    DocumentChunk.source_channel_uuid,
                    Channel.name.label("source_channel_name"),
                    DocumentChunk.source_created_at,
                    DocumentChunk.source_updated_at,
                    DocumentChunk.source_author_id,
                    DocumentChunk.source_author_external_id,
                    SlackUser.display_name.label("source_author_display_name"),
                    DocumentChunk.source_thread_id,
                    DocumentChunk.source_permalink,
                    DocumentChunk.chunk_index,
                    DocumentChunk.embedding.cosine_distance(query_embedding).label(
                        "distance"
                    ),
                )
                .outerjoin(
                    Channel,
                    and_(
                        Channel.workspace_id == DocumentChunk.workspace_id,
                        or_(
                            Channel.id == DocumentChunk.source_channel_uuid,
                            Channel.slack_channel_id == DocumentChunk.source_channel_id,
                        ),
                    ),
                )
                .outerjoin(SlackUser, SlackUser.id == DocumentChunk.source_author_id)
                .where(and_(*filters))
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
                        source_type=row.source_type.value
                        if row.source_type
                        else "unknown",
                        source_id=row.source_id,
                        source_channel_id=row.source_channel_id,
                        chunk_index=row.chunk_index,
                        source_channel_uuid=row.source_channel_uuid,
                        source_channel_name=row.source_channel_name,
                        source_created_at=row.source_created_at,
                        source_updated_at=row.source_updated_at,
                        source_author_id=row.source_author_id,
                        source_author_external_id=row.source_author_external_id,
                        source_author_display_name=row.source_author_display_name,
                        source_thread_id=row.source_thread_id,
                        source_permalink=row.source_permalink,
                        retrieval_method="vector",
                    )
                )

            await event_bus.publish(
                EventType.SEARCH_PERFORMED,
                {
                    "query_length": len(query),
                    "results_count": len(results),
                    "user_slack_id": user_slack_id,
                    "user_id": str(user_id) if user_id else None,
                    "workspace_id": str(workspace_id),
                },
            )

            return results

    async def get_indexing_status(self, workspace_id: uuid.UUID | None = None) -> dict:
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
                count_query = base_query.where(DocumentChunk.source_type == source_type)
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
                delete(DocumentChunk).where(DocumentChunk.source_id == source_id)
            )
            await session.commit()
            return result.rowcount

    async def revalidate_channel_acl(
        self,
        channel_id: uuid.UUID,
        *,
        workspace_id: uuid.UUID | None = None,
    ) -> dict[str, int | str | None]:
        """
        Reclassify existing chunks after channel type or membership changes.

        Channel membership is resolved at query time, so membership events only
        need to refresh ACL verification metadata. Channel type changes can
        change confidentiality and public/private visibility, so chunks are
        updated in place. DM/group-DM chunks are deleted because explicit
        opt-in indexing is not implemented.
        """
        async with AsyncSessionLocal() as session:
            channel = await session.get(Channel, channel_id)
            if not channel:
                return {
                    "channel_id": str(channel_id),
                    "action": "missing_channel",
                    "updated": 0,
                    "deleted": 0,
                }
            if workspace_id and channel.workspace_id != workspace_id:
                return {
                    "channel_id": str(channel_id),
                    "action": "workspace_mismatch",
                    "updated": 0,
                    "deleted": 0,
                }

            chunk_filter = and_(
                DocumentChunk.workspace_id == channel.workspace_id,
                or_(
                    DocumentChunk.source_channel_uuid == channel.id,
                    DocumentChunk.source_channel_id == channel.slack_channel_id,
                ),
            )

            if channel.channel_type in (ChannelType.DM, ChannelType.GROUP_DM):
                result = await session.execute(
                    delete(DocumentChunk).where(chunk_filter)
                )
                await session.commit()
                deleted = result.rowcount or 0
                logger.info(
                    "Deleted %s chunks for %s channel %s during ACL revalidation",
                    deleted,
                    channel.channel_type.value,
                    channel.id,
                )
                return {
                    "channel_id": str(channel.id),
                    "action": "deleted_dm_chunks",
                    "updated": 0,
                    "deleted": deleted,
                }

            acl = compute_acl_for_channel(channel)
            result = await session.execute(
                update(DocumentChunk)
                .where(chunk_filter)
                .values(
                    acl_type=acl.acl_type,
                    allowed_channel_ids=acl.allowed_channel_ids,
                    allowed_user_ids=acl.allowed_user_ids,
                    source_channel_id=acl.source_channel_id,
                    allowed_channel_uuids=acl.allowed_channel_uuids,
                    allowed_user_uuids=acl.allowed_user_uuids,
                    source_channel_uuid=acl.source_channel_uuid,
                    confidentiality=acl.confidentiality,
                    acl_last_verified=datetime.now(timezone.utc),
                )
            )
            await session.commit()
            updated = result.rowcount or 0
            logger.info(
                "Revalidated ACL for %s chunks in channel %s as %s",
                updated,
                channel.id,
                channel.channel_type.value,
            )
            return {
                "channel_id": str(channel.id),
                "action": "updated_acl",
                "updated": updated,
                "deleted": 0,
            }


# ── Module-level singleton ──────────────────────────────────────
knowledge_service = KnowledgeService()
