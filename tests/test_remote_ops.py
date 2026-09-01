"""Tests for the SSH teardown path (discord_bot.remote_ops).

This module's whole job is building the right remote commands, so the commands ARE
the behavior under test: the per-game stop strategy, the restic backup invocation,
and the rsync mirror — all non-interactive so a dead host can't hang the worker.
"""

from __future__ import annotations

import pathlib
from unittest.mock import patch

import pytest

from discord_bot import remote_ops
from discord_bot.games import FACTORIO, VALHEIM, WINDROSE, Game, ServerSpec

IP = "203.0.113.10"


class TestContainerStopCommand:
    def test_sigint_wait_strategy(self):
        # Valheim needs SIGINT + wait to flush its world save.
        assert remote_ops.container_stop_command(VALHEIM) == (
            "docker kill --signal=SIGINT valheim-server && docker wait valheim-server"
        )

    def test_stop_timeout_strategy(self):
        cmd = remote_ops.container_stop_command(WINDROSE)
        assert cmd == f"docker stop -t {WINDROSE.spec.stop_timeout} windrose-server"

    def test_plain_stop_strategy(self):
        assert (
            remote_ops.container_stop_command(FACTORIO) == "docker stop factorio-server"
        )

    def test_unknown_strategy_raises(self):
        bogus = Game(
            game_name="bogus",
            game_display_name="Bogus",
            bot_message_server_started="",
            bot_message_server_ready="",
            bot_message_started="",
            bot_message_finished="",
            spec=ServerSpec(stop_strategy="yolo"),
        )
        with pytest.raises(ValueError, match="yolo"):
            remote_ops.container_stop_command(bogus)

    def test_every_game_has_a_valid_stop_strategy(self):
        from discord_bot.games import ALL_GAMES

        for game in ALL_GAMES.values():
            # Raises ValueError if a game ever ships an unknown strategy.
            assert remote_ops.container_stop_command(game)


class TestStopAndBackup:
    """Division of labor: ``test_sequence_stop_backup_rsync`` owns the count, order
    and *identity* of the three subprocess steps; the sibling tests own each step's
    *content* (ssh options, exit-code checking, rsync source/dest). Step details are
    asserted in exactly one place, so a change to one command fails one test."""

    @pytest.fixture
    def run(self, tmp_path, monkeypatch):
        """The mocked ``subprocess.run``; every call it records is an argv list in
        ``run.call_args_list``. The mocked ``time.sleep`` rides along as ``run.sleep``,
        and ``BACKUP_PATH`` points at ``tmp_path`` (also exposed as ``run.tmp_path``)."""
        monkeypatch.setenv("BACKUP_PATH", str(tmp_path))
        with (
            patch.object(remote_ops.subprocess, "run") as run,
            patch.object(remote_ops.time, "sleep") as sleep,
        ):
            run.tmp_path = tmp_path
            run.sleep = sleep
            yield run

    def test_sequence_stop_backup_rsync(self, run):
        # Shared trace across both mocks: the settle delay must sit between the
        # stop and the backup (the game needs it to finish flushing its save).
        events = []
        run.side_effect = lambda *a, **k: events.append("run")
        run.sleep.side_effect = lambda *a, **k: events.append("sleep")

        remote_ops.stop_and_backup(VALHEIM, IP)

        assert events == ["run", "sleep", "run", "run"]

        commands = [c.args[0] for c in run.call_args_list]
        assert len(commands) == 3

        # This unpacking IS the ordering assertion: stop must come first (flush the
        # world save), then the restic backup, then the rsync mirror — all while the
        # server is still alive. Each step then gets just enough asserting to prove
        # the slot holds the right command; the details live in the sibling tests.
        ssh_stop, ssh_backup, rsync = commands

        # In an ssh argv the remote command is always the last element. Comparing
        # against the production builder (already pinned per-strategy above) keeps
        # this test stable when a game's stop strategy is tuned.
        assert ssh_stop[0] == "ssh"
        assert ssh_stop[-1] == remote_ops.container_stop_command(VALHEIM)

        # Image + tag are what make this recognizably the end-of-session restic
        # backup; the remaining docker flags are deliberately not pinned.
        assert ssh_backup[0] == "ssh"
        assert remote_ops.BACKUP_IMAGE in ssh_backup[-1]
        assert "BACKUP_TAG=after-session" in ssh_backup[-1]

        assert rsync[0] == "rsync"

    def test_ssh_is_non_interactive_and_targets_root(self, run):
        remote_ops.stop_and_backup(VALHEIM, IP)

        for command in [c.args[0] for c in run.call_args_list]:
            flat = " ".join(command)
            # A bad key or dead host must fail fast, never hang on a prompt.
            assert "BatchMode=yes" in flat
            assert "StrictHostKeyChecking=no" in flat
            assert f"root@{IP}" in flat

    def test_all_remote_commands_check_exit_codes(self, run):
        # check=True is what turns a failed backup into an aborted teardown
        # (provisioner refuses to delete the server if this raises).
        remote_ops.stop_and_backup(VALHEIM, IP)

        for c in run.call_args_list:
            assert c.kwargs.get("check") is True

    def test_rsync_mirrors_gamedata_into_per_game_dir(self, run):
        remote_ops.stop_and_backup(VALHEIM, IP)

        rsync = run.call_args_list[-1].args[0]
        dest = pathlib.Path(run.tmp_path) / "valheim" / "current"
        assert rsync[-2] == f"root@{IP}:/gamedata/"
        assert rsync[-1] == f"{dest}/"
        assert "--delete" in rsync
        assert dest.is_dir()
