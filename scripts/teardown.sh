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

json_message=$(jq -n \
  --arg content "$BOT_MESSAGE_STARTED" \
  --arg avatar_url "$BOT_GAME_PERSONA_AVATAR_URL" \
  --arg username "$BOT_GAME_PERSONA_NAME" \
  '{$content, $avatar_url, $username}')

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
if [ "$GAME_NAME" = "factorio" ]; then
  ssh -i "/sshkey/sshkey.$GAME_NAME" -o "StrictHostKeyChecking no" "root@$SERVER_IP" "docker stop $GAME_NAME-server"
fi
sleep 5

echo "Backing up gamedata…"
"$SCRIPT_DIR/backup.sh"

echo "Destroying resources…"

cd "$SCRIPT_DIR"/../terraform/"$GAME_NAME"
terraform destroy -auto-approve -var="ssh_pubkey=foobar" \
  -var="game_persona_bot_name=$BOT_GAME_PERSONA_NAME" \
  -var="game_persona_bot_avatar_url=$BOT_GAME_PERSONA_AVATAR_URL" \
  -var="bot_server_started_message=foobar" \
  -var="bot_server_ready_message=foobar"

json_message=$(jq -n \
  --arg content "$BOT_MESSAGE_FINISHED" \
  --arg avatar_url "$BOT_AVATAR_URL" \
  --arg username "$BOT_NAME" \
  '{$content, $avatar_url, $username}')

curl -i \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -X POST \
  --data "$json_message" \
  "$discord_channel_webhook"
