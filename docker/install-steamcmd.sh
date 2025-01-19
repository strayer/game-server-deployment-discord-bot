#!/usr/bin/env bash
set -euo pipefail

PROTON_URL="https://github.com/GloriousEggroll/proton-ge-custom/releases/download/GE-Proton${PROTON_VERSION}/GE-Proton${PROTON_VERSION}.tar.gz"

if [ ! -e "$STEAMCMD_PATH/steamcmd.sh" ]; then
  echo "--> Installing steamcmd"

  mkdir -p "$STEAMCMD_PATH"
  cd "$STEAMCMD_PATH"

  curl -LO https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz \
    && tar xf steamcmd_linux.tar.gz \
    && chmod +x steamcmd.sh \
    && rm steamcmd_linux.tar.gz
fi

echo "--> Installing or updating Steam"

"${STEAMCMD_PATH}/steamcmd.sh" +quit

mkdir -p /home/steam/.steam

[ ! -L "${STEAM_SDK64_PATH}" ] && ln -s "${STEAMCMD_PATH}/linux64" "${STEAM_SDK64_PATH}"
[ ! -L "${STEAM_SDK64_PATH}/steamservice.so" ] && ln -s "${STEAM_SDK64_PATH}/steamclient.so" "${STEAM_SDK64_PATH}/steamservice.so"
[ ! -L "${STEAM_SDK32_PATH}" ] && ln -s "${STEAMCMD_PATH}/linux32" "${STEAM_SDK32_PATH}"
[ ! -L "${STEAM_SDK32_PATH}/steamservice.so" ] && ln -s "${STEAM_SDK32_PATH}/steamclient.so" "${STEAM_SDK32_PATH}/steamservice.so"

if [ "$USE_PROTON" -eq 1 ]; then
  if [ ! -e "${STEAMCMD_PATH}/compatibilitytools.d/GE-Proton${PROTON_VERSION}" ]; then
    echo "--> Installing proton"
    mkdir -p "$STEAMCMD_PATH/compatibilitytools.d/"

    curl -sqL "$PROTON_URL" | tar zxf - --checkpoint=.100 -C "${STEAMCMD_PATH}/compatibilitytools.d/"
    echo ""
  fi

  mkdir -p "$STEAM_COMPAT_DATA_PATH" && chmod -R 755 "$STEAM_COMPAT_DATA_PATH"
fi
