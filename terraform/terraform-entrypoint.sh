#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)

for game in valheim factorio enshrouded; do
  export TF_DATA_DIR="$TF_DATA_DIR_BASE"/"$game"
  mkdir -p "$TF_DATA_DIR"

  (
    cd "$SCRIPT_DIR/../terraform/$game"
    terraform init -lockfile=readonly -reconfigure -backend-config="bucket=$TERRAFORM_BACKEND_BUCKET"
  )
done

exec "$@"
