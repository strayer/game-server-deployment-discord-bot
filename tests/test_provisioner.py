"""Unit tests for ``discord_bot.provisioner`` with a fully mocked hcloud client.

No real network, SSH, sleeps or ssh-keygen happen here: the Hetzner ``Client`` is a
``MagicMock`` wired up by the ``wired`` fixture, ``cloud_init.render`` and
``remote_ops.stop_and_backup`` are patched, and ``_read_local_pubkey`` is stubbed to a
fixed value. ``Provisioner`` is built with ``poll_interval=0`` / ``shutdown_timeout=1``
so any wait loop is fast.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest
from hcloud import APIException

from discord_bot import provisioner as prov
from discord_bot.games import ABIOTIC_FACTOR, ALL_GAMES, FACTORIO, WINDROSE
from discord_bot.provisioner import (
    AlreadyDeployedError,
    DeployResult,
    ProvisionError,
    Provisioner,
)

LOCAL_PUBKEY = "ssh-ed25519 AAAALOCAL bot"
SERVER_IP = "203.0.113.10"
EGRESS_IP = "198.51.100.7"


def _action() -> MagicMock:
    """A hcloud action whose wait_until_finished() is a harmless no-op."""
    action = MagicMock(name="action")
    action.wait_until_finished.return_value = None
    return action


def _make_server(status: str = "running") -> MagicMock:
    server = MagicMock(name="server")
    server.public_net.ipv4.ip = SERVER_IP
    server.status = status
    server.reload.return_value = None
    server.delete.return_value = _action()
    server.shutdown.return_value = _action()
    return server


def _make_volume(
    volume_id: int = 42, attached_server: object | None = None
) -> MagicMock:
    volume = MagicMock(name="volume")
    volume.id = volume_id
    volume.name = "windrose-install"
    volume.server = attached_server
    volume.detach.return_value = _action()
    return volume


@pytest.fixture
def wired():
    """Return ``(provisioner, client)`` with a fully mocked, success-path client.

    Defaults (overridable per test):
      * no existing server / firewall / volume
      * ssh key already present and matching the local pubkey (no create/delete)
      * create() calls return objects exposing the action/server/volume attributes
        the provisioner reads.
    """
    client = MagicMock(name="client")

    # Queries: nothing exists by default.
    client.servers.get_by_name.return_value = None
    client.firewalls.get_by_name.return_value = None
    client.volumes.get_by_name.return_value = None

    # SSH keys: an existing matching key (so the default path neither creates nor deletes).
    existing_key = MagicMock(name="existing_ssh_key")
    existing_key.public_key = LOCAL_PUBKEY
    client.ssh_keys.get_by_name.return_value = existing_key
    all_keys = [MagicMock(name="key_a"), MagicMock(name="key_b")]
    client.ssh_keys.get_all.return_value = all_keys
    client.ssh_keys.create.return_value = MagicMock(name="created_ssh_key")
    client.ssh_keys.delete.return_value = None

    # Firewall create -> .firewall + .actions (list).
    created_firewall = MagicMock(name="created_firewall")
    client.firewalls.create.return_value = MagicMock(
        firewall=created_firewall, actions=[_action()]
    )
    client.firewalls.delete.return_value = None

    # Volume create -> .volume + .action.
    created_volume = _make_volume(volume_id=99)
    client.volumes.create.return_value = MagicMock(
        volume=created_volume, action=_action()
    )

    # Server create -> .server + .action + .next_actions.
    created_server = _make_server()
    client.servers.create.return_value = MagicMock(
        server=created_server, action=_action(), next_actions=[_action()]
    )

    provisioner = Provisioner(client, shutdown_timeout=1, poll_interval=0)

    with (
        patch.object(Provisioner, "_read_local_pubkey", return_value=LOCAL_PUBKEY),
        patch.object(prov.cloud_init, "render", return_value="#cloud-config\n"),
        patch.object(prov.remote_ops, "stop_and_backup") as stop_and_backup,
        patch.object(prov.time, "sleep", return_value=None),
        patch.object(prov, "_detect_egress_ipv4", return_value=EGRESS_IP),
    ):
        # Expose the stop_and_backup mock for destroy tests.
        client._stop_and_backup = stop_and_backup
        yield provisioner, client


# --------------------------------------------------------------------------- deploy


class TestDeploy:
    def test_happy_path_non_volume(self, wired):
        provisioner, client = wired

        result = provisioner.deploy(FACTORIO)

        assert isinstance(result, DeployResult)
        assert result.server_name == "factorio-server"
        assert result.ipv4 == SERVER_IP

        client.servers.create.assert_called_once()
        kwargs = client.servers.create.call_args.kwargs
        assert kwargs["name"] == "factorio-server"
        assert kwargs["location"].name == "fsn1"
        assert kwargs["server_type"].name == "ccx23"
        assert kwargs["volumes"] is None
        assert kwargs["automount"] is None
        # firewalls must be exactly the firewall we just created.
        created_firewall = client.firewalls.create.return_value.firewall
        assert kwargs["firewalls"] == [created_firewall]
        # ssh_keys must be the full get_all() list.
        assert kwargs["ssh_keys"] == client.ssh_keys.get_all.return_value

    def test_start_guard_refuses_when_server_exists(self, wired):
        provisioner, client = wired
        client.servers.get_by_name.return_value = _make_server()

        with pytest.raises(AlreadyDeployedError):
            provisioner.deploy(FACTORIO)

        client.servers.create.assert_not_called()
        client.firewalls.create.assert_not_called()
        client.firewalls.delete.assert_not_called()
        client.ssh_keys.create.assert_not_called()

    def test_volume_game_existing_volume(self, wired):
        provisioner, client = wired
        existing_vol = _make_volume(volume_id=42, attached_server=None)
        client.volumes.get_by_name.return_value = existing_vol

        with patch.object(
            prov.cloud_init, "render", return_value="#cloud-config\n"
        ) as render:
            provisioner.deploy(WINDROSE)

        client.volumes.create.assert_not_called()
        kwargs = client.servers.create.call_args.kwargs
        assert kwargs["volumes"] == [existing_vol]
        assert kwargs["automount"] is False
        # cloud_init.render must receive the existing volume's id.
        assert render.call_args.kwargs["volume_id"] == 42

    def test_volume_game_creates_missing_volume(self, wired):
        provisioner, client = wired
        client.volumes.get_by_name.return_value = None

        provisioner.deploy(WINDROSE)

        client.volumes.create.assert_called_once()
        vkwargs = client.volumes.create.call_args.kwargs
        assert vkwargs["size"] == 50
        assert vkwargs["format"] == "ext4"
        assert vkwargs["location"].name == "nbg1"
        # The create action was waited on.
        client.volumes.create.return_value.action.wait_until_finished.assert_called_once()
        # The freshly created volume is what gets attached.
        created_volume = client.volumes.create.return_value.volume
        assert client.servers.create.call_args.kwargs["volumes"] == [created_volume]

    def test_rollback_on_server_create_api_error(self, wired):
        provisioner, client = wired
        client.servers.create.side_effect = APIException(
            code="x", message="boom", details=None
        )

        with pytest.raises(ProvisionError) as excinfo:
            provisioner.deploy(FACTORIO)

        assert not isinstance(excinfo.value, AlreadyDeployedError)
        # Rollback deleted the firewall it created.
        created_firewall = client.firewalls.create.return_value.firewall
        client.firewalls.delete.assert_called_once_with(created_firewall)


# ----------------------------------------------------------------- ssh key handling


class TestSSHKey:
    def test_key_missing_creates_it(self, wired):
        provisioner, client = wired
        client.ssh_keys.get_by_name.return_value = None

        provisioner._ensure_bot_ssh_key()

        client.ssh_keys.create.assert_called_once()
        assert client.ssh_keys.create.call_args.kwargs["public_key"] == LOCAL_PUBKEY
        client.ssh_keys.delete.assert_not_called()

    def test_key_matches_no_create_no_delete(self, wired):
        provisioner, client = wired
        # Default fixture key already matches LOCAL_PUBKEY.
        provisioner._ensure_bot_ssh_key()

        client.ssh_keys.create.assert_not_called()
        client.ssh_keys.delete.assert_not_called()

    def test_key_mismatch_no_live_server_recreates(self, wired):
        provisioner, client = wired
        stale = MagicMock(name="stale_key")
        stale.public_key = "ssh-ed25519 AAAASTALE old"
        client.ssh_keys.get_by_name.return_value = stale
        client.servers.get_by_name.return_value = None  # no live server for any game

        provisioner._ensure_bot_ssh_key()

        client.ssh_keys.delete.assert_called_once_with(stale)
        client.ssh_keys.create.assert_called_once()
        assert client.ssh_keys.create.call_args.kwargs["public_key"] == LOCAL_PUBKEY

    def test_key_mismatch_with_live_server_refuses(self, wired):
        provisioner, client = wired
        stale = MagicMock(name="stale_key")
        stale.public_key = "ssh-ed25519 AAAASTALE old"
        client.ssh_keys.get_by_name.return_value = stale
        # Some managed server is live.
        client.servers.get_by_name.return_value = _make_server()

        with pytest.raises(ProvisionError) as excinfo:
            provisioner._ensure_bot_ssh_key()

        assert excinfo.value.step == "ssh-key"
        client.ssh_keys.delete.assert_not_called()


# ---------------------------------------------------------------------- firewall


class TestFirewall:
    def test_recreate_deletes_stale_then_creates_with_rules(self, wired):
        provisioner, client = wired
        stale_fw = MagicMock(name="stale_firewall")
        client.firewalls.get_by_name.return_value = stale_fw

        provisioner._recreate_firewall(FACTORIO)

        # Stale firewall deleted before a fresh one is created.
        client.firewalls.delete.assert_called_once_with(stale_fw)
        client.firewalls.create.assert_called_once()

        rules = client.firewalls.create.call_args.kwargs["rules"]
        protos = {(r.protocol, getattr(r, "port", None)) for r in rules}
        assert ("icmp", None) in protos
        assert ("tcp", "22") in protos
        # FACTORIO spec ports.
        assert ("udp", "60001-60999") in protos
        assert ("udp", "34197") in protos

    def test_ssh_rule_restricted_to_egress_ip(self, wired):
        provisioner, client = wired

        provisioner._recreate_firewall(FACTORIO)

        rules = client.firewalls.create.call_args.kwargs["rules"]
        by_key = {(r.protocol, getattr(r, "port", None)): r for r in rules}
        # SSH is locked to the bot's egress IPv4...
        assert by_key[("tcp", "22")].source_ips == [f"{EGRESS_IP}/32"]
        # ...while ICMP and the game ports stay open to the world.
        assert by_key[("icmp", None)].source_ips == prov._ANY_SOURCE
        assert by_key[("udp", "34197")].source_ips == prov._ANY_SOURCE

    def test_egress_detection_failure_aborts_deploy(self, wired):
        provisioner, client = wired

        with patch.object(
            prov,
            "_detect_egress_ipv4",
            side_effect=ProvisionError("firewall", "no egress IP"),
        ):
            with pytest.raises(ProvisionError) as excinfo:
                provisioner.deploy(FACTORIO)

        assert excinfo.value.step == "firewall"
        # Fail-closed: no server is created when the egress IP can't be determined.
        client.servers.create.assert_not_called()


# ----------------------------------------------------------------------- destroy


class TestDestroy:
    def test_no_server_is_idempotent(self, wired):
        provisioner, client = wired
        client.servers.get_by_name.return_value = None
        existing_fw = MagicMock(name="leftover_firewall")
        client.firewalls.get_by_name.return_value = existing_fw

        provisioner.destroy(FACTORIO)

        client.firewalls.delete.assert_called_once_with(existing_fw)
        client._stop_and_backup.assert_not_called()

    def test_happy_non_volume(self, wired):
        provisioner, client = wired
        server = _make_server()
        client.servers.get_by_name.return_value = server
        existing_fw = MagicMock(name="firewall")
        client.firewalls.get_by_name.return_value = existing_fw

        provisioner.destroy(FACTORIO)

        client._stop_and_backup.assert_called_once_with(FACTORIO, SERVER_IP)
        server.delete.assert_called_once()
        server.delete.return_value.wait_until_finished.assert_called_once()
        # No shutdown/detach for a non-volume game.
        server.shutdown.assert_not_called()
        client.firewalls.delete.assert_called_once_with(existing_fw)

    def test_happy_volume_game_order(self, wired):
        provisioner, client = wired
        server = _make_server(status="off")  # already powered off
        client.servers.get_by_name.return_value = server
        volume = _make_volume(volume_id=42, attached_server=MagicMock())
        client.volumes.get_by_name.return_value = volume

        provisioner.destroy(WINDROSE)

        client._stop_and_backup.assert_called_once_with(WINDROSE, SERVER_IP)
        server.shutdown.assert_called_once()
        volume.detach.assert_called_once()
        server.delete.assert_called_once()
        # Install volumes are sacred: detach only, never delete.
        client.volumes.delete.assert_not_called()
        volume.delete.assert_not_called()

    def test_shutdown_timeout_aborts(self, wired):
        provisioner, client = wired
        server = _make_server(status="running")  # never powers off
        client.servers.get_by_name.return_value = server
        volume = _make_volume(volume_id=42, attached_server=MagicMock())
        client.volumes.get_by_name.return_value = volume

        with pytest.raises(ProvisionError) as excinfo:
            provisioner.destroy(WINDROSE)

        assert excinfo.value.step == "shutdown"
        server.delete.assert_not_called()
        volume.detach.assert_not_called()

    def test_backup_failure_aborts(self, wired):
        provisioner, client = wired
        server = _make_server()
        client.servers.get_by_name.return_value = server
        client._stop_and_backup.side_effect = subprocess.CalledProcessError(1, "ssh")

        with pytest.raises(ProvisionError) as excinfo:
            provisioner.destroy(FACTORIO)

        assert excinfo.value.step == "backup"
        server.delete.assert_not_called()


# ------------------------------------------------------------------- client_from_env


class TestClientFromEnv:
    def test_missing_token_raises_config_error(self):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ProvisionError) as excinfo:
                prov.client_from_env()
        assert excinfo.value.step == "config"

    @pytest.mark.parametrize("var", ["HCLOUD_TOKEN", "TF_VAR_hcloud_token"])
    def test_token_present_returns_client(self, var):
        from hcloud import Client

        with patch.dict("os.environ", {var: "dummy-token"}, clear=True):
            client = prov.client_from_env()
        assert isinstance(client, Client)


def test_all_games_registry_sane():
    """Sanity: the games referenced by these tests are all in ALL_GAMES."""
    for game in (FACTORIO, WINDROSE, ABIOTIC_FACTOR):
        assert ALL_GAMES[game.game_name] is game
