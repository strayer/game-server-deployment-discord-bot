"""Render per-game cloud-init ``user_data`` from the packaged Jinja2 templates.

Each ``discord_bot/cloud_init/<game>.yaml.j2`` is a cloud-config YAML file with standard
Jinja2 ``{{ name }}`` placeholders. ``StrictUndefined`` makes any unresolved variable a hard
error instead of emitting a blank, so a misconfigured environment fails before a server is
ever created.

SECURITY: the rendered output contains restic/AWS credentials and server passwords.
NEVER log the rendered template. ``render()`` returns the string; callers must treat
it as a secret.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from jinja2 import Environment, StrictUndefined, TemplateError, meta

if TYPE_CHECKING:
    from discord_bot.games import Game

_TEMPLATE_DIR = Path(__file__).parent

# Context keys sourced from the Game object rather than TF_VAR_* env vars.
_BOT_STARTED_KEY = "bot_server_started_message"
_BOT_READY_KEY = "bot_server_ready_message"
_VOLUME_ID_SUFFIX = "_volume_id"


class CloudInitError(RuntimeError):
    """Raised when a cloud-init template cannot be rendered (missing/invalid variables)."""


def template_path(game_name: str) -> Path:
    return _TEMPLATE_DIR / f"{game_name}.yaml.j2"


def _read_template(game_name: str) -> str:
    path = template_path(game_name)
    if not path.is_file():
        raise CloudInitError(f"cloud-init template not found: {path}")
    return path.read_text(encoding="utf-8")


def _environment() -> Environment:
    return Environment(
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )


def referenced_variables(env: Environment, template_text: str) -> set[str]:
    """Return the set of variables referenced by a template (parsed with ``env``)."""
    try:
        return meta.find_undeclared_variables(env.parse(template_text))
    except TemplateError as exc:
        raise CloudInitError(f"cannot parse cloud-init template: {exc}") from exc


def build_context(
    env: Environment,
    game: Game,
    template_text: str,
    *,
    volume_id: int | str | None = None,
) -> dict[str, str]:
    """Resolve every variable the template references to a concrete value.

    Resolution order per variable:
      * ``bot_server_*_message`` -> the Game's bot message fields,
      * ``*_volume_id``          -> the resolved/created volume id,
      * ``TF_VAR_<name>`` env    -> the environment (secrets, server config),
      * ``spec.cloud_init_defaults[<name>]`` -> non-secret defaults.

    Raises ``CloudInitError`` listing every variable that could not be resolved,
    so a misconfigured environment fails before a server is ever created.
    """
    context: dict[str, str] = {}
    missing: list[str] = []

    for name in sorted(referenced_variables(env, template_text)):
        if name == _BOT_STARTED_KEY:
            context[name] = game.bot_message_server_started
        elif name == _BOT_READY_KEY:
            context[name] = game.bot_message_server_ready
        elif name.endswith(_VOLUME_ID_SUFFIX):
            if volume_id is None:
                missing.append(f"{name} (no volume id supplied)")
            else:
                context[name] = str(volume_id)
        elif (env_value := os.environ.get(f"TF_VAR_{name}")) is not None:
            context[name] = env_value
        elif name in game.spec.cloud_init_defaults:
            context[name] = str(game.spec.cloud_init_defaults[name])
        else:
            missing.append(f"{name} (set TF_VAR_{name})")

    if missing:
        raise CloudInitError(
            f"cannot render cloud-init for {game.game_name}; unresolved variables: "
            + ", ".join(missing)
        )

    return context


def render(game: Game, *, volume_id: int | str | None = None) -> str:
    """Render ``user_data`` for ``game``. Result is SECRET — never log it."""
    template_text = _read_template(game.game_name)
    env = _environment()
    context = build_context(env, game, template_text, volume_id=volume_id)
    try:
        return env.from_string(template_text).render(**context)
    except TemplateError as exc:
        raise CloudInitError(
            f"cannot render cloud-init for {game.game_name}: {exc}"
        ) from exc
