"""Versioned platform-neutral event payload helpers."""

import uuid
from typing import Any

from app.models.identity import Platform

EVENT_SCHEMA_VERSION = 1


def normalized_payload(
    *,
    platform: Platform,
    workspace_id: uuid.UUID,
    workspace_integration_id: uuid.UUID | None,
    external_metadata: dict[str, Any] | None = None,
    **entity_ids: uuid.UUID | None,
) -> dict[str, Any]:
    """Build a JSON-safe normalized event payload containing internal IDs."""
    payload: dict[str, Any] = {
        "schema_version": EVENT_SCHEMA_VERSION,
        "platform": platform.value,
        "workspace_id": str(workspace_id),
        "workspace_integration_id": (
            str(workspace_integration_id) if workspace_integration_id else None
        ),
        "external_metadata": external_metadata or {},
    }
    payload.update(
        {
            key: str(value) if value is not None else None
            for key, value in entity_ids.items()
        }
    )
    return payload
