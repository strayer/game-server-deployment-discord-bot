#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
. "$SCRIPT_DIR/_base.sh"

if [ "$GAME_NAME" = "valheim" ]; then
  discord_channel_webhook="$TF_VAR_valheim_discord_channel_webhook"
fi

if [ "$GAME_NAME" = "factorio" ]; then
  discord_channel_webhook="$TF_VAR_factorio_discord_channel_webhook"
fi

if [ "$GAME_NAME" = "enshrouded" ]; then
  discord_channel_webhook="$TF_VAR_enshrouded_discord_channel_webhook"
fi

if [ "$GAME_NAME" = "abiotic-factor" ]; then
  discord_channel_webhook="$TF_VAR_abiotic_factor_discord_channel_webhook"
fi

json_message=$(jq -n \
  --arg content "$BOT_MESSAGE_STARTED" \
  '{$content}')

curl -i \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -X POST \
  --data "$json_message" \
  "$discord_channel_webhook"

export_terraform_data_dir
export_server_ip

echo "Stopping $GAME_DISPLAY_NAME server…"
if [ "$GAME_NAME" = "valheim" ]; then
  ssh -i "/sshkey/sshkey.$GAME_NAME" -o "StrictHostKeyChecking no" "root@$SERVER_IP" "docker kill --signal=SIGINT $GAME_NAME-server && docker wait $GAME_NAME-server"
fi
if [ "$GAME_NAME" = "factorio" ] || [ "$GAME_NAME" = "enshrouded" ] || [ "$GAME_NAME" = "abiotic-factor" ]; then
  ssh -i "/sshkey/sshkey.$GAME_NAME" -o "StrictHostKeyChecking no" "root@$SERVER_IP" "docker stop $GAME_NAME-server"
fi
sleep 5

echo "Backing up gamedata…"
"$SCRIPT_DIR/backup.sh"

echo "Destroying resources…"

cd "$SCRIPT_DIR"/../terraform/"$GAME_NAME"
terraform destroy -auto-approve -var="ssh_pubkey=foobar" \
  -var="bot_server_started_message=foobar" \
  -var="bot_server_ready_message=foobar"

json_message=$(jq -n \
  --arg content "$BOT_MESSAGE_FINISHED" \
  '{$content}')

curl -i \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -X POST \
  --data "$json_message" \
  "$discord_channel_webhook"
