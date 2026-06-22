from __future__ import annotations

import os

import redis
import requests
import sentry_sdk
from loguru import logger
from rq import Queue

from discord_bot import db, games, provisioner
from discord_bot.provisioner import AlreadyDeployedError, ProvisionError

_QUEUE = None

if _QUEUE is None:
    RQ_REDIS_URL = os.getenv("RQ_REDIS_URL", "redis://localhost:6379/0")
    redis_conn = redis.Redis.from_url(RQ_REDIS_URL)
    _QUEUE = Queue(connection=redis_conn)

_PROVISIONER: provisioner.Provisioner | None = None


def get_queue() -> Queue:
    return _QUEUE


def get_provisioner() -> provisioner.Provisioner:
    """Lazily build the provisioner so importing this module needs no API token."""
    global _PROVISIONER
    if _PROVISIONER is None:
        _PROVISIONER = provisioner.Provisioner(provisioner.client_from_env())
    return _PROVISIONER


def _notify(game: games.Game, content: str) -> None:
    """Post a message to the game's Discord channel webhook (best-effort)."""
    webhook = game.discord_channel_webhook
    if not webhook:
        logger.warning("No Discord webhook configured for {g}", g=game.game_name)
        return
    try:
        response = requests.post(webhook, json={"content": content}, timeout=(5, 10))
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 — notification must never crash the job
        logger.error(
            "Failed to post Discord webhook for {g}: {e}", g=game.game_name, e=exc
        )
        sentry_sdk.capture_exception(exc)


def start_server(game: games.Game) -> None:
    lock_name = f"{game.game_name}_server"

    with db.get_redis().lock(lock_name):
        logger.info("Starting {g} server", g=game.game_display_name)
        prov = get_provisioner()
        try:
            result = prov.deploy(game)
        except AlreadyDeployedError as exc:
            # Race-condition fix: a repeated/raced /start is a safe no-op, never a
            # destructive re-apply.
            logger.warning("{e}", e=exc)
            _notify(
                game,
                f"⚠️ {game.game_display_name} server is already running or starting — "
                f"ignoring the start request.",
            )
            return
        except ProvisionError as exc:
            logger.error(
                "Failed to start {g} server: {e}", g=game.game_display_name, e=exc
            )
            sentry_sdk.capture_exception(exc.cause or exc)
            _notify(
                game,
                f"❌ Failed to start {game.game_display_name} (step: {exc.step}). {exc}",
            )
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error starting {g}", g=game.game_display_name)
            sentry_sdk.capture_exception(exc)
            _notify(
                game, f"❌ Unexpected error starting {game.game_display_name}: {exc}"
            )
            return

        logger.info(
            "Finished starting {g} server @ {ip}",
            g=game.game_display_name,
            ip=result.ipv4,
        )


def stop_server(game: games.Game) -> None:
    lock_name = f"{game.game_name}_server"

    with db.get_redis().lock(lock_name):
        logger.info("Stopping {g} server", g=game.game_display_name)
        _notify(game, game.bot_message_started)
        prov = get_provisioner()
        try:
            prov.destroy(game)
        except ProvisionError as exc:
            logger.error(
                "Failed to stop {g} server: {e}", g=game.game_display_name, e=exc
            )
            sentry_sdk.capture_exception(exc.cause or exc)
            _notify(
                game,
                f"❌ Failed to stop {game.game_display_name} (step: {exc.step}). {exc}",
            )
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error stopping {g}", g=game.game_display_name)
            sentry_sdk.capture_exception(exc)
            _notify(
                game, f"❌ Unexpected error stopping {game.game_display_name}: {exc}"
            )
            return

        _notify(game, game.bot_message_finished)
        logger.info("Finished stopping {g} server", g=game.game_display_name)


def start_valheim_server() -> None:
    start_server(game=games.VALHEIM)


def stop_valheim_server() -> None:
    stop_server(game=games.VALHEIM)


def start_factorio_server() -> None:
    start_server(game=games.FACTORIO)


def stop_factorio_server() -> None:
    stop_server(game=games.FACTORIO)


def start_enshrouded_server() -> None:
    start_server(game=games.ENSHROUDED)


def stop_enshrouded_server() -> None:
    stop_server(game=games.ENSHROUDED)


def start_abiotic_factor_server() -> None:
    start_server(game=games.ABIOTIC_FACTOR)


def stop_abiotic_factor_server() -> None:
    stop_server(game=games.ABIOTIC_FACTOR)


def start_windrose_server() -> None:
    start_server(game=games.WINDROSE)


def stop_windrose_server() -> None:
    stop_server(game=games.WINDROSE)
