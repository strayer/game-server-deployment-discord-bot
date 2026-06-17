"""Render per-game cloud-init ``user_data`` from the relocated ``.tftpl`` templates.

The templates were authored for Terraform's ``templatefile()`` and use ``${ name }``
interpolation. We render them with Jinja2 configured to use **Terraform-compatible
delimiters** (``variable_start_string='${'`` / ``variable_end_string='}'``) so the
files render *unchanged*: literal single braces (``{ "log-driver": ... }``, the jq
shorthand ``'{$content}'``) and shell ``$VAR`` references pass through untouched, and
``StrictUndefined`` makes any missing variable fail loudly instead of emitting a blank.

SECURITY: the rendered output contains restic/AWS credentials and server passwords.
NEVER log the rendered template. ``render()`` returns the string; callers must treat
it as a secret.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from jinja2 import Environment, StrictUndefined

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from discord_bot.games import Game

_TEMPLATE_DIR = Path(__file__).parent

# Matches the Terraform interpolations in the templates: ``${ some_name }``.
_PLACEHOLDER_RE = re.compile(r"\$\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}")

# Context keys sourced from the Game object rather than TF_VAR_* env vars.
_BOT_STARTED_KEY = "bot_server_started_message"
_BOT_READY_KEY = "bot_server_ready_message"
_VOLUME_ID_SUFFIX = "_volume_id"


class CloudInitError(RuntimeError):
    """Raised when a cloud-init template cannot be rendered (missing variables)."""


def template_path(game_name: str) -> Path:
    return _TEMPLATE_DIR / f"{game_name}.tftpl"


def _read_template(game_name: str) -> str:
    path = template_path(game_name)
    if not path.is_file():
        raise CloudInitError(f"cloud-init template not found: {path}")
    return path.read_text(encoding="utf-8")


def extract_placeholders(template_text: str) -> set[str]:
    """Return the set of ``${ name }`` variables referenced in a template."""
    return set(_PLACEHOLDER_RE.findall(template_text))


def build_context(
    game: Game, template_text: str, *, volume_id: int | str | None = None
) -> dict[str, str]:
    """Resolve every template placeholder to a concrete value.

    Resolution order per placeholder:
      * ``bot_server_*_message`` -> the Game's bot message fields,
      * ``*_volume_id``          -> the resolved/created volume id,
      * ``TF_VAR_<name>`` env    -> the environment (secrets, server config),
      * ``spec.cloud_init_defaults[<name>]`` -> non-secret Terraform defaults.

    Raises ``CloudInitError`` listing every placeholder that could not be resolved,
    so a misconfigured environment fails before a server is ever created.
    """
    context: dict[str, str] = {}
    missing: list[str] = []

    for name in sorted(extract_placeholders(template_text)):
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


def _environment() -> Environment:
    return Environment(
        variable_start_string="${",
        variable_end_string="}",
        # Block/comment syntax is unused by the templates; keep the defaults but
        # StrictUndefined guarantees a hard failure on any unexpected variable.
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )


def render(game: Game, *, volume_id: int | str | None = None) -> str:
    """Render ``user_data`` for ``game``. Result is SECRET — never log it."""
    template_text = _read_template(game.game_name)
    context = build_context(game, template_text, volume_id=volume_id)
    template = _environment().from_string(template_text)
    return template.render(**context)
