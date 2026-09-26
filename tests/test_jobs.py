"""Behavior tests for the rq job layer (discord_bot.jobs).

These pin the worker-side contract that the refactorings must preserve:
  * a raced/repeated start is a safe no-op that warns on Discord,
  * provisioning failures are reported to Discord + Sentry and never crash the job,
  * a failed Discord notification never crashes the job either,
  * stop posts the "shutting down" / "destroyed" messages around the teardown,
  * DNS: a failed deSEC check refuses the start; publish/clear failures only warn.

The provisioner and requests are mocked; Redis (locks) is fakeredis via conftest.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from discord_bot import games, jobs
from discord_bot.dns import DesecClient, DnsError
from discord_bot.provisioner import AlreadyDeployedError, DeployResult, ProvisionError

GAME = games.VALHEIM
WEBHOOK_ENV = {"TF_VAR_valheim_discord_channel_webhook": "https://discord.test/hook"}


@pytest.fixture(autouse=True)
def dns_client():
    """No job test may reach deSEC: every job gets this mock client."""
    client = MagicMock(spec=DesecClient)
    client.hostname.side_effect = lambda sub: f"{sub}.games.example.tld"
    with patch.object(jobs.dns, "client_from_env", return_value=client):
        yield client


@pytest.fixture
def prov():
    """A mocked provisioner with a success-path deploy/destroy."""
    prov = MagicMock(name="provisioner")
    prov.deploy.return_value = DeployResult(
        server_name=GAME.server_name, ipv4="203.0.113.10", ipv6="2001:db8::1"
    )
    prov.destroy.return_value = None
    return prov


@pytest.fixture
def wired(prov, patch_db_redis):
    """Patch the job module's provisioner + webhook env; yield (provisioner, post)."""
    with (
        patch.object(jobs, "get_provisioner", return_value=prov),
        patch.object(jobs.requests, "post") as post,
        patch.dict(os.environ, WEBHOOK_ENV),
    ):
        yield prov, post


def _posted_contents(post) -> list[str]:
    return [call.kwargs["json"]["content"] for call in post.call_args_list]


class TestStartServer:
    def test_success_deploys_and_stays_quiet(self, wired):
        prov, post = wired

        jobs.start_server(GAME)

        prov.deploy.assert_called_once_with(GAME)
        # The "ready" webhook comes from the on-VM watcher, not this job.
        post.assert_not_called()

    def test_already_deployed_is_a_warning_not_a_failure(self, wired):
        prov, post = wired
        prov.deploy.side_effect = AlreadyDeployedError(GAME)

        jobs.start_server(GAME)  # must not raise

        contents = _posted_contents(post)
        assert len(contents) == 1
        assert "already running" in contents[0]
        prov.destroy.assert_not_called()

    def test_provision_error_notifies_with_step(self, wired):
        prov, post = wired
        cause = RuntimeError("api down")
        prov.deploy.side_effect = ProvisionError("firewall", "boom", cause=cause)

        with patch.object(jobs.sentry_sdk, "capture_exception") as capture:
            jobs.start_server(GAME)  # must not raise

        contents = _posted_contents(post)
        assert len(contents) == 1
        assert "Failed to start" in contents[0]
        assert "firewall" in contents[0]
        capture.assert_called_once_with(cause)

    def test_unexpected_error_notifies_and_does_not_raise(self, wired):
        prov, post = wired
        prov.deploy.side_effect = KeyError("surprise")

        with patch.object(jobs.sentry_sdk, "capture_exception") as capture:
            jobs.start_server(GAME)

        contents = _posted_contents(post)
        assert len(contents) == 1
        assert "Unexpected error" in contents[0]
        capture.assert_called_once()

    def test_runs_under_the_per_game_lock(self, wired, fake_redis):
        prov, _ = wired
        locked_during_deploy = []

        def deploy(game):
            locked_during_deploy.append(bool(fake_redis.exists("valheim_server")))
            return DeployResult(server_name=game.server_name, ipv4="203.0.113.10")

        prov.deploy.side_effect = deploy

        jobs.start_server(GAME)

        # The race-condition fix: deploy happens while holding the game lock,
        # and the lock is released afterwards.
        assert locked_during_deploy == [True]
        assert not fake_redis.exists("valheim_server")

    def test_stop_holds_the_same_lock_as_start(self, wired, fake_redis):
        # Start and stop must share one lock name — that shared key is what makes
        # a /stop wait for a running /start deploy (Redis provides the blocking;
        # this pins that both jobs target the same lock).
        prov, _ = wired
        locked_during_destroy = []

        prov.destroy.side_effect = lambda game: locked_during_destroy.append(
            bool(fake_redis.exists("valheim_server"))
        )

        jobs.stop_server(GAME)

        assert locked_during_destroy == [True]
        assert not fake_redis.exists("valheim_server")


class TestStopServer:
    def test_success_posts_started_then_finished(self, wired):
        prov, post = wired

        jobs.stop_server(GAME)

        prov.destroy.assert_called_once_with(GAME)
        contents = _posted_contents(post)
        assert contents == [GAME.bot_message_started, GAME.bot_message_finished]

    def test_unexpected_error_notifies_and_does_not_raise(self, wired):
        prov, post = wired
        prov.destroy.side_effect = KeyError("surprise")

        with patch.object(jobs.sentry_sdk, "capture_exception") as capture:
            jobs.stop_server(GAME)

        contents = _posted_contents(post)
        assert "Unexpected error" in contents[-1]
        assert GAME.bot_message_finished not in contents
        capture.assert_called_once()

    def test_provision_error_reports_and_skips_finished_message(self, wired):
        prov, post = wired
        prov.destroy.side_effect = ProvisionError("backup", "restic failed")

        with patch.object(jobs.sentry_sdk, "capture_exception"):
            jobs.stop_server(GAME)  # must not raise

        contents = _posted_contents(post)
        assert contents[0] == GAME.bot_message_started
        assert "Failed to stop" in contents[1]
        assert "backup" in contents[1]
        assert GAME.bot_message_finished not in contents


class TestNotify:
    def test_missing_webhook_skips_post(self, prov, patch_db_redis):
        env = {k: "" for k in WEBHOOK_ENV}
        with (
            patch.object(jobs, "get_provisioner", return_value=prov),
            patch.object(jobs.requests, "post") as post,
            patch.dict(os.environ, env),
        ):
            jobs.stop_server(GAME)

        post.assert_not_called()
        prov.destroy.assert_called_once()

    def test_webhook_failure_never_crashes_the_job(self, wired):
        prov, post = wired
        post.side_effect = ConnectionError("discord down")

        with patch.object(jobs.sentry_sdk, "capture_exception"):
            jobs.stop_server(GAME)  # must not raise

        prov.destroy.assert_called_once_with(GAME)


class TestJobWiring:
    """Every per-game rq entry point must target its own game."""

    @pytest.mark.parametrize(
        "game", games.ALL_GAMES.values(), ids=lambda g: g.game_name
    )
    def test_start_job_targets_its_game(self, game):
        with patch.object(jobs, "start_server") as start_server:
            getattr(jobs, f"start_{game.tf_var_prefix}_server")()
        start_server.assert_called_once_with(game=game)

    @pytest.mark.parametrize(
        "game", games.ALL_GAMES.values(), ids=lambda g: g.game_name
    )
    def test_stop_job_targets_its_game(self, game):
        with patch.object(jobs, "stop_server") as stop_server:
            getattr(jobs, f"stop_{game.tf_var_prefix}_server")()
        stop_server.assert_called_once_with(game=game)


class TestDns:
    def test_failed_check_refuses_start(self, wired, dns_client):
        prov, post = wired
        dns_client.check.side_effect = DnsError("deSEC GET /domains/x/: HTTP 401")

        jobs.start_server(GAME)

        prov.deploy.assert_not_called()
        [content] = _posted_contents(post)
        assert content.startswith("❌ DNS configuration invalid")
        assert "HTTP 401" in content

    def test_publishes_deploy_addresses(self, wired, dns_client):
        jobs.start_server(GAME)

        dns_client.publish.assert_called_once_with(
            "valheim", "203.0.113.10", "2001:db8::1"
        )

    def test_publish_failure_warns_and_keeps_server(self, wired, dns_client):
        prov, post = wired
        dns_client.publish.side_effect = DnsError("HTTP 403")

        with patch.object(jobs.sentry_sdk, "capture_exception") as capture:
            jobs.start_server(GAME)

        prov.destroy.assert_not_called()
        capture.assert_called_once()
        [content] = _posted_contents(post)
        assert content.startswith("⚠️ DNS update for valheim.games.example.tld")
        assert "203.0.113.10, 2001:db8::1" in content

    @pytest.mark.parametrize(
        "error",
        [AlreadyDeployedError(GAME), ProvisionError("server", "boom")],
        ids=["already-deployed", "provision-error"],
    )
    def test_no_publish_when_deploy_fails(self, wired, dns_client, error):
        wired[0].deploy.side_effect = error

        jobs.start_server(GAME)

        dns_client.publish.assert_not_called()

    def test_stop_clears_after_destroy(self, wired, dns_client):
        prov, post = wired
        calls = []
        prov.destroy.side_effect = lambda game: calls.append("destroy")
        dns_client.clear.side_effect = lambda sub: calls.append(f"clear {sub}")

        jobs.stop_server(GAME)

        assert calls == ["destroy", "clear valheim"]
        assert _posted_contents(post)[-1] == GAME.bot_message_finished

    def test_failed_destroy_keeps_records(self, wired, dns_client):
        wired[0].destroy.side_effect = ProvisionError("backup", "restic failed")

        jobs.stop_server(GAME)

        dns_client.clear.assert_not_called()

    def test_config_error_on_stop_warns_and_tears_down(self, wired):
        prov, post = wired

        with patch.object(
            jobs.dns, "client_from_env", side_effect=DnsError("DESEC_TOKEN is missing")
        ):
            jobs.stop_server(GAME)

        prov.destroy.assert_called_once_with(GAME)
        contents = _posted_contents(post)
        assert contents[1] == "⚠️ DNS records cannot be cleared: DESEC_TOKEN is missing"
        assert contents[-1] == GAME.bot_message_finished
