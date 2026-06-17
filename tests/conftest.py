import os
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis
import pytest


@pytest.fixture
def fake_redis():
    """Create a fresh FakeRedis instance for each test."""
    return fakeredis.FakeRedis()


@pytest.fixture
def patch_db_redis(fake_redis):
    """Patch the db module's Redis connection with FakeRedis."""
    with patch("discord_bot.db._REDIS", fake_redis):
        yield fake_redis


@pytest.fixture
def mock_slash_context():
    """Create a mock SlashContext for testing bot commands."""
    ctx = MagicMock()
    ctx.channel_id = 123456789
    ctx.author = MagicMock()
    ctx.author.username = "testuser"
    ctx.command = MagicMock()
    ctx.command.name = "start-valheim"
    ctx.respond = AsyncMock()
    ctx.member = MagicMock()
    ctx.member.display_name = "Test User"
    return ctx


@pytest.fixture
def mock_env_vars():
    """Set up required environment variables for testing."""
    env_vars = {
        "GUILD_ID": "999999999",
        "CHANNEL_IDS": "123456789,987654321",
        "BOT_TOKEN": "fake-token",
    }
    with patch.dict(os.environ, env_vars, clear=False):
        yield env_vars


@pytest.fixture
def mock_queue():
    """Create a mock RQ queue."""
    queue = MagicMock()
    queue.enqueue = MagicMock()
    return queue
