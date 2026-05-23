"""
HiveMind Database Models — Base class and model registry.

All models inherit from Base and are imported here so that
Alembic can discover them for migration auto-generation.
"""

from app.models.base import Base
from app.models.channel import Channel
from app.models.file_metadata import FileMetadata
from app.models.message import Message
from app.models.user import SlackUser
from app.models.workspace import Workspace

__all__ = [
    "Base",
    "Workspace",
    "Channel",
    "SlackUser",
    "Message",
    "FileMetadata",
]
