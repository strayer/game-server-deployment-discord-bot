from . import sentry  # noqa: F401
import os

import lightbulb
from loguru import logger

from discord_bot import (
    db,
    jobs,
)

GUILD_ID = int(os.environ["GUILD_ID"])
ALLOWED_CHANNEL_IDS = os.environ["CHANNEL_IDS"].split(",")

COMMAND_PREFIX = "dev-" if os.getenv("ENV") == "dev" else ""

bot = lightbulb.BotApp(token=os.environ["BOT_TOKEN"])


def member_name(ctx: lightbulb.SlashContext):
    if ctx.member:
        return ctx.member.display_name
    return ctx.author.username


def is_authorized_channel(channel_id: str) -> bool:
    return channel_id in ALLOWED_CHANNEL_IDS


async def authorize(ctx: lightbulb.SlashContext) -> bool:
    if not is_authorized_channel(str(ctx.channel_id)):
        logger.warning(
            "Received {command} command from unauthorized channel {channel} by user {username}",
            username=ctx.author.username,
            channel=ctx.channel_id,
            command=ctx.command.name,
        )
        await ctx.respond("ERROR: This command is not allowed in this channel!")
        return False

    return True


def log_command(ctx: lightbulb.SlashContext) -> None:
    logger.debug(
        "Received {command} command from channel {channel} by user {username}",
        username=ctx.author.username,
        channel=ctx.channel_id,
        command=ctx.command.name,
    )


async def cooldown(ctx: lightbulb.SlashContext, seconds: int) -> bool:
    is_on_cooldown, ttl = db.get_cooldown(ctx.command.name)

    if is_on_cooldown:
        logger.warning(
            "Received {command} command on cooldown in channel {channel} by user {username}, cooldown left is {ttl}",
            username=ctx.author.username,
            channel=ctx.channel_id,
            command=ctx.command.name,
            ttl=ttl,
        )

        await ctx.respond(f"ERROR: This command is on cooldown! Please retry later. ({ttl}s left)")
        return False

    db.set_cooldown(ctx.command.name, seconds)
    return True


@bot.command
@lightbulb.command(
    f"{COMMAND_PREFIX}start-valheim",
    "Starts the Valheim dedicated server.",
    guilds=[GUILD_ID],
    auto_defer=True,
)
@lightbulb.implements(lightbulb.SlashCommand)
async def start_valheim(ctx: lightbulb.SlashContext) -> None:
    if not await authorize(ctx):
        return
    if not await cooldown(ctx, 60):
        return

    log_command(ctx)

    await ctx.respond("Valheim start trigger received, this may take a few minutes")

    jobs.get_queue().enqueue(jobs.start_valheim_server)


@bot.command
@lightbulb.command(
    f"{COMMAND_PREFIX}stop-valheim",
    "Stops the Valheim dedicated server.",
    guilds=[GUILD_ID],
    auto_defer=True,
)
@lightbulb.implements(lightbulb.SlashCommand)
async def stop_valheim(ctx: lightbulb.SlashContext) -> None:
    if not await authorize(ctx):
        return
    if not await cooldown(ctx, 60):
        return

    log_command(ctx)

    await ctx.respond("Server stop trigger received, this may take a few minutes")

    jobs.get_queue().enqueue(jobs.stop_valheim_server)


@bot.command
@lightbulb.command(
    f"{COMMAND_PREFIX}start-factorio",
    "Starts the Factorio dedicated server.",
    guilds=[GUILD_ID],
    auto_defer=True,
)
@lightbulb.implements(lightbulb.SlashCommand)
async def start_factorio(ctx: lightbulb.SlashContext) -> None:
    if not await authorize(ctx):
        return
    if not await cooldown(ctx, 60):
        return

    log_command(ctx)

    await ctx.respond("Factorio start trigger received, this may take a few minutes")

    jobs.get_queue().enqueue(jobs.start_factorio_server)


@bot.command
@lightbulb.command(
    f"{COMMAND_PREFIX}stop-factorio",
    "Stops the Factorio dedicated server.",
    guilds=[GUILD_ID],
    auto_defer=True,
)
@lightbulb.implements(lightbulb.SlashCommand)
async def stop_factorio(ctx: lightbulb.SlashContext) -> None:
    if not await authorize(ctx):
        return
    if not await cooldown(ctx, 60):
        return

    log_command(ctx)

    await ctx.respond("Server stop trigger received, this may take a few minutes")

    jobs.get_queue().enqueue(jobs.stop_factorio_server)


@bot.command
@lightbulb.command(
    f"{COMMAND_PREFIX}start-enshrouded",
    "Starts the Enshrouded dedicated server.",
    guilds=[GUILD_ID],
    auto_defer=True,
)
@lightbulb.implements(lightbulb.SlashCommand)
async def start_enshrouded(ctx: lightbulb.SlashContext) -> None:
    if not await authorize(ctx):
        return
    if not await cooldown(ctx, 60):
        return

    log_command(ctx)

    await ctx.respond("Enshrouded start trigger received, this may take a few minutes")

    jobs.get_queue().enqueue(jobs.start_enshrouded_server)


@bot.command
@lightbulb.command(
    f"{COMMAND_PREFIX}stop-enshrouded",
    "Stops the Enshrouded dedicated server.",
    guilds=[GUILD_ID],
    auto_defer=True,
)
@lightbulb.implements(lightbulb.SlashCommand)
async def stop_enshrouded(ctx: lightbulb.SlashContext) -> None:
    if not await authorize(ctx):
        return
    if not await cooldown(ctx, 60):
        return

    log_command(ctx)

    await ctx.respond("Server stop trigger received, this may take a few minutes")

    jobs.get_queue().enqueue(jobs.stop_enshrouded_server)


@bot.command
@lightbulb.command(f"{COMMAND_PREFIX}ping", "pong?", guilds=[GUILD_ID], auto_defer=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def ping(ctx: lightbulb.SlashContext) -> None:
    global TEST_MESSAGE_ID

    log_command(ctx)

    response = await ctx.respond(f"Pong! (channel_id: {ctx.channel_id})")

    logger.info(
        "Ponged {username}, response message ID {id}",
        username=ctx.author.username,
        id=(await response.message()).id,
    )


if __name__ == "__main__":
    bot.run()
