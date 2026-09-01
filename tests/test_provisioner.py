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
    Provisioner,
    ProvisionError,
)

LOCAL_PUBKEY = "ssh-ed25519 AAAALOCAL bot"
SERVER_IP = "203.0.113.10"


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
        # A distinct id (not the _make_volume default) so the assertions below can't
        # pass by coincidence against the mock default.
        existing_vol = _make_volume(volume_id=7, attached_server=None)
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
        assert render.call_args.kwargs["volume_id"] == 7

    def test_volume_game_creates_missing_volume(self, wired):
        provisioner, client = wired
        client.volumes.get_by_name.return_value = None

        provisioner.deploy(WINDROSE)

        client.volumes.create.assert_called_once()
        vkwargs = client.volumes.create.call_args.kwargs
        # Pin the spec->API wiring, not the literal size (which is tuned over time).
        assert vkwargs["size"] == WINDROSE.spec.volume_size_gb
        assert vkwargs["format"] == WINDROSE.spec.volume_format
        assert vkwargs["location"].name == WINDROSE.spec.location
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

    def test_rollback_deletes_created_server_on_post_create_failure(self, wired):
        # Failure AFTER the server exists (waiting for the boot action) must roll
        # back the server itself, not just the firewall — otherwise the start-guard
        # blocks every future /start against an orphaned half-deployed server.
        provisioner, client = wired
        created_server = client.servers.create.return_value.server
        client.servers.create.return_value.action.wait_until_finished.side_effect = (
            APIException(code="x", message="boot failed", details=None)
        )

        with pytest.raises(ProvisionError):
            provisioner.deploy(FACTORIO)

        created_server.delete.assert_called_once()
        created_server.delete.return_value.wait_until_finished.assert_called_once()
        created_firewall = client.firewalls.create.return_value.firewall
        client.firewalls.delete.assert_called_once_with(created_firewall)

    def test_failing_rollback_does_not_mask_the_original_error(self, wired):
        # Rollback is best-effort: if deleting the half-created server fails too,
        # the ORIGINAL deploy error must still surface (and the firewall cleanup
        # must still be attempted).
        provisioner, client = wired
        created_server = client.servers.create.return_value.server
        client.servers.create.return_value.action.wait_until_finished.side_effect = (
            APIException(code="x", message="boot failed", details=None)
        )
        created_server.delete.side_effect = APIException(
            code="y", message="delete also failed", details=None
        )

        with pytest.raises(ProvisionError) as excinfo:
            provisioner.deploy(FACTORIO)

        assert "boot failed" in str(excinfo.value)
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

    def test_liveness_api_error_surfaces_as_ssh_key_error(self, wired):
        provisioner, client = wired
        stale = MagicMock(name="stale_key")
        stale.public_key = "ssh-ed25519 AAAASTALE old"
        client.ssh_keys.get_by_name.return_value = stale
        # The shared-key liveness scan hits a (non-retryable) API error.
        client.servers.get_by_name.side_effect = APIException(
            code="boom", message="kaboom", details=None
        )

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

        # Record the actual call order — each step assumes the previous one
        # (backup needs the live OS, detach needs the box off, delete last).
        order = []

        def record(name, ret=None):
            def _side_effect(*args, **kwargs):
                order.append(name)
                return ret

            return _side_effect

        client._stop_and_backup.side_effect = record("backup")
        server.shutdown.side_effect = record("shutdown", _action())
        volume.detach.side_effect = record("detach", _action())
        server.delete.side_effect = record("delete", _action())

        provisioner.destroy(WINDROSE)

        client._stop_and_backup.assert_called_once_with(WINDROSE, SERVER_IP)
        assert order == ["backup", "shutdown", "detach", "delete"]
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

    def test_backup_failure_on_volume_game_touches_nothing(self, wired):
        # The save-critical branch: a failed backup must abort BEFORE shutdown,
        # detach or delete — the world data on the volume stays untouched.
        provisioner, client = wired
        server = _make_server()
        client.servers.get_by_name.return_value = server
        volume = _make_volume(volume_id=42, attached_server=MagicMock())
        client.volumes.get_by_name.return_value = volume
        client._stop_and_backup.side_effect = subprocess.CalledProcessError(1, "ssh")

        with pytest.raises(ProvisionError) as excinfo:
            provisioner.destroy(WINDROSE)

        assert excinfo.value.step == "backup"
        server.shutdown.assert_not_called()
        volume.detach.assert_not_called()
        server.delete.assert_not_called()
        client.firewalls.delete.assert_not_called()

    def test_already_detached_volume_skips_detach(self, wired):
        # Idempotency during recovery from a partial teardown: a volume that is
        # not attached must not be detached again, and the teardown continues.
        provisioner, client = wired
        server = _make_server(status="off")
        client.servers.get_by_name.return_value = server
        volume = _make_volume(volume_id=42, attached_server=None)
        client.volumes.get_by_name.return_value = volume

        provisioner.destroy(WINDROSE)

        volume.detach.assert_not_called()
        server.delete.assert_called_once()


# ------------------------------------------------------------------------- retries


class TestRetry:
    """The @_retry policy matters for dependency updates: hcloud/tenacity changes
    that alter which errors retry would change operational behavior unnoticed."""

    def test_retryable_api_error_is_retried(self, wired):
        provisioner, client = wired
        client.servers.get_by_name.side_effect = [
            APIException(code="conflict", message="locked", details=None),
            _make_server(),
        ]

        # tenacity sleeps between attempts via the real time module.
        with patch("time.sleep"):
            assert provisioner.server_ip(FACTORIO) == SERVER_IP

        assert client.servers.get_by_name.call_count == 2

    def test_non_retryable_api_error_raises_immediately(self, wired):
        provisioner, client = wired
        client.servers.get_by_name.side_effect = APIException(
            code="unauthorized", message="bad token", details=None
        )

        with patch("time.sleep"), pytest.raises(APIException):
            provisioner.server_ip(FACTORIO)

        assert client.servers.get_by_name.call_count == 1


# -------------------------------------------------------------------- queries / keys


class TestQueries:
    def test_server_ip_when_deployed(self, wired):
        provisioner, client = wired
        client.servers.get_by_name.return_value = _make_server()

        assert provisioner.server_ip(FACTORIO) == SERVER_IP
        assert provisioner.is_deployed(FACTORIO) is True

    def test_server_ip_when_absent(self, wired):
        provisioner, client = wired
        client.servers.get_by_name.return_value = None

        assert provisioner.server_ip(FACTORIO) is None
        assert provisioner.is_deployed(FACTORIO) is False


class TestReadLocalPubkey:
    def test_existing_pubkey_is_read_and_stripped(self, tmp_path):
        key_path = tmp_path / "sshkey"
        (tmp_path / "sshkey.pub").write_text(f"{LOCAL_PUBKEY}\n")
        provisioner = Provisioner(MagicMock(), ssh_key_path=str(key_path))

        assert provisioner._read_local_pubkey() == LOCAL_PUBKEY

    def test_missing_keypair_is_generated(self, tmp_path):
        key_path = tmp_path / "keys" / "sshkey"
        provisioner = Provisioner(MagicMock(), ssh_key_path=str(key_path))

        def fake_keygen(cmd, check):
            (tmp_path / "keys" / "sshkey.pub").write_text(f"{LOCAL_PUBKEY}\n")

        with patch.object(prov.subprocess, "run", side_effect=fake_keygen) as run:
            assert provisioner._read_local_pubkey() == LOCAL_PUBKEY

        cmd = run.call_args.args[0]
        assert cmd[0] == "ssh-keygen"
        assert "ed25519" in cmd
        # The parent dir must exist before ssh-keygen writes into it.
        assert (tmp_path / "keys").is_dir()


# ------------------------------------------------------------------- client_from_env


class TestClientFromEnv:
    def test_missing_token_raises_config_error(self):
        with (
            patch.dict("os.environ", {}, clear=True),
            pytest.raises(ProvisionError) as excinfo,
        ):
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
