"""SSH-based remote operations against a deployed game server.

Replaces the shell ``scripts/backup.sh`` / ``scripts/teardown.sh`` SSH steps. The
server IP is supplied by the provisioner (read from the Hetzner API) instead of
``terraform output``, and the single shared bot key ``/sshkey/sshkey`` is used for
every game (the old per-game ``/sshkey/sshkey.<game>`` paths are gone).
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import time

from loguru import logger

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from discord_bot.games import Game

# Shared bot SSH private key (see provisioner / cutover notes).
SSH_KEY_PATH = "/sshkey/sshkey"
# BatchMode + ConnectTimeout keep SSH/rsync non-interactive: a bad key or an
# unreachable host fails fast instead of hanging the job runner on an auth prompt.
_SSH_BASE_OPTS = [
    "-o",
    "StrictHostKeyChecking=no",
    "-o",
    "UserKnownHostsFile=/dev/null",
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=15",
]
BACKUP_IMAGE = "ghcr.io/strayer/game-server-deployment-discord-bot/backup:latest"

# Seconds to wait after issuing the container stop before backing up (matches the
# `sleep 5` in the old teardown.sh).
_POST_STOP_DELAY = 5


def _ssh_command(ip: str, remote_command: str) -> list[str]:
    return [
        "ssh",
        "-i",
        SSH_KEY_PATH,
        *_SSH_BASE_OPTS,
        f"root@{ip}",
        remote_command,
    ]


def container_stop_command(game: Game) -> str:
    """Build the remote ``docker`` command that stops the game container.

    The container is named ``<game>-server`` (same as the Hetzner server name).
    """
    container = game.server_name
    strategy = game.spec.stop_strategy
    if strategy == "sigint-wait":
        return f"docker kill --signal=SIGINT {container} && docker wait {container}"
    if strategy == "stop-timeout":
        return f"docker stop -t {game.spec.stop_timeout} {container}"
    if strategy == "stop":
        return f"docker stop {container}"
    raise ValueError(f"unknown stop_strategy {strategy!r} for {game.game_name}")


def stop_container(game: Game, ip: str) -> None:
    logger.info("Stopping {game} container on {ip}", game=game.game_display_name, ip=ip)
    subprocess.run(_ssh_command(ip, container_stop_command(game)), check=True)


def run_remote_backup(game: Game, ip: str) -> None:
    """Run the restic backup container on the server (tag: after-session)."""
    logger.info(
        "Backing up {game} gamedata on {ip}", game=game.game_display_name, ip=ip
    )
    remote_command = (
        "docker run --rm --read-only "
        "-v /gamedata:/gamedata "
        "--env-file /env-backup "
        "--tmpfs /tmp "
        "-e BACKUP_TAG=after-session "
        f"{BACKUP_IMAGE} backup.sh"
    )
    subprocess.run(_ssh_command(ip, remote_command), check=True)


def pull_gamedata(game: Game, ip: str) -> None:
    """rsync the server's /gamedata into the local backup mirror."""
    backup_path = os.environ.get("BACKUP_PATH", "/backup")
    dest_dir = pathlib.Path(backup_path) / game.game_name / "current"
    dest_dir.mkdir(parents=True, exist_ok=True)
    # Reuse the same non-interactive opts as _ssh_command so rsync can't hang either.
    rsync_ssh = "ssh -i " + SSH_KEY_PATH + " " + " ".join(_SSH_BASE_OPTS)
    subprocess.run(
        [
            "rsync",
            "--delete",
            "-avP",
            "--no-o",
            "--no-g",
            "-e",
            rsync_ssh,
            f"root@{ip}:/gamedata/",
            f"{dest_dir}/",
        ],
        check=True,
    )


def stop_and_backup(game: Game, ip: str) -> None:
    """Full pre-teardown sequence: stop container, back up, mirror gamedata locally.

    Must run while the server is still alive (the backup needs the running OS).
    """
    stop_container(game, ip)
    time.sleep(_POST_STOP_DELAY)
    run_remote_backup(game, ip)
    pull_gamedata(game, ip)
