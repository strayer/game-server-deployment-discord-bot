import pathlib
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from discord_bot import games


class TestGameStartServer:
    """Tests for the Game.start_server method."""

    def test_start_server_calls_correct_script(self):
        with patch("discord_bot.games.subprocess.run") as mock_run:
            games.VALHEIM.start_server()

            mock_run.assert_called_once()
            call_args = mock_run.call_args
            script_path = call_args[0][0][0]

            # Verify it calls start.sh from the scripts directory
            assert script_path.name == "start.sh"
            assert "scripts" in str(script_path)

    def test_start_server_passes_correct_env_variables(self):
        with patch("discord_bot.games.subprocess.run") as mock_run:
            games.VALHEIM.start_server()

            call_kwargs = mock_run.call_args[1]
            env = call_kwargs["env"]

            # Check game-specific env vars
            assert env["GAME_NAME"] == "valheim"
            assert env["GAME_DISPLAY_NAME"] == "Valheim"
            assert "BOT_MESSAGE_SERVER_STARTED" in env
            assert "BOT_MESSAGE_SERVER_READY" in env

    def test_start_server_uses_check_true(self):
        with patch("discord_bot.games.subprocess.run") as mock_run:
            games.VALHEIM.start_server()

            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["check"] is True


class TestGameStopServer:
    """Tests for the Game.stop_server method."""

    def test_stop_server_calls_correct_script(self):
        with patch("discord_bot.games.subprocess.run") as mock_run:
            games.VALHEIM.stop_server()

            mock_run.assert_called_once()
            call_args = mock_run.call_args
            script_path = call_args[0][0][0]

            # Verify it calls teardown.sh from the scripts directory
            assert script_path.name == "teardown.sh"
            assert "scripts" in str(script_path)

    def test_stop_server_passes_correct_env_variables(self):
        with patch("discord_bot.games.subprocess.run") as mock_run:
            games.VALHEIM.stop_server()

            call_kwargs = mock_run.call_args[1]
            env = call_kwargs["env"]

            # Check game-specific env vars
            assert env["GAME_NAME"] == "valheim"
            assert env["GAME_DISPLAY_NAME"] == "Valheim"
            assert "BOT_MESSAGE_STARTED" in env
            assert "BOT_MESSAGE_FINISHED" in env

    def test_stop_server_uses_check_true(self):
        with patch("discord_bot.games.subprocess.run") as mock_run:
            games.VALHEIM.stop_server()

            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["check"] is True


class TestErrorHandling:
    """Tests for error handling in game server operations."""

    def test_start_server_raises_on_subprocess_failure(self):
        with patch("discord_bot.games.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                returncode=1, cmd=["start.sh"]
            )

            with pytest.raises(subprocess.CalledProcessError):
                games.VALHEIM.start_server()

    def test_stop_server_raises_on_subprocess_failure(self):
        with patch("discord_bot.games.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                returncode=1, cmd=["teardown.sh"]
            )

            with pytest.raises(subprocess.CalledProcessError):
                games.VALHEIM.stop_server()

    def test_start_server_logs_error_on_failure(self):
        with patch("discord_bot.games.subprocess.run") as mock_run:
            with patch("discord_bot.games.logger") as mock_logger:
                mock_run.side_effect = subprocess.CalledProcessError(
                    returncode=1, cmd=["start.sh"]
                )

                with pytest.raises(subprocess.CalledProcessError):
                    games.VALHEIM.start_server()

                mock_logger.error.assert_called_once()
                error_msg = mock_logger.error.call_args[0][0]
                assert "Failed to start" in error_msg
                assert "Valheim" in error_msg

    def test_stop_server_logs_error_on_failure(self):
        with patch("discord_bot.games.subprocess.run") as mock_run:
            with patch("discord_bot.games.logger") as mock_logger:
                mock_run.side_effect = subprocess.CalledProcessError(
                    returncode=1, cmd=["teardown.sh"]
                )

                with pytest.raises(subprocess.CalledProcessError):
                    games.VALHEIM.stop_server()

                mock_logger.error.assert_called_once()
                error_msg = mock_logger.error.call_args[0][0]
                assert "Failed to stop" in error_msg
                assert "Valheim" in error_msg


class TestGameInstances:
    """Tests to verify game instances are configured correctly."""

    def test_valheim_game_configuration(self):
        assert games.VALHEIM.game_name == "valheim"
        assert games.VALHEIM.game_display_name == "Valheim"

    def test_factorio_game_configuration(self):
        assert games.FACTORIO.game_name == "factorio"
        assert games.FACTORIO.game_display_name == "Factorio"

    def test_enshrouded_game_configuration(self):
        assert games.ENSHROUDED.game_name == "enshrouded"
        assert games.ENSHROUDED.game_display_name == "Enshrouded"

    def test_abiotic_factor_game_configuration(self):
        assert games.ABIOTIC_FACTOR.game_name == "abiotic-factor"
        assert games.ABIOTIC_FACTOR.game_display_name == "Abiotic Factor"

    def test_windrose_game_configuration(self):
        assert games.WINDROSE.game_name == "windrose"
        assert games.WINDROSE.game_display_name == "Windrose"
