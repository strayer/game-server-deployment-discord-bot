#!/usr/bin/env bash
set -euo pipefail

ipv4="$(curl -s4 icanhazip.com)"
ipv6="$(curl -s6 icanhazip.com)"
rdns="$(dig +short -x "$ipv4" | sed 's/\.$//')"

message="$GAME_NAME server starting @ $rdns ($ipv4, $ipv6)"
json_message=$(jq -n --arg content "$message" '{$content}')

curl -i \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -X POST \
  --data "$json_message" \
  "$DISCORD_MAIN_CHANNEL_WEBHOOK"
