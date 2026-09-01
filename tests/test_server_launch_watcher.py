"""Tests for the on-VM readiness watcher (discord_bot.server_launch_watcher).

The watcher's core value is the per-game readiness regex — a wrong pattern means
the "server is ready" webhook never fires (or fires too early). Each pattern is
pinned against a realistic log line, and the config registry is checked against
games.ALL_GAMES so adding a game without a watcher entry fails a test.
"""

from __future__ import annotations

import re
import typing
from unittest.mock import patch

import pytest

from discord_bot import games
from discord_bot import server_launch_watcher as watcher

READY_LOG_LINES = {
    "valheim": b"04/25/2024 21:30:12: Game server connected",
    "factorio": (
        b"1710.622 Info ServerMultiplayerManager.cpp:783: updateTick(4471) "
        b"changing state from(CreatingGame) to(InGame)"
    ),
    "enshrouded": b"[online] [Session] 'HostOnline' (up)!",
    "abiotic-factor": b"[LogAbiotic]: Session creation completed.",
    "windrose": (
        b"R5LogCoopProxy: SetIsReadyForHostOwnerConnect: "
        b"Host server is ready for owner to connect"
    ),
}

# Lines that look ready-ish but must NOT fire the webhook.
NOT_READY_LOG_LINES = [
    b"Steam game server initialized",
    b"Loading world from save file",
    # Windrose: the lobby "listening" line fires before the world loads.
    b"Server is listening on port 7777",
    b"changing state from(Ready) to(CreatingGame)",
]


class TestWatchConfigs:
    def test_every_game_has_a_watch_config(self):
        # CLAUDE.md step 4: adding a game requires a readiness regex here.
        assert set(watcher.WATCH_CONFIGS) == set(games.ALL_GAMES)

    def test_container_names_follow_the_server_naming_convention(self):
        for name, config in watcher.WATCH_CONFIGS.items():
            assert config.container_name == games.ALL_GAMES[name].server_name

    def test_all_patterns_compile(self):
        for config in watcher.WATCH_CONFIGS.values():
            re.compile(config.ready_pattern)

    @pytest.mark.parametrize("game_name", sorted(READY_LOG_LINES))
    def test_ready_line_matches(self, game_name):
        config = watcher.WATCH_CONFIGS[game_name]
        pattern = re.compile(config.ready_pattern)
        line = READY_LOG_LINES[game_name].decode("utf-8")
        assert pattern.search(line), f"{game_name} readiness line did not match"

    @pytest.mark.parametrize("game_name", sorted(watcher.WATCH_CONFIGS))
    def test_not_ready_lines_do_not_match(self, game_name):
        pattern = re.compile(watcher.WATCH_CONFIGS[game_name].ready_pattern)
        for raw in NOT_READY_LOG_LINES:
            assert not pattern.search(raw.decode("utf-8"))

    def test_every_ready_sample_exists(self):
        assert set(READY_LOG_LINES) == set(watcher.WATCH_CONFIGS)


class TestFirstReadyLine:
    def test_returns_first_matching_line_and_stops_consuming(self):
        pattern = re.compile("Game server connected")
        lines = iter(
            [
                b"noise\n",
                READY_LOG_LINES["valheim"] + b"\n",
                b"must never be read",
            ]
        )

        matched = watcher.first_ready_line(lines, pattern)

        assert matched == READY_LOG_LINES["valheim"].decode("utf-8")
        # The stream is left open at the line after the match (the real stream
        # is infinite while the container runs — matching must break out).
        assert next(lines) == b"must never be read"

    def test_returns_none_when_stream_ends_without_match(self):
        pattern = re.compile("never matches")
        assert watcher.first_ready_line(iter([b"a", b"b"]), pattern) is None


class TestServerAddresses:
    def test_ipv4_only(self):
        addresses = watcher.ServerAddresses(ipv4="1.2.3.4", ipv6=None, domain=None)
        assert str(addresses) == "1.2.3.4"

    def test_ipv4_and_ipv6_when_supported(self):
        addresses = watcher.ServerAddresses(
            ipv4="1.2.3.4", ipv6="2001:db8::1", domain=None, ipv6_supported=True
        )
        assert str(addresses) == "1.2.3.4, 2001:db8::1"

    def test_ipv6_hidden_when_game_does_not_support_it(self):
        addresses = watcher.ServerAddresses(
            ipv4="1.2.3.4", ipv6="2001:db8::1", domain=None, ipv6_supported=False
        )
        assert str(addresses) == "1.2.3.4"

    def test_domain_wraps_the_ip_part(self):
        addresses = watcher.ServerAddresses(
            ipv4="1.2.3.4", ipv6=None, domain="static.1.2.3.4.example.net"
        )
        assert str(addresses) == "static.1.2.3.4.example.net (1.2.3.4)"


class TestReverseDns:
    def test_resolves(self):
        with patch.object(
            watcher.socket, "gethostbyaddr", return_value=("host.example", [], [])
        ):
            assert watcher.reverse_dns("1.2.3.4") == "host.example"

    def test_missing_ptr_record_returns_none(self):
        with patch.object(
            watcher.socket,
            "gethostbyaddr",
            side_effect=watcher.socket.herror("no PTR"),
        ):
            assert watcher.reverse_dns("1.2.3.4") is None


class TestMainStartupValidation:
    """main() must refuse to start (before touching Docker or the network) when
    its environment is incomplete."""

    ENV_OK: typing.ClassVar[dict[str, str]] = {
        "GAME_NAME": "valheim",
        "DISCORD_WEBHOOK": "https://hook.test",
        "SERVER_READY_MESSAGE": "Ready!",
    }

    @pytest.mark.parametrize(
        "missing", ["GAME_NAME", "DISCORD_WEBHOOK", "SERVER_READY_MESSAGE"]
    )
    def test_missing_env_var_exits(self, monkeypatch, missing):
        for key, value in self.ENV_OK.items():
            monkeypatch.setenv(key, value)
        monkeypatch.delenv(missing)

        with pytest.raises(SystemExit):
            watcher.main()

    def test_unknown_game_exits(self, monkeypatch):
        for key, value in self.ENV_OK.items():
            monkeypatch.setenv(key, value)
        monkeypatch.setenv("GAME_NAME", "minecraft")

        with pytest.raises(SystemExit):
            watcher.main()


class TestNotifyServerReady:
    def test_posts_ready_message_with_addresses(self):
        addresses = watcher.ServerAddresses(
            ipv4="1.2.3.4", ipv6=None, domain="host.example"
        )
        with patch.object(watcher.requests, "post") as post:
            watcher.notify_server_ready("https://hook.test", "Ready!", addresses)

        post.assert_called_once()
        args, kwargs = post.call_args
        assert args[0] == "https://hook.test"
        assert kwargs["json"]["content"] == "Ready! [host.example (1.2.3.4)]"
        post.return_value.raise_for_status.assert_called_once()
