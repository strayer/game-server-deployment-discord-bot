import os
import pathlib
import subprocess
from loguru import logger

SCRIPTS_PATH = pathlib.Path(__file__).parent.parent.joinpath("scripts")


class Game:
    def __init__(
        self,
        game_name: str,
        game_display_name: str,
        bot_message_server_started: str,
        bot_message_server_ready: str,
        bot_message_started: str,
        bot_message_finished: str,
    ):
        self.game_name = game_name
        self.game_display_name = game_display_name
        self.default_env = {
            **os.environ,
            "GAME_NAME": self.game_name,
            "GAME_DISPLAY_NAME": self.game_display_name,
        }
        self.bot_message_server_started = bot_message_server_started
        self.bot_message_server_ready = bot_message_server_ready
        self.bot_message_started = bot_message_started
        self.bot_message_finished = bot_message_finished

    def start_server(self):
        try:
            subprocess.run(
                [SCRIPTS_PATH / "start.sh"],
                check=True,
                env={
                    **self.default_env,
                    "BOT_MESSAGE_SERVER_STARTED": self.bot_message_server_started,
                    "BOT_MESSAGE_SERVER_READY": self.bot_message_server_ready,
                },
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to start {self.game_display_name} server: {e}")
            raise

    def stop_server(self):
        try:
            subprocess.run(
                [SCRIPTS_PATH / "teardown.sh"],
                check=True,
                env={
                    **self.default_env,
                    "BOT_MESSAGE_STARTED": self.bot_message_started,
                    "BOT_MESSAGE_FINISHED": self.bot_message_finished,
                },
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to stop {self.game_display_name} server: {e}")
            raise


VALHEIM = Game(
    game_name="valheim",
    game_display_name="Valheim",
    bot_message_server_started="Valheim has been installed and save state backup restored, starting game server...",
    bot_message_server_ready="Valheim server is ready!",
    bot_message_started="Valheim is shutting down...",
    bot_message_finished="Valheim server has been destroyed and world backed up 🧨💥",
)

FACTORIO = Game(
    game_name="factorio",
    game_display_name="Factorio",
    bot_message_server_started="Factorio has been installed and save state backup restored, starting game server...",
    bot_message_server_ready="Factorio server is ready!",
    bot_message_started="Factorio is shutting down...",
    bot_message_finished="Factorio server has been destroyed and savegame backed up 🧨💥",
)

ENSHROUDED = Game(
    game_name="enshrouded",
    game_display_name="Enshrouded",
    bot_message_server_started="Enshrouded has been installed and save state backup restored, starting game server...",
    bot_message_server_ready="Enshrouded server is ready!",
    bot_message_started="Enshrouded is shutting down...",
    bot_message_finished="Enshrouded server has been destroyed and savegame backed up 🧨💥",
)
