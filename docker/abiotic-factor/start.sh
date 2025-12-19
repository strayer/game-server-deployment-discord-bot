#!/usr/bin/env bash
set -euo pipefail

# Configuration defaults
MAX_SERVER_PLAYERS="${MAX_SERVER_PLAYERS:-6}"
PORT="${PORT:-7777}"
QUERY_PORT="${QUERY_PORT:-27015}"
WORLD_SAVE_NAME="${WORLD_SAVE_NAME:-Cascade}"

if [ -z "${SERVER_NAME:-}" ]; then
  echo "SERVER_NAME environment variable is not set." >&2
  exit 1
fi

if [ -z "${SERVER_PASSWORD:-}" ]; then
  echo "SERVER_PASSWORD environment variable is not set." >&2
  exit 1
fi

# Build server arguments
SERVER_ARGS=(
  "-useperfthreads"
  "-Port=${PORT}"
  "-QueryPort=${QUERY_PORT}"
  "-MaxServerPlayers=${MAX_SERVER_PLAYERS}"
  "-SteamServerName=${SERVER_NAME}"
  "-ServerPassword=${SERVER_PASSWORD}"
  "-WorldSaveName=${WORLD_SAVE_NAME}"
)

# Add any additional arguments
if [ -n "${ADDITIONAL_ARGS:-}" ]; then
  # shellcheck disable=SC2206
  SERVER_ARGS+=($ADDITIONAL_ARGS)
fi

cd "$GAME_PATH"

# Set up log redirection to stdout
LOG_DIR="${GAME_PATH}/AbioticFactor/Saved/Logs"
mkdir -p "$LOG_DIR"
ln -sf /proc/1/fd/1 "${LOG_DIR}/AbioticFactor.log"

echo "Starting Abiotic Factor Dedicated Server"
exec "${STEAMCMD_PATH}/compatibilitytools.d/GE-Proton${PROTON_VERSION}/proton" run "${GAME_PATH}/AbioticFactor/Binaries/Win64/AbioticFactorServer-Win64-Shipping.exe" "${SERVER_ARGS[@]}"