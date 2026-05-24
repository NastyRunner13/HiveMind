"""
LIVE Integration Tests -- hits the REAL Slack API.

These tests use your actual Slack credentials from .env to verify
that the bot can connect, read channels, read messages, post messages,
and list users in your workspace.

Run separately:
    python -m pytest tests/slack/test_live.py -v -s

The -s flag is important: it shows print() output so you can see
the actual data coming back from Slack.

Prerequisites:
    1. .env must have valid SLACK_BOT_TOKEN
    2. A #hivemind-test channel must exist
    3. The bot must be invited to #hivemind-test
    4. At least one message must be in #hivemind-test
"""

import os
import sys
from datetime import datetime, timezone

import pytest

# Ensure we can import from app
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from dotenv import load_dotenv

load_dotenv()

# -- Config --
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
TEST_CHANNEL_NAME = "hivemind-test"
BOT_DISPLAY_NAME = "HiveMind"

# Skip all tests in this file if no Slack token is configured
pytestmark = pytest.mark.skipif(
    not SLACK_BOT_TOKEN or not SLACK_BOT_TOKEN.startswith("xoxb-"),
    reason="SLACK_BOT_TOKEN not configured -- skipping live tests",
)


# -- Shared client fixture --
@pytest.fixture(scope="module")
def slack_client():
    """Create a real AsyncWebClient for the test session."""
    from slack_sdk.web.async_client import AsyncWebClient

    return AsyncWebClient(token=SLACK_BOT_TOKEN)


# Store channel ID across tests
_test_channel_id = None


# =================================================================
# TEST 1: Auth Verification
# =================================================================


@pytest.mark.asyncio
async def test_01_auth_test(slack_client):
    """
    Verify the bot token is valid by calling auth.test.

    This is the most fundamental test -- if this fails, nothing else
    will work. Prints bot identity and workspace info.
    """
    result = await slack_client.auth_test()

    assert result["ok"] is True, f"auth.test failed: {result.get('error')}"

    print("\n" + "=" * 60)
    print("[PASS] AUTH TEST PASSED")
    print("=" * 60)
    print(f"  Bot User:      {result.get('user')}")
    print(f"  Bot User ID:   {result.get('user_id')}")
    print(f"  Team:          {result.get('team')}")
    print(f"  Team ID:       {result.get('team_id')}")
    print(f"  Workspace URL: {result.get('url')}")
    print("=" * 60)


# =================================================================
# TEST 2: List Channels
# =================================================================


@pytest.mark.asyncio
async def test_02_list_channels(slack_client):
    """
    Verify we can list channels the bot has access to.
    Prints all visible channels.
    """
    result = await slack_client.conversations_list(
        types="public_channel,private_channel",
        limit=100,
    )

    assert result["ok"] is True, f"conversations.list failed: {result.get('error')}"

    channels = result.get("channels", [])
    assert len(channels) > 0, "No channels found -- is the bot in any channels?"

    print("\n" + "=" * 60)
    print(f"[PASS] CHANNELS FOUND: {len(channels)}")
    print("=" * 60)
    for ch in channels:
        archived = " [ARCHIVED]" if ch.get("is_archived") else ""
        private = " [PRIVATE]" if ch.get("is_private") else ""
        members = ch.get("num_members", "?")
        print(
            f"  #{ch['name']:<30} (ID: {ch['id']}) "
            f"members: {members}{private}{archived}"
        )
    print("=" * 60)


# =================================================================
# TEST 3: Find Test Channel
# =================================================================


@pytest.mark.asyncio
async def test_03_find_test_channel(slack_client):
    """
    Find the #hivemind-test channel specifically.
    Stores its ID for subsequent tests.
    """
    global _test_channel_id

    result = await slack_client.conversations_list(
        types="public_channel,private_channel",
        limit=200,
    )
    assert result["ok"] is True

    channels = result.get("channels", [])
    test_channel = next(
        (ch for ch in channels if ch["name"] == TEST_CHANNEL_NAME),
        None,
    )

    assert test_channel is not None, (
        f"Channel #{TEST_CHANNEL_NAME} not found! Please create it and invite the bot."
    )

    _test_channel_id = test_channel["id"]

    print("\n" + "=" * 60)
    print(f"[PASS] TEST CHANNEL FOUND: #{TEST_CHANNEL_NAME}")
    print("=" * 60)
    print(f"  Channel ID:   {_test_channel_id}")
    print(f"  Members:      {test_channel.get('num_members', '?')}")
    print(f"  Topic:        {(test_channel.get('topic') or {}).get('value', 'none')}")
    print(f"  Purpose:      {(test_channel.get('purpose') or {}).get('value', 'none')}")
    print("=" * 60)


# =================================================================
# TEST 4: Read Channel History
# =================================================================


@pytest.mark.asyncio
async def test_04_read_channel_history(slack_client):
    """
    Read message history from #hivemind-test.
    Verifies the bot can actually fetch messages.
    """
    global _test_channel_id

    if not _test_channel_id:
        pytest.skip("Test channel not found in previous test")

    result = await slack_client.conversations_history(
        channel=_test_channel_id,
        limit=10,
    )

    assert result["ok"] is True, (
        f"conversations.history failed: {result.get('error')}. "
        f"Is the bot invited to #{TEST_CHANNEL_NAME}?"
    )

    messages = result.get("messages", [])

    print("\n" + "=" * 60)
    print(f"[PASS] MESSAGE HISTORY: {len(messages)} messages in #{TEST_CHANNEL_NAME}")
    print("=" * 60)

    if messages:
        for i, msg in enumerate(messages[:10], 1):
            user = msg.get("user", msg.get("bot_id", "system"))
            text = msg.get("text", "")[:80]
            # Replace non-ascii characters for Windows console
            text = text.encode("ascii", errors="replace").decode("ascii")
            ts = msg.get("ts", "0")
            dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            print(f"  [{i}] {dt.strftime('%Y-%m-%d %H:%M:%S')} | {user} | {text}")
    else:
        print("  [WARN] No messages found. Post a message in the channel!")

    print("=" * 60)

    assert len(messages) > 0, (
        f"No messages in #{TEST_CHANNEL_NAME}. Please post at least one message."
    )


# =================================================================
# TEST 5: Post and Read Back a Message
# =================================================================


@pytest.mark.asyncio
async def test_05_post_and_read_message(slack_client):
    """
    Post a timestamped test message to #hivemind-test,
    then read it back to verify write + read works end-to-end.
    """
    global _test_channel_id

    if not _test_channel_id:
        pytest.skip("Test channel not found in previous test")

    # Create a unique test message
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    test_text = f"[TEST] HiveMind Integration Test -- {timestamp}"

    # POST the message
    post_result = await slack_client.chat_postMessage(
        channel=_test_channel_id,
        text=test_text,
    )

    assert post_result["ok"] is True, (
        f"chat.postMessage failed: {post_result.get('error')}"
    )

    posted_ts = post_result["ts"]

    print("\n" + "=" * 60)
    print("[PASS] MESSAGE POSTED")
    print("=" * 60)
    print(f"  Text:     {test_text}")
    print(f"  Channel:  #{TEST_CHANNEL_NAME} ({_test_channel_id})")
    print(f"  TS:       {posted_ts}")

    # Wait a moment for Slack to propagate
    await _async_sleep(1.5)

    # READ it back
    history_result = await slack_client.conversations_history(
        channel=_test_channel_id,
        oldest=posted_ts,
        inclusive=True,
        limit=5,
    )

    assert history_result["ok"] is True

    messages = history_result.get("messages", [])
    found = any(msg.get("ts") == posted_ts for msg in messages)

    print(f"  Read back: {'[OK] Found!' if found else '[FAIL] Not found'}")
    print("=" * 60)

    assert found, (
        f"Posted message (ts={posted_ts}) not found in history. "
        f"Possible Slack propagation delay."
    )


# =================================================================
# TEST 6: List Users
# =================================================================


@pytest.mark.asyncio
async def test_06_list_users(slack_client):
    """
    Verify we can list workspace users.
    Prints all non-bot users.
    """
    result = await slack_client.users_list(limit=100)

    assert result["ok"] is True, f"users.list failed: {result.get('error')}"

    members = result.get("members", [])
    assert len(members) > 0, "No users found in workspace"

    # Filter out slackbot and deactivated
    real_users = [
        m for m in members if m.get("id") != "USLACKBOT" and not m.get("deleted")
    ]

    print("\n" + "=" * 60)
    print(f"[PASS] USERS FOUND: {len(real_users)} active (of {len(members)} total)")
    print("=" * 60)
    for u in real_users[:20]:
        profile = u.get("profile", {})
        name = (
            profile.get("display_name")
            or profile.get("real_name")
            or u.get("name", "?")
        )
        is_bot = " [BOT]" if u.get("is_bot") else ""
        is_admin = " [ADMIN]" if u.get("is_admin") else ""
        email = profile.get("email", "")
        print(f"  {name:<25} (ID: {u['id']}){is_bot}{is_admin}  {email}")
    print("=" * 60)


# =================================================================
# TEST 7: Bot Info Verification
# =================================================================


@pytest.mark.asyncio
async def test_07_bot_info(slack_client):
    """
    Verify the bot's own identity and permissions.
    """
    auth = await slack_client.auth_test()
    assert auth["ok"]

    bot_user_id = auth["user_id"]

    # Fetch the bot's user info
    user_info = await slack_client.users_info(user=bot_user_id)
    assert user_info["ok"] is True

    user = user_info["user"]
    profile = user.get("profile", {})

    print("\n" + "=" * 60)
    print("[PASS] BOT IDENTITY")
    print("=" * 60)
    print(f"  Display Name: {profile.get('display_name', 'N/A')}")
    print(f"  Real Name:    {profile.get('real_name', 'N/A')}")
    print(f"  User ID:      {user['id']}")
    print(f"  Is Bot:       {user.get('is_bot', False)}")
    print(f"  Team ID:      {auth.get('team_id')}")
    print("=" * 60)


# =================================================================
# HELPER
# =================================================================


async def _async_sleep(seconds: float):
    """Async-compatible sleep."""
    import asyncio

    await asyncio.sleep(seconds)
