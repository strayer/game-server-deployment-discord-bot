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

attempt=1

while true; do
  echo "--> Attempt $attempt"

  set +e
  "$STEAMCMD_PATH/steamcmd.sh" "${STEAM_ARGS[@]}" | tee /tmp/steamcmd_output.txt
  exit_code=${PIPESTATUS[0]}
  set -e

  if [ $exit_code -eq 0 ]; then
    echo "--> Game installed successfully"
    exit 0
  fi

  if grep -q "Missing configuration" /tmp/steamcmd_output.txt; then
    echo "--> Got 'Missing configuration' error, retrying..."
    attempt=$((attempt + 1))
  else
    echo "--> Failed with non-retryable error (exit code: $exit_code)"
    exit $exit_code
  fi
done
