"""Tests for cloud-init template rendering (discord_bot.cloud_init).

The key guarantee: all five templates render with no unresolved placeholders, the
literal single-brace constructs survive verbatim, and missing variables fail loudly.
"""

import os
import re
from unittest.mock import patch

import pytest

from discord_bot import cloud_init, games

ALL_GAMES = list(games.ALL_GAMES.values())
_UNRESOLVED_RE = re.compile(r"\$\{[^}]*\}")


def _env_for(game: games.Game) -> dict[str, str]:
    """Build the minimal TF_VAR_* env needed to render ``game``'s template.

    Derived from the template's own placeholders, so it stays correct as templates
    change. Excludes the bot-message keys, the volume id, and any value supplied via
    ``spec.cloud_init_defaults`` (those must resolve without env).
    """
    text = cloud_init._read_template(game.game_name)
    env: dict[str, str] = {}
    for name in cloud_init.extract_placeholders(text):
        if name in (cloud_init._BOT_STARTED_KEY, cloud_init._BOT_READY_KEY):
            continue
        if name.endswith(cloud_init._VOLUME_ID_SUFFIX):
            continue
        if name in game.spec.cloud_init_defaults:
            continue
        env[f"TF_VAR_{name}"] = f"value-for-{name}"
    return env


@pytest.mark.parametrize("game", ALL_GAMES, ids=lambda g: g.game_name)
def test_render_leaves_no_unresolved_placeholders(game):
    volume_id = 12345 if game.spec.has_volume else None
    with patch.dict(os.environ, _env_for(game), clear=True):
        rendered = cloud_init.render(game, volume_id=volume_id)

    leftovers = _UNRESOLVED_RE.findall(rendered)
    assert leftovers == [], f"unresolved placeholders in {game.game_name}: {leftovers}"


@pytest.mark.parametrize("game", ALL_GAMES, ids=lambda g: g.game_name)
def test_render_preserves_literal_braces(game):
    """The jq object shorthand and JSON blocks must pass through untouched."""
    volume_id = 12345 if game.spec.has_volume else None
    with patch.dict(os.environ, _env_for(game), clear=True):
        rendered = cloud_init.render(game, volume_id=volume_id)

    assert '"log-driver": "local"' in rendered
    assert "'{$content}'" in rendered
    # shell variable references (not Terraform interpolation) survive
    assert "$BOT_MESSAGE" in rendered


@pytest.mark.parametrize("game", ALL_GAMES, ids=lambda g: g.game_name)
def test_render_injects_bot_messages(game):
    volume_id = 12345 if game.spec.has_volume else None
    with patch.dict(os.environ, _env_for(game), clear=True):
        rendered = cloud_init.render(game, volume_id=volume_id)

    assert game.bot_message_server_started in rendered
    assert game.bot_message_server_ready in rendered


@pytest.mark.parametrize(
    "game", [games.ABIOTIC_FACTOR, games.WINDROSE], ids=lambda g: g.game_name
)
def test_volume_id_rendered_into_mount(game):
    with patch.dict(os.environ, _env_for(game), clear=True):
        rendered = cloud_init.render(game, volume_id=98765)

    assert "scsi-0HC_Volume_98765" in rendered


@pytest.mark.parametrize(
    "game", [games.ABIOTIC_FACTOR, games.WINDROSE], ids=lambda g: g.game_name
)
def test_volume_game_requires_volume_id(game):
    with patch.dict(os.environ, _env_for(game), clear=True):
        with pytest.raises(cloud_init.CloudInitError):
            cloud_init.render(game, volume_id=None)


def test_missing_env_var_raises_clear_error():
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(cloud_init.CloudInitError) as exc:
            cloud_init.render(games.FACTORIO)
    # error should name the missing TF_VAR for actionability
    assert "TF_VAR_factorio_save_name" in str(exc.value)


def test_abiotic_factor_max_players_uses_default():
    """max_players is not in env; it must come from spec.cloud_init_defaults."""
    env = _env_for(games.ABIOTIC_FACTOR)
    assert "TF_VAR_abiotic_factor_max_players" not in env
    with patch.dict(os.environ, env, clear=True):
        # renders successfully despite no env var -> default applied
        rendered = cloud_init.render(games.ABIOTIC_FACTOR, volume_id=1)
    assert _UNRESOLVED_RE.findall(rendered) == []
