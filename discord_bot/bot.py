# Sentry must initialize before anything else is imported.
from . import sentry  # noqa: F401  # isort: skip

import os
from typing import TYPE_CHECKING

import hikari
import lightbulb
from loguru import logger

from discord_bot import (
    db,
    jobs,
)
from discord_bot.games import ALL_GAMES

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from discord_bot.games import Game

GUILD_ID = int(os.environ["GUILD_ID"])
ALLOWED_CHANNEL_IDS = os.environ["CHANNEL_IDS"].split(",")

COMMAND_PREFIX = "dev-" if os.getenv("ENV") == "dev" else ""

COMMAND_COOLDOWN_SECONDS = 60

bot = hikari.GatewayBot(token=os.environ["BOT_TOKEN"])
client = lightbulb.client_from_app(bot, default_enabled_guilds=[GUILD_ID])
bot.subscribe(hikari.StartingEvent, client.start)


def is_authorized_channel(channel_id: str) -> bool:
    return channel_id in ALLOWED_CHANNEL_IDS


async def authorize(ctx: lightbulb.Context) -> bool:
    if not is_authorized_channel(str(ctx.channel_id)):
        logger.warning(
            "Received {command} command from unauthorized channel {channel} by user {username}",
            username=ctx.user.username,
            channel=ctx.channel_id,
            command=ctx.command_data.name,
        )
        await ctx.respond("ERROR: This command is not allowed in this channel!")
        return False

    return True


def log_command(ctx: lightbulb.Context) -> None:
    logger.debug(
        "Received {command} command from channel {channel} by user {username}",
        username=ctx.user.username,
        channel=ctx.channel_id,
        command=ctx.command_data.name,
    )


async def cooldown(ctx: lightbulb.Context, seconds: int) -> bool:
    is_on_cooldown, ttl = db.get_cooldown(ctx.command_data.name)

    if is_on_cooldown:
        logger.warning(
            "Received {command} command on cooldown in channel {channel} by user {username}, cooldown left is {ttl}",
            username=ctx.user.username,
            channel=ctx.channel_id,
            command=ctx.command_data.name,
            ttl=ttl,
        )

        await ctx.respond(
            f"ERROR: This command is on cooldown! Please retry later. ({ttl}s left)"
        )
        return False

    db.set_cooldown(ctx.command_data.name, seconds)
    return True


# Handlers keyed by command name (sans COMMAND_PREFIX), e.g. "start-valheim".
# Exposed for the tests, which drive every command through its handler.
HANDLERS: dict[str, Callable[[lightbulb.Context], Coroutine[None, None, None]]] = {}


def _register_game_command(game: Game, action: str) -> None:
    """Generate and register the start/stop slash command for one game."""
    job = getattr(jobs, f"{action}_{game.tf_var_prefix}_server")

    if action == "start":
        description = f"Starts the {game.game_display_name} dedicated server."
        response = (
            f"{game.game_display_name} start trigger received, "
            "this may take a few minutes"
        )
    else:
        description = f"Stops the {game.game_display_name} dedicated server."
        response = "Server stop trigger received, this may take a few minutes"

    async def handler(ctx: lightbulb.Context) -> None:
        if not await authorize(ctx):
            return
        if not await cooldown(ctx, COMMAND_COOLDOWN_SECONDS):
            return

        log_command(ctx)

        await ctx.respond(response)

        jobs.get_queue().enqueue(job)

    command_name = f"{action}-{game.game_name}"
    HANDLERS[command_name] = handler

    @client.register
    class GameCommand(
        lightbulb.SlashCommand,
        name=f"{COMMAND_PREFIX}{command_name}",
        description=description,
    ):
        @lightbulb.invoke
        async def invoke(self, ctx: lightbulb.Context) -> None:
            await ctx.defer()
            await handler(ctx)


for _game in ALL_GAMES.values():
    for _action in ("start", "stop"):
        _register_game_command(_game, _action)


@client.register
class Ping(lightbulb.SlashCommand, name=f"{COMMAND_PREFIX}ping", description="pong?"):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        await ctx.defer()
        log_command(ctx)

        message_id = await ctx.respond(f"Pong! (channel_id: {ctx.channel_id})")

        logger.info(
            "Ponged {username}, response message ID {id}",
            username=ctx.user.username,
            id=message_id,
        )


if __name__ == "__main__":
    bot.run()
