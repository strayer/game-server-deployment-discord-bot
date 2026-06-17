#!/usr/bin/env bash
set -euo pipefail

# Configuration defaults
MAX_PLAYERS="${MAX_PLAYERS:-10}"
SERVER_PORT="${SERVER_PORT:-7777}"
USE_DIRECT_CONNECTION="${USE_DIRECT_CONNECTION:-true}"
DIRECT_CONNECTION_PROXY_ADDRESS="${DIRECT_CONNECTION_PROXY_ADDRESS:-0.0.0.0}"
P2P_PROXY_ADDRESS="${P2P_PROXY_ADDRESS:-127.0.0.1}"
USER_SELECTED_REGION="${USER_SELECTED_REGION:-}"

if [ -z "${SERVER_NAME:-}" ]; then
  echo "SERVER_NAME environment variable is not set." >&2
  exit 1
fi

# SERVER_PASSWORD may be empty (public server) but must be defined.
SERVER_PASSWORD="${SERVER_PASSWORD:-}"

PROTON_DIR="${STEAMCMD_PATH}/compatibilitytools.d/GE-Proton${PROTON_VERSION}"
PROTON="${PROTON_DIR}/proton"
WINESERVER="${PROTON_DIR}/files/bin/wineserver"
WINEPREFIX="${STEAM_COMPAT_DATA_PATH}/pfx"

SERVER_EXEC="${GAME_PATH}/R5/Binaries/Win64/WindroseServer-Win64-Shipping.exe"
SERVER_DESC="${GAME_PATH}/R5/ServerDescription.json"
# ServerDescription.json lives on the install volume, but holds the WorldIslandId that
# must match the world in the (separately backed-up) save dir. Mirror it into the save
# volume so backups capture it and it can be restored alongside the world.
BACKUP_SERVER_DESC="${GAMEDATA_PATH}/ServerDescription.json"
# The engine's own stdout (-STDOUT) does not survive the Proton/Wine boundary, so we
# tail the on-disk log to the container's stdout instead. It lives under the save dir,
# which is symlinked to $GAMEDATA_PATH.
LOG_FILE="${GAME_PATH}/R5/Saved/Logs/R5.log"
tail_pid=""

export STEAM_COMPAT_DATA_PATH
export STEAM_COMPAT_CLIENT_INSTALL_PATH="${STEAMCMD_PATH}"
export WINEDEBUG="${WINEDEBUG:--all}"

cd "$GAME_PATH"

# Recreate the save symlink at runtime (the volume mount covers the image's symlink).
mkdir -p "${GAME_PATH}/R5"
ln -sfn "$GAMEDATA_PATH" "${GAME_PATH}/R5/Saved"

if [ ! -f "$SERVER_EXEC" ]; then
  echo "Could not find server executable at: $SERVER_EXEC" >&2
  exit 1
fi

# Graceful shutdown: wineserver -k is synchronous and triggers Wine's proper
# shutdown so RocksDB flushes the world to disk before exit.
shutdown() {
  echo "Received SIGTERM/SIGINT - shutting down Windrose server gracefully"
  WINEPREFIX="$WINEPREFIX" "$WINESERVER" -k >/dev/null 2>&1 || true
  # Stop the log tail only after the server has been signalled, so shutdown/save
  # lines still reach stdout.
  [ -n "$tail_pid" ] && kill "$tail_pid" 2>/dev/null || true
}

# Launch the server via Proton. Args after the exe are passed to the game.
run_server() {
  "$PROTON" run "$SERVER_EXEC" "$@" &
  server_pid=$!
}

# If the install volume has no config but a backed-up copy was restored into the save
# volume (fresh install volume + restored /gamedata), put it back where the game expects
# it. This MUST run before the first-boot check so a restored world skips generation and
# keeps its matching WorldIslandId.
if [ ! -f "$SERVER_DESC" ] && [ -f "$BACKUP_SERVER_DESC" ]; then
  echo "Restoring ServerDescription.json from backup"
  cp "$BACKUP_SERVER_DESC" "$SERVER_DESC"
fi

#
# First boot: the config files only exist after the server has run once.
# Start it briefly to generate ServerDescription.json, then stop it cleanly.
#
if [ ! -f "$SERVER_DESC" ]; then
  echo "First boot - generating default config (ServerDescription.json)"
  run_server -log -STDOUT -UTF8Output

  count=0
  while [ ! -f "$SERVER_DESC" ] && [ $count -lt 180 ]; do
    sleep 2
    count=$((count + 2))
  done

  if [ ! -f "$SERVER_DESC" ]; then
    echo "ServerDescription.json was not generated after ${count}s - aborting" >&2
    WINEPREFIX="$WINEPREFIX" "$WINESERVER" -k >/dev/null 2>&1 || true
    exit 1
  fi

  echo "ServerDescription.json generated - stopping temporary server"
  sleep 5
  WINEPREFIX="$WINEPREFIX" "$WINESERVER" -k >/dev/null 2>&1 || true
  wait "$server_pid" 2>/dev/null || true
  sleep 2
fi

#
# Stamp the fields we control into ServerDescription.json on every boot.
# Identity/world fields (PersistentServerId, WorldIslandId) are left untouched.
#
echo "Patching ServerDescription.json"
tmpfile=$(mktemp)
tr -d '\r' <"$SERVER_DESC" | jq \
  --arg name "$SERVER_NAME" \
  --arg password "$SERVER_PASSWORD" \
  --argjson maxplayers "$MAX_PLAYERS" \
  --argjson directconn "$USE_DIRECT_CONNECTION" \
  --argjson serverport "$SERVER_PORT" \
  --arg dcproxy "$DIRECT_CONNECTION_PROXY_ADDRESS" \
  --arg p2pproxy "$P2P_PROXY_ADDRESS" \
  --arg region "$USER_SELECTED_REGION" \
  '
  .ServerDescription_Persistent.ServerName = $name |
  .ServerDescription_Persistent.MaxPlayerCount = $maxplayers |
  .ServerDescription_Persistent.UseDirectConnection = $directconn |
  .ServerDescription_Persistent.DirectConnectionServerPort = $serverport |
  .ServerDescription_Persistent.DirectConnectionProxyAddress = $dcproxy |
  .ServerDescription_Persistent.P2pProxyAddress = $p2pproxy |
  (if $region != "" then .ServerDescription_Persistent.UserSelectedRegion = $region else . end) |
  (if $password != "" then
     .ServerDescription_Persistent.IsPasswordProtected = true |
     .ServerDescription_Persistent.Password = $password
   else
     .ServerDescription_Persistent.IsPasswordProtected = false |
     .ServerDescription_Persistent.Password = ""
   end)
  ' >"$tmpfile" && mv "$tmpfile" "$SERVER_DESC"

# Mirror the patched config into the save volume so backups capture the current
# WorldIslandId / settings alongside the world.
cp "$SERVER_DESC" "$BACKUP_SERVER_DESC"

trap 'shutdown' SIGTERM SIGINT

echo "Starting Windrose Dedicated Server"
run_server -log

# Mirror the engine's log file to the container's stdout. The engine rotates R5.log
# to R5-backup-<ts>.log and opens a fresh R5.log on each launch, so this only ever
# carries the current boot. -n 0 emits only lines written after we attach (avoids the
# brief window where tail could print the previous log's tail before the rotation);
# -F follows by name and retries across the engine creating/rotating the file.
mkdir -p "$(dirname "$LOG_FILE")"
tail -n 0 -F "$LOG_FILE" 2>/dev/null &
tail_pid=$!

wait "$server_pid"

[ -n "$tail_pid" ] && kill "$tail_pid" 2>/dev/null || true
