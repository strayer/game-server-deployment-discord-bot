#!/usr/bin/env bash
set -euo pipefail

cd "$GAMEDATA_PATH"

EXCLUDE_ARGS=()

if [ "$GAME_NAME" = "abiotic-factor" ]; then
  EXCLUDE_ARGS+=(--exclude "Logs")
  EXCLUDE_ARGS+=(--exclude "Config/CrashReportClient")
  EXCLUDE_ARGS+=(--exclude "SaveGames/Server/Backups")
fi

if [ "$GAME_NAME" = "windrose" ]; then
  # /gamedata = R5/Saved. Keep SaveProfiles/ (the world saves); drop the
  # engine logs and crash-reporter config, which only accumulate junk.
  EXCLUDE_ARGS+=(--exclude "Logs")
  EXCLUDE_ARGS+=(--exclude "Config/CrashReportClient")
fi

restic backup -H "$GAME_NAME" --tag "$BACKUP_TAG" --no-cache -v "${EXCLUDE_ARGS[@]}" .
