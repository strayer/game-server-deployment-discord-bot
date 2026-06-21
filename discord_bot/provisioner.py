"""Imperative Hetzner Cloud provisioning.

No state database: every resource is named by a fixed convention, so the Hetzner
API itself is the source of truth for what is deployed. Ownership is by name —
the bot manages only ``<game>-server`` / ``<game>-firewall`` / its own ``discord-bot``
SSH key, and never deletes ``<game>-install`` volumes (adopt/attach/detach only).
"""

from __future__ import annotations

import contextlib
import dataclasses
import ipaddress
import os
import socket
import subprocess
import time
from pathlib import Path

import backoff
import requests
import urllib3.util.connection
from hcloud import APIException, Client
from hcloud.firewalls.domain import FirewallRule
from hcloud.locations.domain import Location
from hcloud.server_types.domain import ServerType
from hcloud.servers.client import BoundServer
from loguru import logger

from discord_bot import cloud_init, remote_ops
from discord_bot.games import ALL_GAMES, Game
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hcloud.volumes.client import BoundVolume
    from hcloud.ssh_keys.client import BoundSSHKey
    from hcloud.firewalls.client import BoundFirewall

# The single, bot-managed SSH key shared by all games.
BOT_SSH_KEY_NAME = "discord-bot"
BOT_SSH_KEY_PATH = remote_ops.SSH_KEY_PATH

# Inbound firewall allows ICMP + the per-game game ports from anywhere; SSH (port
# 22) is restricted to the bot's own egress IPv4 (see `_detect_egress_ipv4`).
_ANY_SOURCE = ["0.0.0.0/0", "::/0"]

# Egress-IP detection for the SSH firewall rule. The URL must return JSON with an
# ``ip`` field; ``BOT_EGRESS_IP`` short-circuits detection entirely.
_EGRESS_IP_URL_DEFAULT = "https://ifconfig.co/json"
_EGRESS_IP_TIMEOUT = (5, 10)  # (connect, read) seconds

# API error codes worth retrying (the SDK already retries rate limits internally;
# `backoff` adds a little resilience for transient conflicts/locks).
_RETRYABLE_CODES = {"rate_limit_exceeded", "conflict", "locked"}


def _is_not_retryable(exc: Exception) -> bool:
    return not (isinstance(exc, APIException) and exc.code in _RETRYABLE_CODES)


_retry = backoff.on_exception(
    backoff.expo,
    APIException,
    max_tries=4,
    giveup=_is_not_retryable,
    logger=None,
)


class ProvisionError(RuntimeError):
    """A deploy/destroy step failed. ``step`` names the failed stage for Discord."""

    def __init__(self, step: str, message: str, *, cause: Exception | None = None):
        self.step = step
        self.cause = cause
        super().__init__(f"[{step}] {message}")


class AlreadyDeployedError(ProvisionError):
    """The named server already exists — refuse to (re-)deploy (race-condition fix)."""

    def __init__(self, game: Game):
        super().__init__(
            "guard",
            f"{game.game_display_name} server is already running or starting "
            f"({game.server_name} exists); refusing to deploy.",
        )


@contextlib.contextmanager
def _force_ipv4_dns():
    """Force outbound connections to resolve to IPv4 only, so a dual-stack host
    can't reach the egress-IP service over IPv6 and report its IPv6 address."""
    original = urllib3.util.connection.allowed_gai_family
    urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET
    try:
        yield
    finally:
        urllib3.util.connection.allowed_gai_family = original


def _validate_ipv4(value: str, *, source: str) -> str:
    try:
        parsed = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ProvisionError(
            "firewall",
            f"egress IP {value!r} from {source} is not a valid IP.",
            cause=exc,
        ) from exc
    if not isinstance(parsed, ipaddress.IPv4Address):
        raise ProvisionError(
            "firewall",
            f"egress IP {value!r} from {source} is not IPv4; refusing to open SSH "
            f"to an IPv6 source.",
        )
    return str(parsed)


def _detect_egress_ipv4() -> str:
    """Return the bot's public IPv4 for the SSH firewall rule.

    ``BOT_EGRESS_IP`` short-circuits detection. Otherwise GET ``BOT_EGRESS_IP_URL``
    (default ifconfig.co), forcing IPv4, and read its ``ip`` field. Fail-closed:
    any error raises ``ProvisionError`` so a deploy/teardown aborts rather than
    silently opening SSH to the world.
    """
    override = os.environ.get("BOT_EGRESS_IP")
    if override:
        return _validate_ipv4(override, source="BOT_EGRESS_IP")

    url = os.environ.get("BOT_EGRESS_IP_URL", _EGRESS_IP_URL_DEFAULT)
    try:
        with _force_ipv4_dns():
            resp = requests.get(
                url, timeout=_EGRESS_IP_TIMEOUT, headers={"Accept": "application/json"}
            )
        resp.raise_for_status()
        ip = resp.json()["ip"]
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        raise ProvisionError(
            "firewall",
            f"could not detect bot egress IPv4 from {url!r}: {exc}",
            cause=exc,
        ) from exc
    return _validate_ipv4(ip, source=url)


@dataclasses.dataclass
class DeployResult:
    server_name: str
    ipv4: str


class Provisioner:
    def __init__(
        self,
        client: Client,
        *,
        ssh_key_path: str = BOT_SSH_KEY_PATH,
        shutdown_timeout: float = 180.0,
        poll_interval: float = 5.0,
    ):
        self.client = client
        self.ssh_key_path = ssh_key_path
        self.shutdown_timeout = shutdown_timeout
        self.poll_interval = poll_interval

    # ----------------------------------------------------------------- queries

    @_retry
    def _get_server(self, game: Game) -> BoundServer | None:
        return self.client.servers.get_by_name(game.server_name)

    @_retry
    def _get_firewall(self, game: Game) -> BoundFirewall | None:
        return self.client.firewalls.get_by_name(game.firewall_name)

    @_retry
    def _get_volume(self, name: str) -> BoundVolume | None:
        return self.client.volumes.get_by_name(name)

    def server_ip(self, game: Game) -> str | None:
        server = self._get_server(game)
        if server is None:
            return None
        return server.public_net.ipv4.ip

    def is_deployed(self, game: Game) -> bool:
        return self._get_server(game) is not None

    def _any_managed_server_live(self) -> bool:
        """True if ANY game's server currently exists (the bot SSH key is shared).

        Reuses the retry-wrapped ``_get_server`` and converts a persistent API
        failure into a clear ssh-key-step error rather than a raw ``APIException``.
        """
        try:
            return any(
                self._get_server(other) is not None for other in ALL_GAMES.values()
            )
        except APIException as exc:
            raise ProvisionError(
                "ssh-key",
                f"could not determine whether a managed server is live while "
                f"validating the bot SSH key: {exc.message}",
                cause=exc,
            ) from exc

    # --------------------------------------------------------------- ssh keys

    def _read_local_pubkey(self) -> str:
        """Return the local bot public key, generating the keypair if absent."""
        priv = Path(self.ssh_key_path)
        pub = Path(f"{self.ssh_key_path}.pub")
        if not pub.exists():
            logger.info("Generating bot SSH keypair at {path}", path=self.ssh_key_path)
            priv.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    "ssh-keygen",
                    "-t",
                    "ed25519",
                    "-f",
                    self.ssh_key_path,
                    "-q",
                    "-N",
                    "",
                ],
                check=True,
            )
        return pub.read_text(encoding="utf-8").strip()

    @staticmethod
    def _pubkey_material(pubkey: str) -> str:
        """Normalise an SSH pubkey to ``<type> <base64>`` (ignore comment/whitespace)."""
        parts = pubkey.split()
        return " ".join(parts[:2]) if len(parts) >= 2 else pubkey.strip()

    def _ensure_bot_ssh_key(self) -> None:
        """Validate the bot key against the local private key; adopt or recreate.

        A blind adopt-by-name can attach a stale cloud key whose pubkey no longer
        matches the local private key, silently breaking later SSH stop/backup.
        """
        local_pub = self._read_local_pubkey()
        existing = self.client.ssh_keys.get_by_name(BOT_SSH_KEY_NAME)

        if existing is None:
            logger.info("Creating bot SSH key {name}", name=BOT_SSH_KEY_NAME)
            self.client.ssh_keys.create(name=BOT_SSH_KEY_NAME, public_key=local_pub)
            return

        if self._pubkey_material(existing.public_key) == self._pubkey_material(
            local_pub
        ):
            return  # adopt — already correct

        # Mismatch: only safe to recreate when no managed server depends on the key.
        if self._any_managed_server_live():
            raise ProvisionError(
                "ssh-key",
                f"Bot SSH key {BOT_SSH_KEY_NAME!r} does not match the local private "
                f"key, but a managed server is live. Refusing to recreate it "
                f"(would lock us out). Manual intervention required.",
            )
        logger.warning("Bot SSH key mismatch with no live server; recreating it")
        self.client.ssh_keys.delete(existing)
        self.client.ssh_keys.create(name=BOT_SSH_KEY_NAME, public_key=local_pub)

    @_retry
    def _all_project_ssh_keys(self) -> list[BoundSSHKey]:
        """Every project SSH key (incl. human/debug keys) — read-only, never deleted."""
        return self.client.ssh_keys.get_all()

    # ----------------------------------------------------------------- volumes

    def _resolve_or_create_volume(self, game: Game) -> BoundVolume:
        spec = game.spec
        existing = self._get_volume(game.volume_name)
        if existing is not None:
            return existing

        if spec.volume_size_gb is None or spec.volume_format is None:
            raise ProvisionError(
                "volume",
                f"volume {game.volume_name!r} is missing and cannot be created "
                f"(size/format not configured).",
            )
        logger.info(
            "Creating install volume {name} ({size} GB, {fmt}) in {loc}",
            name=game.volume_name,
            size=spec.volume_size_gb,
            fmt=spec.volume_format,
            loc=spec.location,
        )
        resp = self.client.volumes.create(
            size=spec.volume_size_gb,
            name=game.volume_name,
            location=Location(name=spec.location),
            format=spec.volume_format,
            automount=False,
        )
        resp.action.wait_until_finished()
        return resp.volume

    # ---------------------------------------------------------------- firewall

    def _build_firewall_rules(
        self, game: Game, ssh_source_ips: list[str]
    ) -> list[FirewallRule]:
        rules = [
            FirewallRule(
                direction=FirewallRule.DIRECTION_IN,
                protocol=FirewallRule.PROTOCOL_ICMP,
                source_ips=list(_ANY_SOURCE),
            ),
            FirewallRule(
                direction=FirewallRule.DIRECTION_IN,
                protocol=FirewallRule.PROTOCOL_TCP,
                port="22",
                source_ips=list(ssh_source_ips),
            ),
        ]
        for protocol, port in game.spec.firewall_ports:
            rules.append(
                FirewallRule(
                    direction=FirewallRule.DIRECTION_IN,
                    protocol=protocol,
                    port=port,
                    source_ips=list(_ANY_SOURCE),
                )
            )
        return rules

    def _delete_firewall_if_present(self, game: Game) -> None:
        existing = self._get_firewall(game)
        if existing is None:
            return
        logger.info("Deleting firewall {name}", name=game.firewall_name)
        try:
            self.client.firewalls.delete(existing)
        except APIException as exc:
            raise ProvisionError(
                "firewall",
                f"could not delete firewall {game.firewall_name!r} "
                f"(attached to an unexpected resource?): {exc.message}",
                cause=exc,
            ) from exc

    def _recreate_firewall(self, game: Game) -> BoundFirewall:
        """Delete any stale firewall (we only get here with no live server) and
        create a fresh one — never diff/update."""
        # Detect the egress IP first: a failure here aborts before we touch anything.
        ssh_source_ips = [f"{_detect_egress_ipv4()}/32"]
        self._delete_firewall_if_present(game)
        logger.info("Creating firewall {name}", name=game.firewall_name)
        resp = self.client.firewalls.create(
            name=game.firewall_name,
            rules=self._build_firewall_rules(game, ssh_source_ips),
        )
        for action in resp.actions or []:
            if action is not None:
                action.wait_until_finished()
        return resp.firewall

    def _refresh_firewall_ssh_rule(self, game: Game) -> None:
        """Re-point the SSH rule at the *current* egress IP before teardown SSH.

        The firewall is built at deploy time and reused until /stop, so if the bot's
        egress IP changed in between, teardown SSH/rsync would be blocked. No-op if
        the firewall is already gone; fail-closed if detection fails."""
        firewall = self._get_firewall(game)
        if firewall is None:
            return
        ssh_source_ips = [f"{_detect_egress_ipv4()}/32"]
        logger.info("Refreshing SSH firewall rule for {name}", name=game.firewall_name)
        for action in firewall.set_rules(
            self._build_firewall_rules(game, ssh_source_ips)
        ):
            if action is not None:
                action.wait_until_finished()

    # -------------------------------------------------------------------- image

    @_retry
    def _resolve_image(self, spec):
        """Resolve the OS image, pinning the architecture (was `with_architecture`
        in Terraform) so we never accidentally pick the arm64 ``debian-12``."""
        image = self.client.images.get_by_name_and_architecture(
            spec.image, spec.image_architecture
        )
        if image is None:
            raise ProvisionError(
                "image",
                f"image {spec.image!r} ({spec.image_architecture}) not found.",
            )
        return image

    # ------------------------------------------------------------------ deploy

    def deploy(self, game: Game) -> DeployResult:
        """Provision a game server. Ends once the server exists and its IP is known —
        does NOT wait for the game to be playable (readiness is the watcher's job)."""
        if self.is_deployed(game):
            raise AlreadyDeployedError(game)

        spec = game.spec
        created_server: BoundServer | None = None
        created_firewall: BoundFirewall | None = None
        try:
            self._ensure_bot_ssh_key()

            volume: BoundVolume | None = None
            if spec.has_volume:
                volume = self._resolve_or_create_volume(game)

            user_data = cloud_init.render(
                game, volume_id=volume.id if volume is not None else None
            )

            created_firewall = self._recreate_firewall(game)
            ssh_keys = self._all_project_ssh_keys()
            image = self._resolve_image(spec)

            logger.info(
                "Creating server {name} ({type} @ {loc}){vol}",
                name=game.server_name,
                type=spec.server_type,
                loc=spec.location,
                vol=f" with volume {volume.name}" if volume else "",
            )
            resp = self.client.servers.create(
                name=game.server_name,
                server_type=ServerType(name=spec.server_type),
                image=image,
                location=Location(name=spec.location),
                user_data=user_data,
                ssh_keys=ssh_keys,
                firewalls=[created_firewall],
                volumes=[volume] if volume is not None else None,
                automount=False if volume is not None else None,
                start_after_create=True,
            )
            created_server = resp.server

            for action in [resp.action, *(resp.next_actions or [])]:
                if action is not None:
                    action.wait_until_finished()

            created_server.reload()
            ipv4 = created_server.public_net.ipv4.ip
            logger.info("Server {name} created @ {ip}", name=game.server_name, ip=ipv4)
            return DeployResult(server_name=game.server_name, ipv4=ipv4)

        except ProvisionError:
            self._rollback(game, created_server, created_firewall)
            raise
        except APIException as exc:
            self._rollback(game, created_server, created_firewall)
            raise ProvisionError(
                "deploy",
                f"Hetzner API error while deploying {game.game_display_name}: "
                f"{exc.message}"
                + (
                    f" (correlation_id={exc.correlation_id})"
                    if exc.correlation_id
                    else ""
                ),
                cause=exc,
            ) from exc

    def _rollback(
        self,
        game: Game,
        server: BoundServer | None,
        firewall: BoundFirewall | None,
    ) -> None:
        """Best-effort cleanup of just-created resources. Never touch volumes.
        Anything missed here is recognised on the next deploy: the start-guard
        refuses when the server exists, and a leftover firewall is delete-and-
        recreated, so a half-finished deploy is always structurally recoverable."""
        if server is not None:
            try:
                logger.warning("Rolling back: deleting server {n}", n=game.server_name)
                server.delete().wait_until_finished()
            except Exception as exc:  # noqa: BLE001 — best-effort
                logger.error("Rollback server delete failed: {e}", e=exc)
        if firewall is not None:
            try:
                logger.warning(
                    "Rolling back: deleting firewall {n}", n=game.firewall_name
                )
                self.client.firewalls.delete(firewall)
            except Exception as exc:  # noqa: BLE001 — best-effort
                logger.error("Rollback firewall delete failed: {e}", e=exc)

    # ----------------------------------------------------------------- destroy

    def _wait_until_off(self, server: BoundServer) -> None:
        deadline = time.monotonic() + self.shutdown_timeout
        while True:
            server.reload()
            if server.status == BoundServer.STATUS_OFF:
                return
            if time.monotonic() >= deadline:
                raise ProvisionError(
                    "shutdown",
                    f"server {server.name} did not power off within "
                    f"{self.shutdown_timeout:.0f}s. Refusing to force-off or detach "
                    f"the volume (risk of filesystem corruption).",
                )
            time.sleep(self.poll_interval)

    def destroy(self, game: Game) -> None:
        """Tear down a game server. Ordered: backup (alive) -> shutdown -> detach
        volume -> delete server -> delete firewall. Idempotent throughout."""
        server = self._get_server(game)
        if server is None:
            logger.info("No {name} server to destroy", name=game.server_name)
            # Still reap a leftover firewall so /stop fully cleans up.
            self._delete_firewall_if_present(game)
            return

        ipv4 = server.public_net.ipv4.ip

        # Make sure the SSH rule still allows our (possibly changed) egress IP before
        # we rely on SSH for the backup.
        self._refresh_firewall_ssh_rule(game)

        # 1. Stop the container and back up while the server is still alive.
        try:
            remote_ops.stop_and_backup(game, ipv4)
        except subprocess.CalledProcessError as exc:
            raise ProvisionError(
                "backup",
                f"SSH stop/backup of {game.game_display_name} failed "
                f"(rc={exc.returncode}); aborting teardown to avoid data loss.",
                cause=exc,
            ) from exc

        # 2/3. Volume games: graceful OS shutdown, then detach (never from a running VM).
        if game.spec.has_volume:
            try:
                logger.info("Shutting down {name} (ACPI)", name=game.server_name)
                server.shutdown().wait_until_finished()
                self._wait_until_off(server)
                self._detach_volume(game)
            except APIException as exc:
                raise ProvisionError(
                    "shutdown",
                    f"failed to cleanly shut down/detach volume for "
                    f"{game.game_display_name}: {exc.message}",
                    cause=exc,
                ) from exc

        # 4. Delete the server.
        logger.info("Deleting server {name}", name=game.server_name)
        server.delete().wait_until_finished()

        # 5. Delete the per-game firewall (after the server is gone). The shared bot
        #    SSH key is intentionally left in place.
        self._delete_firewall_if_present(game)

    def _detach_volume(self, game: Game) -> None:
        """Detach the install volume if attached. Never delete it."""
        volume = self._get_volume(game.volume_name)
        if volume is None or volume.server is None:
            return
        logger.info("Detaching volume {name}", name=game.volume_name)
        volume.detach().wait_until_finished()


def client_from_env() -> Client:
    """Build a Hetzner client from the token (reuses the existing TF_VAR env var)."""
    token = os.environ.get("HCLOUD_TOKEN") or os.environ.get("TF_VAR_hcloud_token")
    if not token:
        raise ProvisionError(
            "config", "no Hetzner token (set HCLOUD_TOKEN or TF_VAR_hcloud_token)."
        )
    return Client(token=token)
