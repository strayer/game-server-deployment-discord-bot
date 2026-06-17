import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestIsAuthorizedChannel:
    """Tests for the is_authorized_channel function."""

    def test_returns_true_for_allowed_channel(self):
        with patch.dict(
            os.environ,
            {"GUILD_ID": "999", "CHANNEL_IDS": "123,456,789", "BOT_TOKEN": "fake"},
        ):
            # Need to reimport after patching env vars
            from discord_bot import bot

            # Reload to pick up new env vars
            import importlib

            importlib.reload(bot)

            assert bot.is_authorized_channel("123") is True
            assert bot.is_authorized_channel("456") is True
            assert bot.is_authorized_channel("789") is True

    def test_returns_false_for_unauthorized_channel(self):
        with patch.dict(
            os.environ,
            {"GUILD_ID": "999", "CHANNEL_IDS": "123,456", "BOT_TOKEN": "fake"},
        ):
            from discord_bot import bot

            import importlib

            importlib.reload(bot)

            assert bot.is_authorized_channel("999") is False
            assert bot.is_authorized_channel("000") is False


class TestAuthorize:
    """Tests for the authorize async function."""

    @pytest.fixture
    def mock_context(self):
        ctx = MagicMock()
        ctx.channel_id = 123
        ctx.author = MagicMock()
        ctx.author.username = "testuser"
        ctx.command = MagicMock()
        ctx.command.name = "test-command"
        ctx.respond = AsyncMock()
        return ctx

    async def test_authorize_rejects_unauthorized_channel(self, mock_context):
        with patch.dict(
            os.environ,
            {"GUILD_ID": "999", "CHANNEL_IDS": "999", "BOT_TOKEN": "fake"},
        ):
            from discord_bot import bot

            import importlib

            importlib.reload(bot)

            # Channel 123 is not in allowed list (only 999)
            result = await bot.authorize(mock_context)

            assert result is False
            mock_context.respond.assert_called_once()
            call_args = mock_context.respond.call_args[0][0]
            assert "not allowed" in call_args.lower()

    async def test_authorize_accepts_authorized_channel(self, mock_context):
        mock_context.channel_id = 123

        with patch.dict(
            os.environ,
            {"GUILD_ID": "999", "CHANNEL_IDS": "123,456", "BOT_TOKEN": "fake"},
        ):
            from discord_bot import bot

            import importlib

            importlib.reload(bot)

            result = await bot.authorize(mock_context)

            assert result is True
            mock_context.respond.assert_not_called()


class TestCooldown:
    """Tests for the cooldown async function."""

    @pytest.fixture
    def mock_context(self):
        ctx = MagicMock()
        ctx.channel_id = 123
        ctx.author = MagicMock()
        ctx.author.username = "testuser"
        ctx.command = MagicMock()
        ctx.command.name = "test-command"
        ctx.respond = AsyncMock()
        return ctx

    async def test_cooldown_allows_first_request(self, mock_context, patch_db_redis):
        with patch.dict(
            os.environ,
            {"GUILD_ID": "999", "CHANNEL_IDS": "123", "BOT_TOKEN": "fake"},
        ):
            from discord_bot import bot

            import importlib

            importlib.reload(bot)

            result = await bot.cooldown(mock_context, 60)

            assert result is True
            mock_context.respond.assert_not_called()

    async def test_cooldown_blocks_second_request_within_window(
        self, mock_context, patch_db_redis
    ):
        with patch.dict(
            os.environ,
            {"GUILD_ID": "999", "CHANNEL_IDS": "123", "BOT_TOKEN": "fake"},
        ):
            from discord_bot import bot, db

            import importlib

            importlib.reload(bot)

            # First request should pass
            result1 = await bot.cooldown(mock_context, 60)
            assert result1 is True

            # Second request should be blocked
            result2 = await bot.cooldown(mock_context, 60)
            assert result2 is False
            mock_context.respond.assert_called_once()
            call_args = mock_context.respond.call_args[0][0]
            assert "cooldown" in call_args.lower()

    async def test_cooldown_allows_request_after_expiry(
        self, mock_context, patch_db_redis
    ):
        with patch.dict(
            os.environ,
            {"GUILD_ID": "999", "CHANNEL_IDS": "123", "BOT_TOKEN": "fake"},
        ):
            from discord_bot import bot

            import importlib

            importlib.reload(bot)

            # First request
            await bot.cooldown(mock_context, 1)

            # Manually expire the key
            patch_db_redis.delete("cooldown_test-command")

            # Should be allowed again
            mock_context.respond.reset_mock()
            result = await bot.cooldown(mock_context, 60)
            assert result is True
            mock_context.respond.assert_not_called()


class TestQueueIntegrity:
    """Tests for verifying correct jobs are enqueued."""

    @pytest.fixture
    def mock_context(self):
        ctx = MagicMock()
        ctx.channel_id = 123
        ctx.author = MagicMock()
        ctx.author.username = "testuser"
        ctx.command = MagicMock()
        ctx.command.name = "start-valheim"
        ctx.respond = AsyncMock()
        ctx.member = MagicMock()
        ctx.member.display_name = "Test User"
        return ctx

    async def test_start_valheim_enqueues_correct_job(
        self, mock_context, patch_db_redis
    ):
        mock_context.command.name = "start-valheim"

        with patch.dict(
            os.environ,
            {"GUILD_ID": "999", "CHANNEL_IDS": "123", "BOT_TOKEN": "fake"},
        ):
            from discord_bot import bot, jobs

            import importlib

            importlib.reload(bot)

            mock_queue = MagicMock()
            with patch.object(jobs, "get_queue", return_value=mock_queue):
                await bot.start_valheim(mock_context)

                mock_queue.enqueue.assert_called_once_with(jobs.start_valheim_server)

    async def test_stop_valheim_enqueues_correct_job(
        self, mock_context, patch_db_redis
    ):
        mock_context.command.name = "stop-valheim"

        with patch.dict(
            os.environ,
            {"GUILD_ID": "999", "CHANNEL_IDS": "123", "BOT_TOKEN": "fake"},
        ):
            from discord_bot import bot, jobs

            import importlib

            importlib.reload(bot)

            mock_queue = MagicMock()
            with patch.object(jobs, "get_queue", return_value=mock_queue):
                await bot.stop_valheim(mock_context)

                mock_queue.enqueue.assert_called_once_with(jobs.stop_valheim_server)

    async def test_start_factorio_enqueues_correct_job(
        self, mock_context, patch_db_redis
    ):
        mock_context.command.name = "start-factorio"

        with patch.dict(
            os.environ,
            {"GUILD_ID": "999", "CHANNEL_IDS": "123", "BOT_TOKEN": "fake"},
        ):
            from discord_bot import bot, jobs

            import importlib

            importlib.reload(bot)

            mock_queue = MagicMock()
            with patch.object(jobs, "get_queue", return_value=mock_queue):
                await bot.start_factorio(mock_context)

                mock_queue.enqueue.assert_called_once_with(jobs.start_factorio_server)

    async def test_start_enshrouded_enqueues_correct_job(
        self, mock_context, patch_db_redis
    ):
        mock_context.command.name = "start-enshrouded"

        with patch.dict(
            os.environ,
            {"GUILD_ID": "999", "CHANNEL_IDS": "123", "BOT_TOKEN": "fake"},
        ):
            from discord_bot import bot, jobs

            import importlib

            importlib.reload(bot)

            mock_queue = MagicMock()
            with patch.object(jobs, "get_queue", return_value=mock_queue):
                await bot.start_enshrouded(mock_context)

                mock_queue.enqueue.assert_called_once_with(jobs.start_enshrouded_server)

    async def test_start_windrose_enqueues_correct_job(
        self, mock_context, patch_db_redis
    ):
        mock_context.command.name = "start-windrose"

        with patch.dict(
            os.environ,
            {"GUILD_ID": "999", "CHANNEL_IDS": "123", "BOT_TOKEN": "fake"},
        ):
            from discord_bot import bot, jobs

            import importlib

            importlib.reload(bot)

            mock_queue = MagicMock()
            with patch.object(jobs, "get_queue", return_value=mock_queue):
                await bot.start_windrose(mock_context)

                mock_queue.enqueue.assert_called_once_with(jobs.start_windrose_server)

    async def test_stop_windrose_enqueues_correct_job(
        self, mock_context, patch_db_redis
    ):
        mock_context.command.name = "stop-windrose"

        with patch.dict(
            os.environ,
            {"GUILD_ID": "999", "CHANNEL_IDS": "123", "BOT_TOKEN": "fake"},
        ):
            from discord_bot import bot, jobs

            import importlib

            importlib.reload(bot)

            mock_queue = MagicMock()
            with patch.object(jobs, "get_queue", return_value=mock_queue):
                await bot.stop_windrose(mock_context)

                mock_queue.enqueue.assert_called_once_with(jobs.stop_windrose_server)
