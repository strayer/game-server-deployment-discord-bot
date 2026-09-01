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

# steamcmd frequently returns transient errors for anonymous app downloads -
# most commonly "Missing configuration", but also bare non-zero exits (e.g. code 8)
# on a subsequent attempt. Retry on ANY non-zero exit up to a bounded number of
# attempts with a short backoff, rather than only on the "Missing configuration"
# string (which previously caused a fatal bail-out when a retry returned exit 8).
MAX_ATTEMPTS="${STEAMCMD_MAX_ATTEMPTS:-8}"
attempt=1

while true; do
  echo "--> Attempt $attempt of $MAX_ATTEMPTS"

  set +e
  "$STEAMCMD_PATH/steamcmd.sh" "${STEAM_ARGS[@]}" | tee /tmp/steamcmd_output.txt
  exit_code=${PIPESTATUS[0]}
  set -e

  if [ "$exit_code" -eq 0 ]; then
    echo "--> Game installed successfully"
    exit 0
  fi

  if [ $attempt -ge "$MAX_ATTEMPTS" ]; then
    echo "--> Failed after $attempt attempts (last exit code: $exit_code)"
    exit "$exit_code"
  fi

  echo "--> steamcmd attempt $attempt failed (exit code: $exit_code), retrying..."
  attempt=$((attempt + 1))
  sleep 5
done
