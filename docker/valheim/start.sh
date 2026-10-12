#!/usr/bin/env bash
set -euo pipefail

export LD_LIBRARY_PATH=/opt/valheim/linux64:${LD_LIBRARY_PATH:-}

cd /opt/valheim

# Optional BepInEx modpack. VALHEIM_MODPACK_URL points at a zip rooted at the
# Valheim server folder (BepInEx/, doorstop_libs/, ...). Empty = vanilla server.
# The pack is the source of truth: every start removes the previous BepInEx
# install, including its config, and unpacks the zip fresh.
if [ -n "${VALHEIM_MODPACK_URL:-}" ]; then
  echo "--> Installing Valheim modpack from $VALHEIM_MODPACK_URL"

  rm -rf BepInEx doorstop_libs doorstop_config.ini .doorstop_version winhttp.dll

  curl -fsSL --retry 5 --retry-all-errors --retry-delay 5 -o /tmp/modpack.zip "$VALHEIM_MODPACK_URL"
  python3 -m zipfile -e /tmp/modpack.zip /opt/valheim
  rm -f /tmp/modpack.zip

  if [ ! -f BepInEx/core/BepInEx.Preloader.dll ] || [ ! -f doorstop_libs/libdoorstop_x64.so ]; then
    echo "--> Modpack has no BepInEx/core/BepInEx.Preloader.dll or doorstop_libs/libdoorstop_x64.so, refusing to start" >&2
    exit 1
  fi

  export DOORSTOP_ENABLED=1
  export DOORSTOP_TARGET_ASSEMBLY=./BepInEx/core/BepInEx.Preloader.dll
  export LD_LIBRARY_PATH=/opt/valheim/doorstop_libs:$LD_LIBRARY_PATH
  export LD_PRELOAD=libdoorstop_x64.so${LD_PRELOAD:+:$LD_PRELOAD}

  echo "--> Modpack installed, starting with BepInEx"
fi

exec /opt/valheim/valheim_server.x86_64 -nographics -batchmode -name "$VALHEIM_SERVER_NAME" -port 2456 -world "$VALHEIM_SERVER_WORLD" -password "$VALHEIM_SERVER_PASSWORD" -public 0
