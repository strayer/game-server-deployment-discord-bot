"""Runs ON the game VM: watches the game container's logs and posts the "server
is ready" Discord webhook once the per-game readiness marker appears.

Only ``main()`` touches the environment, Docker and the network — importing this
module is side-effect free so the per-game config and matching logic are testable.
"""

import os
import re
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

import requests
import tenacity
from docker.errors import NotFound
from loguru import logger

import docker
from discord_bot import games

if TYPE_CHECKING:
    from docker.models.containers import Container


@dataclass(frozen=True)
class WatchConfig:
    container_name: str
    # Regex searched against each log line; the first match fires the webhook.
    ready_pattern: str


WATCH_CONFIGS: dict[str, WatchConfig] = {
    "valheim": WatchConfig(
        container_name="valheim-server",
        ready_pattern="Game server connected",
    ),
    "factorio": WatchConfig(
        container_name="factorio-server",
        ready_pattern=r"changing state from\(CreatingGame\) to\(InGame\)",
    ),
    "enshrouded": WatchConfig(
        container_name="enshrouded-server",
        ready_pattern=r"\[Session\] 'HostOnline' \(up\)!",
    ),
    "abiotic-factor": WatchConfig(
        container_name="abiotic-factor-server",
        ready_pattern=r"Session creation completed\.",
    ),
    "windrose": WatchConfig(
        container_name="windrose-server",
        # R5LogCoopProxy ... SetIsReadyForHostOwnerConnect: fires after the save DB has
        # loaded and the listeners are up - the true "ready for players" gate. (The port
        # "listening" line is unreliable: it fires for the lobby before the world loads.)
        ready_pattern=r"Host server is ready for owner to connect",
    ),
}


@dataclass
class ServerAddresses:
    ipv4: str
    ipv6: str | None
    domain: str

    def __str__(self) -> str:
        ip_part = self.ipv4 if self.ipv6 is None else f"{self.ipv4}, {self.ipv6}"
        return f"{self.domain} ({ip_part})"


@tenacity.retry(
    retry=tenacity.retry_if_exception_type(NotFound),
    wait=tenacity.wait_random_exponential(multiplier=1),
    stop=tenacity.stop_after_delay(60),
    reraise=True,
)
def get_container(client: docker.DockerClient, container_name: str) -> Container:
    return client.containers.get(container_name)  # type:ignore


def get_addresses(ipv6_supported: bool, hostname: str) -> ServerAddresses:
    r_ipv4 = requests.get("https://ipv4.icanhazip.com/")
    r_ipv6 = requests.get("https://ipv6.icanhazip.com/")

    r_ipv4.raise_for_status()

    ipv4 = r_ipv4.text.strip()
    ipv6 = r_ipv6.text.strip() if r_ipv6.ok and ipv6_supported else None

    return ServerAddresses(ipv4=ipv4, ipv6=ipv6, domain=hostname)


def first_ready_line(log_lines, ready_regex: re.Pattern) -> str | None:
    """Consume a (streaming) iterable of raw log lines; return the first line that
    matches the readiness regex, or None if the stream ends without a match."""
    for log_line in log_lines:
        log_line = log_line.decode("utf-8").strip()

        if ready_regex.search(log_line):
            logger.info("Matched log line: {log_line}", log_line=log_line)
            return log_line
        else:
            logger.debug("Unmatched log line: {log_line}", log_line=log_line)
    return None


def notify_server_ready(
    webhook: str, ready_message: str, server_addresses: ServerAddresses
):
    data = {
        "content": f"{ready_message} [{server_addresses}]",
    }
    result = requests.post(webhook, json=data)
    result.raise_for_status()


def main() -> None:
    game_name = os.environ.get("GAME_NAME")
    discord_webhook = os.environ.get("DISCORD_WEBHOOK")
    server_ready_message = os.environ.get("SERVER_READY_MESSAGE")
    server_hostname = os.environ.get("SERVER_HOSTNAME")

    if discord_webhook is None or discord_webhook == "":
        logger.error("DISCORD_WEBHOOK environment variable required to function")
        sys.exit(-1)

    if server_ready_message is None or server_ready_message == "":
        logger.error("SERVER_READY_MESSAGE environment variable required to function")
        sys.exit(-1)

    if game_name is None or game_name == "":
        logger.error("GAME_NAME environment variable required to function")
        sys.exit(-1)

    if not server_hostname:
        logger.error("SERVER_HOSTNAME environment variable required to function")
        sys.exit(-1)

    config = WATCH_CONFIGS.get(game_name)
    if config is None:
        logger.error("Unknown game {game}", game=game_name)
        sys.exit(-1)

    # Compile the regex pattern for better performance
    compiled_regex = re.compile(config.ready_pattern)

    # Establish a connection to the Docker server using the default socket
    client = docker.from_env()

    server_addresses = get_addresses(
        games.ALL_GAMES[game_name].spec.ipv6_supported, server_hostname
    )

    try:
        container = get_container(client, config.container_name)

        # Stream the logs from the container, both old and new
        matched = first_ready_line(
            container.logs(stream=True, follow=True, tail="all"), compiled_regex
        )
        if matched is not None:
            notify_server_ready(discord_webhook, server_ready_message, server_addresses)

    except NotFound:
        logger.error(
            "Container '{container_name}' not found.",
            container_name=config.container_name,
        )
    except Exception as e:  # noqa: BLE001 — the watcher must never crash the VM boot
        logger.error("An error occurred: {e}", e=e)
    finally:
        client.close()


if __name__ == "__main__":
    main()
