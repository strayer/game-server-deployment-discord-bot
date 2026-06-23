from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping

# Firewall port spec: (protocol, port). ``port`` is a single port ("7777") or an
# inclusive range ("15636-15637") — hence a string, not an int. ICMP and TCP/22 are
# always added by the firewall builder, so they are NOT listed here.
PortRule = tuple[Literal["tcp", "udp"], str]


@dataclass(frozen=True)
class ServerSpec:
    """Per-game infrastructure parameters for direct Hetzner API provisioning."""

    # Hetzner server type (vCPU/RAM tier).
    server_type: str = "ccx23"
    # Hetzner location.
    location: str = "nbg1"
    image: str = "debian-12"
    image_architecture: str = "x86"
    firewall_ports: tuple[PortRule, ...] = ()

    # Install volume (volume-backed games only). The volume is resolved by name
    # (see ``Game.volume_name``) and CREATED on demand when missing — size/format
    # are required for that create.
    volume_size_gb: int | None = None
    volume_format: str | None = None

    # cloud-init template variables that are NOT sourced from a TF_VAR_* env var.
    # These were Terraform variable *defaults* (e.g. abiotic-factor max players).
    # Secrets must never live here — they come from the environment.
    cloud_init_defaults: Mapping[str, str] = field(default_factory=dict)

    # How destroy() stops the game container over SSH before the restic backup.
    #   "stop"         -> docker stop <container>
    #   "sigint-wait"  -> docker kill --signal=SIGINT <container> && docker wait <container>
    #   "stop-timeout" -> docker stop -t <stop_timeout> <container>   (graceful flush)
    stop_strategy: str = "stop"
    stop_timeout: int = 90

    @property
    def has_volume(self) -> bool:
        return self.volume_size_gb is not None


class Game:
    def __init__(
        self,
        game_name: str,
        game_display_name: str,
        bot_message_server_started: str,
        bot_message_server_ready: str,
        bot_message_started: str,
        bot_message_finished: str,
        spec: ServerSpec,
    ):
        self.game_name = game_name
        self.game_display_name = game_display_name
        self.bot_message_server_started = bot_message_server_started
        self.bot_message_server_ready = bot_message_server_ready
        self.bot_message_started = bot_message_started
        self.bot_message_finished = bot_message_finished
        self.spec = spec

    @property
    def server_name(self) -> str:
        return f"{self.game_name}-server"

    @property
    def firewall_name(self) -> str:
        return f"{self.game_name}-firewall"

    @property
    def volume_name(self) -> str:
        return f"{self.game_name}-install"

    @property
    def tf_var_prefix(self) -> str:
        """Underscore form used in TF_VAR_* env vars and cloud-init placeholders.

        e.g. game_name "abiotic-factor" -> "abiotic_factor".
        """
        return self.game_name.replace("-", "_")

    @property
    def discord_channel_webhook(self) -> str | None:
        """The game's Discord channel webhook (for error/teardown notifications)."""
        return os.environ.get(f"TF_VAR_{self.tf_var_prefix}_discord_channel_webhook")


VALHEIM = Game(
    game_name="valheim",
    game_display_name="Valheim",
    bot_message_server_started="Valheim has been installed and save state backup restored, starting game server...",
    bot_message_server_ready="Valheim server is ready!",
    bot_message_started="Valheim is shutting down...",
    bot_message_finished="Valheim server has been destroyed and world backed up 🧨💥",
    spec=ServerSpec(
        location="nbg1",
        firewall_ports=(("udp", "2456-2457"),),
        # Valheim needs SIGINT + `docker wait` to flush its world save cleanly.
        stop_strategy="sigint-wait",
    ),
)

FACTORIO = Game(
    game_name="factorio",
    game_display_name="Factorio",
    bot_message_server_started="Factorio has been installed and save state backup restored, starting game server...",
    bot_message_server_ready="Factorio server is ready!",
    bot_message_started="Factorio is shutting down...",
    bot_message_finished="Factorio server has been destroyed and savegame backed up 🧨💥",
    spec=ServerSpec(
        location="fsn1",
        firewall_ports=(("udp", "60001-60999"), ("udp", "34197")),
    ),
)

ENSHROUDED = Game(
    game_name="enshrouded",
    game_display_name="Enshrouded",
    bot_message_server_started="Enshrouded has been installed and save state backup restored, starting game server...",
    bot_message_server_ready="Enshrouded server is ready!",
    bot_message_started="Enshrouded is shutting down...",
    bot_message_finished="Enshrouded server has been destroyed and savegame backed up 🧨💥",
    spec=ServerSpec(
        location="nbg1",
        firewall_ports=(("udp", "15636-15637"), ("tcp", "15636-15637")),
    ),
)

ABIOTIC_FACTOR = Game(
    game_name="abiotic-factor",
    game_display_name="Abiotic Factor",
    bot_message_server_started="Abiotic Factor has been installed and save state backup restored, starting game server...",
    bot_message_server_ready="Abiotic Factor server is ready!",
    bot_message_started="Abiotic Factor is shutting down...",
    bot_message_finished="Abiotic Factor server has been destroyed and savegame backed up 🧨💥",
    spec=ServerSpec(
        location="nbg1",
        firewall_ports=(("udp", "7777"), ("udp", "27015")),
        volume_size_gb=10,
        volume_format="ext4",
        # max players is not in the environment; it was a Terraform default (6).
        cloud_init_defaults={"abiotic_factor_max_players": "6"},
    ),
)

WINDROSE = Game(
    game_name="windrose",
    game_display_name="Windrose",
    bot_message_server_started="Windrose has been installed and save state backup restored, starting game server...",
    bot_message_server_ready="Windrose server is ready!",
    bot_message_started="Windrose is shutting down...",
    bot_message_finished="Windrose server has been destroyed and savegame backed up 🧨💥",
    spec=ServerSpec(
        location="nbg1",
        firewall_ports=(("tcp", "7777"), ("udp", "7777")),
        volume_size_gb=10,
        volume_format="ext4",
        # Longer stop timeout so the wineserver -k graceful shutdown can flush the
        # RocksDB world save before SIGKILL.
        stop_strategy="stop-timeout",
        stop_timeout=90,
    ),
)


# All games the bot manages, keyed by game_name.
ALL_GAMES: dict[str, Game] = {
    game.game_name: game
    for game in (VALHEIM, FACTORIO, ENSHROUDED, ABIOTIC_FACTOR, WINDROSE)
}
