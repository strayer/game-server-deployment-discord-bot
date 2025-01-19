#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)

pushd "$SCRIPT_DIR" >/dev/null

./install-steamcmd.sh
./install-or-update-game.sh

popd

exec "$@"
