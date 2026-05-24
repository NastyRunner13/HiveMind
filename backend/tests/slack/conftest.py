"""
Shared pytest fixtures for HiveMind Slack tests.

Provides mocked Slack clients, settings, database sessions, and
sample event payloads so unit tests never hit real APIs or databases.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

# ═════════════════════════════════════════════════════════════════
# SETTINGS FIXTURES
# ═════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_settings():
    """Return a mock Settings object with Slack credentials configured."""
    settings = MagicMock()
    settings.slack_bot_token = "xoxb-test-token"
    settings.slack_signing_secret = "test-signing-secret"
    settings.slack_app_token = "xapp-test-app-token"
    settings.slack_socket_mode = True
    settings.slack_configured = True
    settings.is_development = True
    settings.app_env = "development"
    settings.app_name = "HiveMind"
    settings.app_version = "0.1.0"
    settings.log_level = "INFO"
    return settings


@pytest.fixture
def mock_settings_no_slack():
    """Return a mock Settings with no Slack credentials."""
    settings = MagicMock()
    settings.slack_bot_token = ""
    settings.slack_signing_secret = ""
    settings.slack_app_token = ""
    settings.slack_socket_mode = True
    settings.slack_configured = False
    return settings


# ═════════════════════════════════════════════════════════════════
# SLACK CLIENT FIXTURES
# ═════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_slack_client():
    """
    Return a mocked AsyncWebClient with pre-canned responses.

    All API methods return realistic Slack API response shapes.
    """
    client = AsyncMock()

    # auth.test
    client.auth_test.return_value = {
        "ok": True,
        "url": "https://test-workspace.slack.com/",
        "team": "Test Workspace",
        "user": "hivemind",
        "team_id": "T_TEST_TEAM",
        "user_id": "U_BOT_USER",
        "bot_id": "B_BOT_ID",
    }

    # conversations.list
    client.conversations_list.return_value = {
        "ok": True,
        "channels": [
            {
                "id": "C_GENERAL",
                "name": "general",
                "is_private": False,
                "is_archived": False,
                "num_members": 10,
                "topic": {"value": "General chat"},
                "purpose": {"value": "Company-wide announcements"},
            },
            {
                "id": "C_HIVEMIND_TEST",
                "name": "hivemind-test",
                "is_private": False,
                "is_archived": False,
                "num_members": 3,
                "topic": {"value": "Testing HiveMind"},
                "purpose": {"value": "Test channel for HiveMind bot"},
            },
        ],
        "response_metadata": {"next_cursor": ""},
    }

    # conversations.history
    client.conversations_history.return_value = {
        "ok": True,
        "messages": [
            {
                "type": "message",
                "user": "U_TESTUSER1",
                "text": "Hello from HiveMind test!",
                "ts": "1716500000.000100",
                "thread_ts": None,
            },
            {
                "type": "message",
                "user": "U_TESTUSER2",
                "text": "Testing 1-2-3",
                "ts": "1716499900.000200",
                "thread_ts": None,
            },
        ],
        "has_more": False,
        "response_metadata": {"next_cursor": ""},
    }

    # users.list
    client.users_list.return_value = {
        "ok": True,
        "members": [
            {
                "id": "U_TESTUSER1",
                "name": "testuser1",
                "real_name": "Test User One",
                "is_bot": False,
                "is_admin": False,
                "is_owner": False,
                "deleted": False,
                "tz": "Asia/Kolkata",
                "profile": {
                    "display_name": "testuser1",
                    "real_name": "Test User One",
                    "email": "test1@example.com",
                    "image_72": "https://example.com/avatar1.png",
                    "status_text": "",
                    "title": "Developer",
                },
            },
            {
                "id": "USLACKBOT",
                "name": "slackbot",
                "real_name": "Slackbot",
                "is_bot": True,
                "deleted": False,
                "profile": {
                    "display_name": "Slackbot",
                    "real_name": "Slackbot",
                },
            },
        ],
        "response_metadata": {"next_cursor": ""},
    }

    # files.info
    client.files_info.return_value = {
        "ok": True,
        "file": {
            "id": "F_TESTFILE",
            "name": "test_doc.pdf",
            "title": "Test Document",
            "filetype": "pdf",
            "mimetype": "application/pdf",
            "size": 12345,
            "user": "U_TESTUSER1",
            "url_private": "https://files.slack.com/test_doc.pdf",
            "permalink": "https://test-workspace.slack.com/files/test_doc.pdf",
            "created": 1716500000,
            "is_external": False,
            "shares": {"public": {"C_GENERAL": [{}]}},
        },
    }

    # files.list
    client.files_list.return_value = {
        "ok": True,
        "files": [
            {
                "id": "F_TESTFILE",
                "name": "test_doc.pdf",
                "title": "Test Document",
                "filetype": "pdf",
                "mimetype": "application/pdf",
                "size": 12345,
                "user": "U_TESTUSER1",
                "url_private": "https://files.slack.com/test_doc.pdf",
                "permalink": "https://test-workspace.slack.com/files/test_doc.pdf",
                "created": 1716500000,
                "is_external": False,
                "shares": {"public": {"C_GENERAL": [{}]}},
            },
        ],
        "paging": {"pages": 1, "page": 1},
    }

    # chat.postMessage
    client.chat_postMessage.return_value = {
        "ok": True,
        "channel": "C_HIVEMIND_TEST",
        "ts": "1716500100.000300",
        "message": {
            "text": "Test message from HiveMind",
            "ts": "1716500100.000300",
        },
    }

    return client


# ═════════════════════════════════════════════════════════════════
# SAMPLE EVENT PAYLOADS
# ═════════════════════════════════════════════════════════════════


@pytest.fixture
def sample_message_event():
    """A typical Slack message event."""
    return {
        "type": "message",
        "channel": "C_GENERAL",
        "user": "U_TESTUSER1",
        "text": "Hello, this is a test message!",
        "ts": "1716500000.000100",
        "thread_ts": None,
        "team": "T_TEST_TEAM",
    }


@pytest.fixture
def sample_bot_message_event():
    """A message from a bot."""
    return {
        "type": "message",
        "subtype": "bot_message",
        "channel": "C_GENERAL",
        "bot_id": "B_OTHER_BOT",
        "text": "Automated notification",
        "ts": "1716500001.000200",
    }


@pytest.fixture
def sample_deleted_message_event():
    """A message_deleted event (should be skipped)."""
    return {
        "type": "message",
        "subtype": "message_deleted",
        "channel": "C_GENERAL",
        "ts": "1716500002.000300",
        "deleted_ts": "1716500000.000100",
    }


@pytest.fixture
def sample_channel_join_event():
    """A channel_join event (should be skipped)."""
    return {
        "type": "message",
        "subtype": "channel_join",
        "channel": "C_GENERAL",
        "user": "U_TESTUSER1",
        "text": "<@U_TESTUSER1> has joined the channel",
        "ts": "1716500003.000400",
    }


@pytest.fixture
def sample_file_shared_event():
    """A file_shared event."""
    return {
        "type": "file_shared",
        "file_id": "F_TESTFILE",
        "channel_id": "C_GENERAL",
        "user_id": "U_TESTUSER1",
    }


@pytest.fixture
def sample_channel_created_event():
    """A channel_created event."""
    return {
        "type": "channel_created",
        "channel": {
            "id": "C_NEWCHANNEL",
            "name": "new-project",
            "creator": "U_TESTUSER1",
        },
    }


@pytest.fixture
def sample_channel_rename_event():
    """A channel_rename event."""
    return {
        "type": "channel_rename",
        "channel": {
            "id": "C_GENERAL",
            "name": "general-renamed",
        },
    }


@pytest.fixture
def sample_channel_archive_event():
    """A channel_archive event."""
    return {
        "type": "channel_archive",
        "channel": "C_GENERAL",
        "user": "U_TESTUSER1",
    }


@pytest.fixture
def sample_channel_unarchive_event():
    """A channel_unarchive event."""
    return {
        "type": "channel_unarchive",
        "channel": "C_GENERAL",
        "user": "U_TESTUSER1",
    }


@pytest.fixture
def sample_app_mention_event():
    """An app_mention event (someone @mentioned the bot)."""
    return {
        "type": "app_mention",
        "user": "U_TESTUSER1",
        "text": "<@U_BOT_USER> what's the latest update?",
        "ts": "1716500010.000500",
        "channel": "C_GENERAL",
        "thread_ts": None,
    }


@pytest.fixture
def sample_team_join_event():
    """A team_join event (new user joins workspace)."""
    return {
        "type": "team_join",
        "user": {
            "id": "U_NEWUSER",
            "name": "newuser",
            "real_name": "New User",
            "is_bot": False,
            "is_admin": False,
            "is_owner": False,
            "deleted": False,
            "tz": "Asia/Kolkata",
            "profile": {
                "display_name": "newuser",
                "real_name": "New User",
                "email": "newuser@example.com",
                "image_72": "https://example.com/avatar_new.png",
                "status_text": "",
                "title": "Intern",
            },
        },
    }


@pytest.fixture
def sample_message_changed_event():
    """A message_changed event (message was edited)."""
    return {
        "type": "message",
        "subtype": "message_changed",
        "channel": "C_GENERAL",
        "message": {
            "user": "U_TESTUSER1",
            "text": "Hello, this is the EDITED message!",
            "ts": "1716500000.000100",
            "edited": {
                "user": "U_TESTUSER1",
                "ts": "1716500050.000000",
            },
        },
        "previous_message": {
            "user": "U_TESTUSER1",
            "text": "Hello, this is a test message!",
            "ts": "1716500000.000100",
        },
    }


@pytest.fixture
def sample_member_joined_event():
    """A member_joined_channel event."""
    return {
        "type": "member_joined_channel",
        "user": "U_TESTUSER1",
        "channel": "C_GENERAL",
        "team": "T_TEST_TEAM",
    }
