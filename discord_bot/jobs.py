import os

import redis
from loguru import logger
from rq import Queue

from discord_bot import db, games

_QUEUE = None

if _QUEUE is None:
    RQ_REDIS_URL = os.getenv("RQ_REDIS_URL", "redis://localhost:6379/0")
    redis_conn = redis.Redis.from_url(RQ_REDIS_URL)
    _QUEUE = Queue(connection=redis_conn)


def get_queue() -> Queue:
    return _QUEUE


def start_server(game: games.Game) -> None:
    lock_name = f"{game.game_name}_server"

    with db.get_redis().lock(lock_name):
        logger.info(f"Starting {game.game_display_name} server")
        game.start_server()
        logger.info(f"Finished starting {game.game_display_name} server")


def stop_server(game: games.Game) -> None:
    lock_name = f"{game.game_name}_server"

    with db.get_redis().lock(lock_name):
        logger.info(f"Stopping {game.game_display_name} server")
        game.stop_server()
        logger.info(f"Finished stopping {game.game_display_name} server")


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
