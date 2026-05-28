"""Versioned normalized event-payload contract tests."""

import uuid

from app.events.contracts import normalized_payload
from app.models.identity import Platform


def test_normalized_message_payload_contains_internal_ids_and_platform_metadata():
    workspace_id = uuid.uuid4()
    integration_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    message_id = uuid.uuid4()
    sender_id = uuid.uuid4()

    payload = normalized_payload(
        platform=Platform.SLACK,
        workspace_id=workspace_id,
        workspace_integration_id=integration_id,
        channel_id=channel_id,
        message_id=message_id,
        sender_id=sender_id,
        external_metadata={"channel_id": "C024BE91L"},
    )

    assert payload["schema_version"] == 1
    assert payload["platform"] == "slack"
    assert payload["workspace_id"] == str(workspace_id)
    assert payload["message_id"] == str(message_id)
    assert payload["external_metadata"]["channel_id"] == "C024BE91L"
