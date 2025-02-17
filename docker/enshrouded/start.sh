#!/usr/bin/env bash
set -euo pipefail

# Configuration block
ENSHROUDED_CONFIG="$GAME_PATH/enshrouded_server.json"

# Function to handle shutdown
shutdown() {
  echo ""
  echo "Received SIGTERM, shutting down gracefully"
  kill -s INT "$enshrouded_pid"
}

# Function to update JSON config using jq
update_config() {
  local key=$1
  local value=$2
  local tmpfile
  tmpfile=$(mktemp)
  jq --arg v "$value" "$key = \$v" "$ENSHROUDED_CONFIG" >"$tmpfile" && mv "$tmpfile" "$ENSHROUDED_CONFIG"
}

if [ -z "${SERVER_NAME}" ]; then
  echo "SERVER_NAME environment variable is not set." >&2
  exit 1
fi

if [ -z "${SERVER_PASSWORD}" ]; then
  echo "SERVER_PASSWORD environment variable is not set." >&2
  exit 1
fi

# Copy the example configuration file
cp "/opt/enshrouded_server_example.json" "$ENSHROUDED_CONFIG"

# Update server configuration
update_config '.name' "$SERVER_NAME"
update_config '.userGroups[0].password' "$SERVER_PASSWORD"
update_config '.saveDirectory' "$GAMEDATA_PATH/savegame"
update_config '.logDirectory' "/logs"

# Set trap to call shutdown function on SIGTERM
trap 'shutdown' SIGTERM

cd "$GAME_PATH"

echo "Starting Enshrouded Dedicated Server"
"${STEAMCMD_PATH}/compatibilitytools.d/GE-Proton${PROTON_VERSION}/proton" run "${GAME_PATH}/enshrouded_server.exe" &

# Find pid for enshrouded_server.exe
timeout=0
while [ $timeout -lt 11 ]; do
  if ps -e | grep "enshrouded_serv"; then
    enshrouded_pid=$(ps -e | grep "enshrouded_serv" | awk '{print $1}')
    echo "enshrouded_server.exe is running with PID: $enshrouded_pid"
    break
  elif [ $timeout -eq 10 ]; then
    echo "Timed out waiting for enshrouded_server.exe to be running" >&2
    exit 1
  fi
  sleep 6
  timeout=$((timeout + 1))
  echo "Waiting for enshrouded_server.exe to be running..."
done

# Hold us open until we recieve a SIGTERM by opening a job waiting for the process to finish then calling `wait`
tail --pid="$enshrouded_pid" -f /dev/null &
wait

# Handle post SIGTERM from here (SIGTERM will cancel the `wait` immediately even though the job is not done yet)
# Check if the enshrouded_server.exe process is still running, and if so, wait for it to close, indicating full shutdown, then go home
if ps -e | grep "enshrouded_serv"; then
  tail --pid="$enshrouded_pid" -f /dev/null
fi

echo "Enshrouded Dedicated Server has stopped."
