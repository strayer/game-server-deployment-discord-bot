import os
import re
import socket
import sys
from dataclasses import dataclass

import backoff
import requests
from loguru import logger

import docker
from docker.errors import NotFound
from docker.models.containers import Container

# Specify the environment variables for the container name and regex pattern
GAME_NAME = os.environ.get("GAME_NAME")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK")
SERVER_READY_MESSAGE = os.environ.get("SERVER_READY_MESSAGE")

if DISCORD_WEBHOOK is None or DISCORD_WEBHOOK == "":
    logger.error("DISCORD_WEBHOOK environment variable required to function")
    sys.exit(-1)

if SERVER_READY_MESSAGE is None or SERVER_READY_MESSAGE == "":
    logger.error("SERVER_READY_MESSAGE environment variable required to function")
    sys.exit(-1)

if GAME_NAME == "valheim":
    CONTAINER_NAME = "valheim-server"
    REGEX_PATTERN = "Game server connected"
elif GAME_NAME == "factorio":
    CONTAINER_NAME = "factorio-server"
    REGEX_PATTERN = r"changing state from\(CreatingGame\) to\(InGame\)"
elif GAME_NAME == "enshrouded":
    CONTAINER_NAME = "enshrouded-server"
    REGEX_PATTERN = r"\[Session\] 'HostOnline' \(up\)!"
elif GAME_NAME is None or GAME_NAME == "":
    logger.error("GAME_NAME environment variable required to function")
    sys.exit(-1)
else:
    logger.error("Unknown game {game}", game=GAME_NAME)
    sys.exit(-1)

# Compile the regex pattern for better performance
compiled_regex = re.compile(REGEX_PATTERN)


@dataclass
class ServerAddresses:
    ipv4: str
    ipv6: str | None
    domain: str | None

    def __str__(self) -> str:
        # At time of writing Enshrouded does not support IPv6
        ip_part = (
            self.ipv4
            if self.ipv6 is None or GAME_NAME == "enshrouded"
            else f"{self.ipv4}, {self.ipv6}"
        )

        if self.domain is None:
            return ip_part
        else:
            return f"{self.domain} ({ip_part})"


def reverse_dns(ip: str) -> str | None:
    try:
        resolved_hostname, _, _ = socket.gethostbyaddr(ip)
        return resolved_hostname
    except socket.herror:
        # Handle exception which may be thrown if the IP does not have a reverse DNS record
        return None


@backoff.on_exception(backoff.expo, NotFound, max_time=60)
def get_container() -> Container:
    return client.containers.get(CONTAINER_NAME)  # type:ignore


def get_addresses() -> ServerAddresses:
    r_ipv4 = requests.get("https://ipv4.icanhazip.com/")
    r_ipv6 = requests.get("https://ipv6.icanhazip.com/")

    r_ipv4.raise_for_status()

    ipv4 = r_ipv4.text.strip()
    ipv6 = r_ipv6.text.strip() if r_ipv6.ok else None

    return ServerAddresses(
        ipv4=ipv4,
        ipv6=ipv6,
        domain=reverse_dns(ipv4),
    )


def notify_server_ready(server_addresses: ServerAddresses):
    data = {
        "content": f"{SERVER_READY_MESSAGE} [{server_addresses}]",
    }
    result = requests.post(DISCORD_WEBHOOK, json=data)
    result.raise_for_status()


# Establish a connection to the Docker server using the default socket
client = docker.from_env()

server_addresses = get_addresses()

try:
    container = get_container()

    # Stream the logs from the container, both old and new
    for log_line in container.logs(stream=True, follow=True, tail="all"):
        log_line = log_line.decode("utf-8").strip()

        if compiled_regex.search(log_line):
            logger.info("Matched log line: {log_line}", log_line=log_line)
            notify_server_ready(server_addresses)
            break
        else:
            logger.debug("Unmatched log line: {log_line}", log_line=log_line)

except NotFound:
    logger.error(
        "Container '{CONTAINER_NAME}' not found.", CONTAINER_NAME=CONTAINER_NAME
    )
except Exception as e:
    logger.error("An error occurred: {e}", e=e)
finally:
    client.close()
