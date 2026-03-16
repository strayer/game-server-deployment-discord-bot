#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)

for game in valheim factorio enshrouded abiotic-factor; do
  export TF_DATA_DIR="$TF_DATA_DIR_BASE"/"$game"
  mkdir -p "$TF_DATA_DIR"
  mkdir -p "/terraform/state/$game"

  (
    cd "$SCRIPT_DIR/../terraform/$game"
    terraform init -lockfile=readonly -reconfigure
  )
done

exec "$@"
