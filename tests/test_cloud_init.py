"""Tests for cloud-init template rendering (discord_bot.cloud_init).

Each game's rendered ``user_data`` is pinned to a committed snapshot
(``tests/snapshots/<game>.yaml``) so any change to a template or the renderer shows up
as a reviewable diff. Regenerate after an intentional change with::

    uv run pytest tests/test_cloud_init.py --snapshot-update

The renderer must also fail loudly when a variable cannot be resolved — exercised below
for each resolution source (env var, volume id, and the spec-defaults fallback).
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from discord_bot import cloud_init, games

ALL_GAMES = list(games.ALL_GAMES.values())
_FIXED_VOLUME_ID = 98765
_SNAPSHOT_DIR = Path(__file__).parent / "snapshots"


def _fake_value(name: str) -> str:
    """A readable, deterministic stand-in for a TF_VAR_ value (keeps snapshots legible)."""
    if "webhook" in name:
        return "https://discord.example/api/webhooks/fake"
    if name.endswith("_repo"):
        return "s3:https://s3.example.tld/restic-fake"
    if name.endswith("_password"):
        return "fake-password"
    if name.endswith("_aws_access_key_id"):
        return "FAKEACCESSKEYID"
    if name.endswith("_aws_secret_access_key"):
        return "fake-secret-access-key"
    return f"fake-{name}"


def _env_for(game: games.Game) -> dict[str, str]:
    """Deterministic TF_VAR_* env for ``game``, derived from its template placeholders.

    Excludes the bot-message keys, the volume id, and anything supplied via
    ``spec.cloud_init_defaults`` — those resolve without the environment.
    """
    env_obj = cloud_init._environment()
    text = cloud_init._read_template(game.game_name)
    env: dict[str, str] = {}
    for name in cloud_init.referenced_variables(env_obj, text):
        if name in (cloud_init._BOT_STARTED_KEY, cloud_init._BOT_READY_KEY):
            continue
        if name.endswith(cloud_init._VOLUME_ID_SUFFIX):
            continue
        if name in game.spec.cloud_init_defaults:
            continue
        env[f"TF_VAR_{name}"] = _fake_value(name)
    return env


@pytest.mark.parametrize("game", ALL_GAMES, ids=lambda g: g.game_name)
def test_render_matches_snapshot(game, snapshot):
    snapshot.snapshot_dir = _SNAPSHOT_DIR
    volume_id = _FIXED_VOLUME_ID if game.spec.has_volume else None
    with patch.dict(os.environ, _env_for(game), clear=True):
        rendered = cloud_init.render(game, volume_id=volume_id)
    snapshot.assert_match(rendered, f"{game.game_name}.yaml")


def test_missing_env_var_raises_clear_error():
    """A placeholder with no TF_VAR_ value fails, naming the missing var."""
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(cloud_init.CloudInitError) as exc:
            cloud_init.render(games.FACTORIO)
    assert "TF_VAR_factorio_save_name" in str(exc.value)


@pytest.mark.parametrize(
    "game", [games.ABIOTIC_FACTOR, games.WINDROSE], ids=lambda g: g.game_name
)
def test_volume_game_requires_volume_id(game):
    """The ``*_volume_id`` path fails when no volume id is supplied."""
    with patch.dict(os.environ, _env_for(game), clear=True):
        with pytest.raises(cloud_init.CloudInitError) as exc:
            cloud_init.render(game, volume_id=None)
    assert "volume_id" in str(exc.value)


def test_abiotic_factor_max_players_uses_default():
    """max_players is not in env; it resolves from spec.cloud_init_defaults."""
    env = _env_for(games.ABIOTIC_FACTOR)
    assert "TF_VAR_abiotic_factor_max_players" not in env
    with patch.dict(os.environ, env, clear=True):
        # renders successfully despite no env var -> default applied
        rendered = cloud_init.render(games.ABIOTIC_FACTOR, volume_id=_FIXED_VOLUME_ID)
    assert "MAX_SERVER_PLAYERS=6" in rendered
