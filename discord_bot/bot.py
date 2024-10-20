from . import sentry  # noqa: F401
import os
from datetime import datetime

import lightbulb
import sentry_sdk
from loguru import logger

from . import (
    db,
    jobs,
)
from .gpt.personas import (
    ActiveInfrastructurePersona,
    FitzgeraldGallagher,
    HalvarTheSkald,
)

GUILD_ID = int(os.environ["GUILD_ID"])
ALLOWED_CHANNEL_IDS = os.environ["CHANNEL_IDS"].split(",")

COMMAND_PREFIX = "dev-" if os.getenv("ENV") == "dev" else ""

bot = lightbulb.BotApp(token=os.environ["BOT_TOKEN"])


@bot.listen(lightbulb.LightbulbStartedEvent)
async def on_lightbulb_started_event(event: lightbulb.LightbulbStartedEvent):
    logger.debug("Received LightbulbStartedEvent, updating bot username and avatar")

    # this can fail due to rate limiting
    try:
        await event.app.rest.edit_my_user(
            username=ActiveInfrastructurePersona.name,
            avatar=ActiveInfrastructurePersona.avatar_url,
        )
    except Exception as e:
        sentry_sdk.capture_exception(e)
        pass


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
    redis = db.get_redis()
    if redis.get("cooldown_" + ctx.command.name) is not None:
        ttl = redis.ttl("cooldown_" + ctx.command.name)

        logger.warning(
            "Received {command} command on cooldown in channel {channel} by user {username}, cooldown left is {ttl}",
            username=ctx.author.username,
            channel=ctx.channel_id,
            command=ctx.command.name,
            ttl=ttl,
        )

        await ctx.respond(
            str.format(
                ActiveInfrastructurePersona.cooldown_message,
                name=member_name(ctx),
                seconds=ttl,
            )
        )
        return False

    set_cooldown(ctx, seconds)
    return True


def set_cooldown(ctx: lightbulb.SlashContext, seconds: int) -> None:
    redis = db.get_redis()
    redis.set("cooldown_" + ctx.command.name, value=1, ex=seconds)


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

    response = await ActiveInfrastructurePersona.valheim_start_request(member_name(ctx))

    await ctx.respond(response)

    server_started_response = await HalvarTheSkald.server_installed(
        player_name=member_name(ctx),
        infrastructure_persona_name=ActiveInfrastructurePersona.name,
    )
    server_ready_response = await HalvarTheSkald.server_ready()
    jobs.get_queue().enqueue(
        jobs.start_valheim_server, server_started_response, server_ready_response
    )


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

    response = await ActiveInfrastructurePersona.valheim_stop_request(member_name(ctx))

    await ctx.respond(response)

    server_stopping_response = await HalvarTheSkald.server_stopping(
        player_name=member_name(ctx),
        infrastructure_persona_name=ActiveInfrastructurePersona.name,
    )
    stop_finished_response = await ActiveInfrastructurePersona.valheim_stop_finished()
    jobs.get_queue().enqueue(
        jobs.stop_valheim_server, server_stopping_response, stop_finished_response
    )


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

    response = await ActiveInfrastructurePersona.factorio_start_request(
        member_name(ctx)
    )
    await ctx.respond(response)

    server_started_response = await FitzgeraldGallagher.server_installed(
        player_name=member_name(ctx),
        infrastructure_persona_name=ActiveInfrastructurePersona.name,
    )
    server_ready_response = await FitzgeraldGallagher.server_ready()
    jobs.get_queue().enqueue(
        jobs.start_factorio_server, server_started_response, server_ready_response
    )


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

    response = await ActiveInfrastructurePersona.factorio_stop_request(member_name(ctx))

    await ctx.respond(response)

    server_stopping_response = await FitzgeraldGallagher.server_stopping(
        player_name=member_name(ctx),
        infrastructure_persona_name=ActiveInfrastructurePersona.name,
    )
    stop_finished_response = await ActiveInfrastructurePersona.factorio_stop_finished()
    jobs.get_queue().enqueue(
        jobs.stop_factorio_server, server_stopping_response, stop_finished_response
    )


@bot.command
@lightbulb.command(f"{COMMAND_PREFIX}ping", "pong?", guilds=[GUILD_ID], auto_defer=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def ping(ctx: lightbulb.SlashContext) -> None:
    log_command(ctx)

    response = await ActiveInfrastructurePersona.ping(member_name(ctx))

    await ctx.respond(f"{response} (channel_id: {ctx.channel_id})")


@bot.command
@lightbulb.command(
    f"{COMMAND_PREFIX}thank-you-bella", "☺️", guilds=[GUILD_ID], auto_defer=True
)
@lightbulb.implements(lightbulb.SlashCommand)
async def thankyoubella(ctx: lightbulb.SlashContext) -> None:
    if not await cooldown(ctx, 10):
        return

    log_command(ctx)

    response = await ActiveInfrastructurePersona.thank_you(member_name(ctx))

    await ctx.respond(response)


@bot.command
@lightbulb.command(
    f"{COMMAND_PREFIX}hey-bella", "☺️", guilds=[GUILD_ID], auto_defer=True
)
@lightbulb.implements(lightbulb.SlashCommand)
async def heybella(ctx: lightbulb.SlashContext) -> None:
    if not await cooldown(ctx, 10):
        return

    log_command(ctx)

    response = await ActiveInfrastructurePersona.hey(member_name(ctx))

    await ctx.respond(response)


@bot.command
@lightbulb.command(f"{COMMAND_PREFIX}tuesday", "🕹️", guilds=[GUILD_ID], auto_defer=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def tuesday(ctx: lightbulb.SlashContext) -> None:
    if not await cooldown(ctx, 10):
        return

    log_command(ctx)

    if datetime.now().weekday() == 1:
        response = await ActiveInfrastructurePersona.tuesday(member_name(ctx))
    else:
        response = await ActiveInfrastructurePersona.not_tuesday(member_name(ctx))

    await ctx.respond(response)


@bot.command
@lightbulb.command(
    f"{COMMAND_PREFIX}fuck-you-greg", "🕹️", guilds=[GUILD_ID], auto_defer=True
)
@lightbulb.implements(lightbulb.SlashCommand)
async def fuck_you_greg(ctx: lightbulb.SlashContext) -> None:
    if not await cooldown(ctx, 10):
        return

    log_command(ctx)

    response = await ActiveInfrastructurePersona.fuck_you_greg(member_name(ctx))

    await ctx.respond(response)


if __name__ == "__main__":
    bot.run()
