"""Tests for per-game configuration (discord_bot.games)."""

from discord_bot import games


class TestGameInstances:
    """Verify game instances are configured correctly."""

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

    def test_all_games_registry(self):
        assert set(games.ALL_GAMES) == {
            "valheim",
            "factorio",
            "enshrouded",
            "abiotic-factor",
            "windrose",
        }


class TestNamingConvention:
    """The Hetzner API is keyed by these names; they must be stable."""

    def test_server_name(self):
        for name, game in games.ALL_GAMES.items():
            assert game.server_name == f"{name}-server"

    def test_firewall_name(self):
        for name, game in games.ALL_GAMES.items():
            assert game.firewall_name == f"{name}-firewall"

    def test_tf_var_prefix_underscores_hyphens(self):
        assert games.ABIOTIC_FACTOR.tf_var_prefix == "abiotic_factor"
        assert games.VALHEIM.tf_var_prefix == "valheim"


class TestServerSpec:
    """Per-game infra parameters that replace terraform/<game>/main.tf."""

    def test_firewall_ports_match_terraform(self):
        assert games.VALHEIM.spec.firewall_ports == (("udp", "2456-2457"),)
        assert games.FACTORIO.spec.firewall_ports == (
            ("udp", "60001-60999"),
            ("udp", "34197"),
        )
        assert games.ENSHROUDED.spec.firewall_ports == (
            ("udp", "15636-15637"),
            ("tcp", "15636-15637"),
        )
        assert games.ABIOTIC_FACTOR.spec.firewall_ports == (
            ("udp", "7777"),
            ("udp", "27015"),
        )
        assert games.WINDROSE.spec.firewall_ports == (
            ("tcp", "7777"),
            ("udp", "7777"),
        )

    def test_volume_backed_games(self):
        assert games.ABIOTIC_FACTOR.spec.has_volume
        assert games.ABIOTIC_FACTOR.volume_name == "abiotic-factor-install"
        assert games.WINDROSE.spec.has_volume
        assert games.WINDROSE.volume_name == "windrose-install"

    def test_non_volume_games(self):
        for game in (games.VALHEIM, games.FACTORIO, games.ENSHROUDED):
            assert not game.spec.has_volume

    def test_volume_games_have_size_and_format(self):
        for game in (games.ABIOTIC_FACTOR, games.WINDROSE):
            assert game.spec.volume_size_gb is not None
            assert game.spec.volume_format == "ext4"
