import os

import redis

_REDIS = None

if _REDIS is None:
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/1")
    _REDIS = redis.Redis.from_url(REDIS_URL)


def get_redis() -> redis.Redis:
    return _REDIS


def get_cooldown(command_name: str) -> tuple[bool, int]:
    redis = get_redis()
    if redis.get("cooldown_" + command_name) is not None:
        return True, redis.ttl("cooldown_" + command_name)

    return False, 0


def set_cooldown(command_name: str, seconds: int) -> None:
    redis = get_redis()
    redis.set("cooldown_" + command_name, value=1, ex=seconds)
