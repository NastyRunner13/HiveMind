"""
HiveMind Database Models — Base class and model registry.

All models inherit from Base and are imported here so that
Alembic can discover them for migration auto-generation.
"""

from app.models.base import Base
from app.models.channel import Channel
from app.models.digest import Digest
from app.models.embedding import DocumentChunk
from app.models.file_metadata import FileMetadata
from app.models.identity import (
    AuthIdentity,
    Platform,
    User,
    UserPlatformMapping,
    WorkspaceIntegration,
)
from app.models.membership import ChannelMembership
from app.models.message import Message
from app.models.user import SlackUser
from app.models.workspace import Workspace
from app.models.agent_session import AgentSession, AgentMessage

__all__ = [
    "Base",
    "Workspace",
    "Channel",
    "SlackUser",
    "Message",
    "FileMetadata",
    "Platform",
    "User",
    "WorkspaceIntegration",
    "UserPlatformMapping",
    "AuthIdentity",
    "DocumentChunk",
    "Digest",
    "ChannelMembership",
    "AgentSession",
    "AgentMessage",
]
