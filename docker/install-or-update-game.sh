#!/usr/bin/env bash
set -euo pipefail

echo "--> Installing game"

STEAM_ARGS=(
  +force_install_dir "$GAME_PATH"
  +login anonymous
  +app_update "$STEAMAPPID"
  +quit
)

# Add windows platform parameter if USE_PROTON is set to "1"
if [ "${USE_PROTON:-}" = "1" ]; then
  STEAM_ARGS=(+@sSteamCmdForcePlatformType windows "${STEAM_ARGS[@]}")
fi

mkdir -p "$GAME_PATH"

"$STEAMCMD_PATH/steamcmd.sh" "${STEAM_ARGS[@]}"
