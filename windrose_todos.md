# Windrose Dedicated Server — Setup TODOs

## Background / Context for picking this up

### The game

**Windrose** is a co-op pirate/sailing game. We want to host its **dedicated server** the
same way we host Valheim / Factorio / Enshrouded / Abiotic Factor: one container per game,
provisioned on a Hetzner VM via Terraform + cloud-init, started/stopped from the Discord bot.

Key facts about the Windrose dedicated server:

- **Windows-only.** There is no native Linux server build. We must run the Windows
  `WindroseServer-Win64-Shipping.exe` under **Proton** (same approach as Enshrouded /
  Abiotic Factor).
- **SteamCMD**, anonymous login, **app id `4129620`**. Install with
  `+@sSteamCmdForcePlatformType windows`.
- Binary path: `<install>/R5/Binaries/Win64/WindroseServer-Win64-Shipping.exe`.
- **Configured only via JSON files — no command-line flags** for name/password/etc.
  This is the big difference vs Abiotic Factor (CLI args). Closer to our Enshrouded
  (template + `jq`) pattern.
  - `R5/ServerDescription.json` — common server settings (name, password, region,
    direct-connection settings, invite code, world to load).
  - `R5/Saved/SaveProfiles/Default/RocksDB_v2/<gameversion>/Worlds/<worldid>/WorldDescription.json`
    — per-world settings (preset, difficulty multipliers, etc.).
- **Config files only exist after the first launch.** Official guidance: start once → stop →
  edit JSON. We handle this with **Option A** (see below).
- Saves use **RocksDB** (`R5/Saved/SaveProfiles/Default/RocksDB_v2`). Unclean shutdown can
  corrupt saves (there's an `AutoLoadLatestBackupIfHasBroken` flag). **Graceful shutdown
  matters.**
- **Networking: we use direct IP connection** (`UseDirectConnection=true`,
  `DirectConnectionServerPort=7777`, TCP **and** UDP). Players connect by IP:port like all
  our other servers. The invite-code connection mechanism is therefore **not used** — ignore
  `InviteCode` in the JSON.

### Test environment (for agents)

- **Remote test machine:** `ssh game-server-deployment-test@orb` (OrbStack, amd64).
  Debian 13 (Trixie), kernel 7.0 (orbstack), 10 cores, 15 GB RAM.
- **Docker:** `29.5.3` — this is **≥ 29.4.2**, so the seccomp / CVE-2026-31431 Wine/Proton
  socket issue *may* surface here (`wine: socket: Function not implemented`). Good place to
  find out. Local user is `strayer`; use `sudo` for docker commands.
- **`/dev/ntsync` is available** on this host — usable for the step-4 perf experiment.
- This project is mounted at `/mnt/mac/Users/strayer/dev/game-server-deployment-discord-bot`
  on the test machine (edit files on the Mac, build/run on the remote).

### Docs & references

- **Official dedicated server guide:** https://playwindrose.com/dedicated-server-guide/
  (covers ServerDescription.json / WorldDescription.json fields, SteamCMD install, save
  paths, direct-IP connection scenarios, FAQ). Also bundled in-game as `DedicatedServer.md`.
- **Reference dockerizations we studied:**
  - https://github.com/mornedhels/windrose-server — Proton + Wine variants, supervisor/cron
    orchestration. We are **not** reusing their update/backup/supervisor machinery — we only
    borrow their Windrose-specific config handling.
  - https://github.com/indifferentbroccoli/windrose-server-docker — **Wine + xvfb**,
    DepotDownloader, plain-bash. Best reference for **graceful shutdown** (`wineserver -k`)
    and the **log file path**. Ships an optional mod stack (UE4SS / Windrose+ / repak /
    PowerShell / RCON dashboard) that is **irrelevant to us — ignore it**.

### Key facts confirmed/learned from the reference implementations

- **First-boot config generation works** (both repos do it): start server → poll for
  `ServerDescription.json` → kill → `wineserver -k`. Timeout seen: 120s (broccoli) / 300s
  (mornedhels). Then `jq`-patch every boot. Validates our Option A.
- **Log file:** the server writes to `R5/Saved/Logs/R5.log` and accepts a `-log` (and
  `-STDOUT`) flag. This is where the "server ready" line lives (relevant to step 2).
- **Graceful shutdown = `wineserver -k`** (synchronous; returns only after wineserver exits;
  triggers Wine's proper shutdown so RocksDB flushes). Must run as the prefix-owning user.
  Proton equivalent: run the GE-Proton-bundled `files/bin/wineserver -k` against the
  compatdata prefix (mornedhels does this). Fallback: `wineserver -k9` + `pkill -9 -u <user>`.
  **This is the most promising fix for our long-standing clean-stop/save problem (step 3).**
- **Possible virtual-display requirement (UNKNOWN/RISK):** broccoli wraps wine in `xvfb-run`,
  implying the binary may need an X display even headless. The Proton-based repos (mornedhels)
  and our own Proton games do NOT use xvfb. De-risk early in step 1: if Windrose fails to
  start under Proton with no useful output, try a virtual display (`xvfb`).
- **CPU instruction sets (RISK):** broccoli warns that virtualized CPUs missing instruction
  sets cause Wine/the binary to crash or fail silently. Candidate cause if we hit silent
  startup failures on Hetzner.

### Our approach / decisions so far

- **Reuse our existing Proton Dockerfile pattern** (`Dockerfile.steamcmd`, `abiotic-factor` /
  `enshrouded` stages). Add a `windrose` stage. We do **NOT** need mornedhels' update, backup,
  supervisor, or cron logic — our stack already solves updates (fresh `steamcmd app_update`
  every container start) and backups (separate restic mechanism).
- **Config handling = Option A (mornedhels-style, persistent world):**
  - Let the server **generate** `ServerDescription.json` / `WorldDescription.json` on first
    boot into the persistent `/gamedata` volume.
  - On **every** start, re-stamp the fields we control via `jq` over the existing files
    (ServerName, Password + IsPasswordProtected, UseDirectConnection,
    DirectConnectionServerPort, world preset, etc.).
  - **Preserve** identity/world fields across restarts: `PersistentServerId`, `WorldIslandId`,
    and the RocksDB world data all just ride along in the volume.
  - Relies on the game-data volume persisting across restarts (consistent with the recent
    "persist game installation on Hetzner volume" work for Abiotic Factor).
- **Start script** = Enshrouded-style (Proton `proton run`, template/`jq` config, SIGTERM→SIGINT
  trap) rather than Abiotic Factor-style (bare `exec`, CLI args). Symlink `R5/Saved` →
  `$GAMEDATA_PATH` like the other games.
- **Proton hygiene to copy from mornedhels:** add `libfreetype6:i386` (our base only has the
  64-bit one), use a recent GE-Proton (they use `10-34`; AF uses `10-26`). We already have
  steamcmd download-retry; the `CPU_MHZ` workaround is optional.

### Notes / decisions explicitly deferred

- **`/dev/ntsync`** — in-kernel Windows NT sync primitives (kernel ≥ 6.14), a Proton **CPU
  performance** optimization. Purely optional; Proton falls back to fsync/esync without it.
  Deferred to step 4. Requires checking the Hetzner image kernel version and device passthrough.
- **Docker ≥ 29.4.2 seccomp / CVE-2026-31431** breaks Wine/Proton (`wine: socket: Function
  not implemented`). We'll **ignore and test first** — our other Proton containers run, so the
  host is likely unaffected. Watch for that error at launch; fix is a seccomp profile tweak.

---

## Step 1 — MVP Docker image working

Goal: a Windrose container that installs the game, generates + stamps config, and launches the
real server instance correctly.

> **Progress (2026-06-14): MVP runtime VALIDATED end-to-end on real x86_64.** ✅
>
> Files changed:
> - `Dockerfile.steamcmd`: added `windrose` stage (appid 4129620, USE_PROTON=1, GE-Proton 10-34,
>   STOPSIGNAL SIGINT, `R5/Saved`→`/gamedata` symlink).
> - `docker/windrose/start.sh`: Option-A first-boot config gen → poll for ServerDescription.json
>   → `wineserver -k` stop → jq-stamp controlled fields → relaunch. Graceful-shutdown trap via
>   GE-Proton's `files/bin/wineserver -k`. Logging via **`tail -F` of R5.log** (see below).
> - `docker/install-or-update-game.sh`: retry loop now retries on **any** non-zero steamcmd exit
>   up to `STEAMCMD_MAX_ATTEMPTS` (default 8) with a 5s backoff — previously it only retried on
>   the "Missing configuration" string and fatally bailed when a retry returned bare exit 8.
>   (Benefits all games.)
>
> Validated on the native amd64 VM (`ssh windrose-vm`, GenuineIntel, Docker 29.5.3):
> - ✅ Image builds; steamcmd downloads the ~3 GB game (Windows platform).
> - ✅ **Proton launches the server — NO seccomp/socket issue on Docker 29.5.3** (`fsync: up and
>   running`, Steam SDK loaded, engine inits). The CVE-2026-31431 concern does NOT bite here.
> - ✅ The GE-Proton **`Xalia ... Video driver not supported` exception is NON-FATAL** — server
>   boots fully. **No xvfb needed** (unlike the Wine-based broccoli image).
> - ✅ First-boot config generation works; `ServerDescription.json` produced and jq-stamped
>   correctly (ServerName/Password/IsPasswordProtected/MaxPlayerCount/UseDirectConnection=true/
>   DirectConnectionServerPort=7777 all applied; PersistentServerId + WorldIslandId preserved).
> - ✅ Server **listens on direct connection** `0.0.0.0:7777` (`IpNetDriver listening on port
>   7777`, `Coop NetServer ... <DirectConnection>`); world `GenlandiaMulty` loads.
> - ✅ **Graceful shutdown (step 3!) works:** `docker stop` → trap → `wineserver -k` (synchronous)
>   → R5.log shows `Save backup ... finished successfully`. Restart loads clean (zero
>   broken/corrupt/AutoLoadLatestBackup recovery).
> - ✅ **Option-A persistence:** 2nd boot reuses existing ServerDescription.json + world (no
>   "First boot" path), just re-stamps env + starts.
> - ⚠️ **`-STDOUT` does NOT reach container stdout** (engine writes only to R5.log; only Proton's
>   Xalia error showed on stdout). **Switched to `tail -F R5.log` → stdout** (kept alive until the
>   server exits so shutdown/save lines are captured). [Final rebuild/verify of this in progress.]
>
> Test-box notes (for later agents):
> - The FIRST box (`game-server-deployment-test@orb`) is **x86_64 emulated on Apple Silicon**
>   (`VirtualApple`); steamcmd's 32-bit client segfaults under `qemu-i386` there. **Unusable for
>   Proton/Steam.** Use `ssh windrose-vm` (native Intel) instead.
> - `windrose-vm`: project synced to `/root/game-server-deployment-discord-bot` (needed
>   `apt-get install rsync` first); game data persisted at `/root/windrose-data/{game,saves}`
>   (chown 1000:1000 — the container runs as uid 1000 and the bind mount must be writable by it).
> - SSH goes through Little Snitch (allow once) + a multiplexed master at `/tmp/wr-mux` to avoid
>   per-connection prompts.
> - GE-Proton is re-downloaded into the container fs on every start (~30s) since it installs to
>   `/opt/steamcmd` (not persisted). Acceptable; optimize later if desired.

- [ ] Add `windrose` stage to `Dockerfile.steamcmd` (STEAMAPPID=4129620, USE_PROTON=1,
      PROTON_VERSION, STEAM_COMPAT_DATA_PATH, GAME_PATH=/opt/windrose, STOPSIGNAL SIGINT).
- [ ] Add `libfreetype6:i386` to the base steamcmd stage if Windrose needs it.
- [ ] Symlink `R5/Saved` → `$GAMEDATA_PATH` (image + runtime, like Abiotic Factor).
- [ ] Write `docker/windrose/start.sh`:
  - [ ] First-boot config generation: if `ServerDescription.json` missing, launch server,
        wait for the file to appear, stop cleanly (Option A).
  - [ ] `jq`-stamp controlled fields on every start: ServerName, Password +
        IsPasswordProtected, UseDirectConnection=true, DirectConnectionServerPort=7777,
        (world preset if desired). Preserve PersistentServerId / WorldIslandId.
  - [ ] Launch via `proton run …/WindroseServer-Win64-Shipping.exe`.
  - [ ] Redirect game logs to stdout.
- [ ] Verify steamcmd download works with `+@sSteamCmdForcePlatformType windows`.
      (Fallback if steamcmd misbehaves: DepotDownloader `-app 4129620 -validate`, as broccoli uses.)
- [ ] Confirm the server actually boots under Proton and stays up.
- [ ] **De-risk virtual display:** if the server fails to start with no useful output, test
      running under `xvfb-run` (broccoli wraps wine in xvfb — our Proton games don't need it,
      but Windrose might).
- [ ] If silent startup failure on Hetzner: suspect missing CPU instruction sets (broccoli's
      Proxmox warning) — check the VM CPU type/flags.
- [ ] **Log output to stdout (decision: native engine stdout — no symlink, no `tail`).**
  - Approach: launch the server with `-log -STDOUT -UTF8Output` so the engine writes the log
    directly to stdout. Cleanest option — no symlink trick, no `tail` process, no missed early
    lines, immune to UE's startup log rotation.
  - **Must verify early in step 1** that this actually propagates through `proton run` to the
    container's stdout — this is the one approach not yet proven for Windrose. (broccoli used
    `-STDOUT` only for first-run generation and fell back to `tail` for the real run, hinting it
    may not have sufficed under *Wine*; Proton behaviour is untested.)
  - **Fallback if stdout is empty/incomplete:** `tail -F "$LOG_FILE"` on
    `R5/Saved/Logs/R5.log` to stdout in the background; kill `tail` only after the server fully
    exits so shutdown/final-save lines are captured. (`tail -F` re-opens on UE log rotation.)
  - Avoid the house-style symlink (`ln -sf /proc/1/fd/1 .../R5.log`): UE rotates its log on
    startup, moving the symlink aside and breaking capture on every boot after the first.
  - **Log rotation / "no stale output" (verified on windrose-vm):** the engine renames the
    previous log to `R5-backup-<timestamp>.log` and opens a fresh `R5.log` each launch, so
    `R5.log` only ever holds the current boot (the ready marker appears exactly once → safe to
    grep on disk). We use **`tail -n 0 -F`** so stdout never replays the previous log's tail
    during the rotation race. No manual log-clearing needed.
  - Minor: `R5-backup-*.log` accumulate in the save volume over restarts (~150 KB each) —
    optional future cleanup. `docker logs` also accumulates across `docker start` of the SAME
    container (non-issue for fresh-container-per-start; watcher should tail live / use `--since`).

## Step 2 — Discord notification (server ready)

- [x] **Identified the readiness marker (from live log on windrose-vm, 2026-06-14).** Logs go to
      `R5/Saved/Logs/R5.log` and now also to container stdout via `tail -F`.
  - **Primary "ready" signal → match: `Host server is ready for owner to connect`**
    (log cat `R5LogCoopProxy`, fn `SetIsReadyForHostOwnerConnect`). Singular, purpose-built,
    fires after the save loads and listeners are up.
  - **Save-loaded signal** (the "world/save fully loaded" gate, if wanted): `Successfully loaded
    DB` together with `/Worlds/<WorldId>` (cat `R5LogBLDalAQ`).
  - **Gameplay-world-loaded signal:** the SECOND `Load map complete` (path is the world map,
    e.g. `.../GenlandiaMulty`), NOT the first one (`/Game/Maps/Lobby/R5ServerLobby`).
  - ⚠️ **Do NOT use `IpNetDriver listening on port 7777` as readiness** — it fires for the LOBBY
    net driver before the gameplay world loads, and appears TWICE. Same trap for the first
    `Load map complete` (it's the lobby). Observed order:
    `loaded DB /Worlds/...` → `Island doc is ready` → listening(lobby) → lobby map complete →
    **`Host server is ready for owner to connect`** → world BeginPlay → `SetActorIsReady` →
    world map complete.
  - Optional belt-and-suspenders: require `Successfully loaded DB .../Worlds/` THEN
    `Host server is ready for owner to connect`.
- [x] **Wired into `discord_bot/server_launch_watcher.py`** (2026-06-14): added
      `GAME_NAME == "windrose"` → `CONTAINER_NAME = "windrose-server"`,
      `REGEX_PATTERN = r"Host server is ready for owner to connect"`; added `windrose` to the
      IPv4-only set for the address string (direct-connect IP, no IPv6).
- [x] **Tested end-to-end on windrose-vm:** watcher streamed the container logs, ignored the
      `listening on port 7777` lines, matched the ready marker, and POSTed
      `Windrose server is ready! [<reverse-dns> (<ipv4>)]` to a mock webhook (HTTP 204 OK).
- [ ] Remaining (overlaps Step 5): deploy the watcher container with `GAME_NAME=windrose` in
      `terraform/windrose/cloud-init.tftpl`, name the game container `windrose-server`, and set
      `SERVER_READY_MESSAGE` from the bot's `bot_message_server_ready` (needs a `WINDROSE` entry
      in `discord_bot/games.py`). The notification announces IP:port (direct connection).

## Step 3 — Clean server stop + final world save

> Note: graceful stop + final save has historically never worked well from Discord for us.
> RocksDB makes this important (risk of corrupt saves). May need to compare against other
> Windrose container implementations.

- [ ] **Preferred approach (from broccoli):** trap SIGTERM and call `wineserver -k` as the
      prefix-owning user. It's synchronous (returns only after wineserver exits) and triggers
      Wine's proper shutdown so RocksDB flushes. Proton equivalent: run the GE-Proton-bundled
      `.../files/bin/wineserver -k` against `$STEAM_COMPAT_DATA_PATH/pfx`. Fallback:
      `wineserver -k9` then `pkill -9 -u <user>`.
- [ ] Confirm the world is fully flushed to RocksDB before container exit (no
      `AutoLoadLatestBackupIfHasBroken` recovery on next boot = good sign).
- [ ] Verify `/stop-windrose` from Discord produces a clean save.
- [ ] Reference shutdown impls: broccoli `scripts/functions.sh:shutdown_server()` +
      `scripts/init.sh:term_handler()`; mornedhels `scripts/proton/windrose-server`.

## Step 4 — Optimizations

- [ ] Evaluate `/dev/ntsync` passthrough (check Hetzner kernel ≥ 6.14, add device, measure CPU).
- [ ] Revisit Docker seccomp / CVE-2026-31431 only if Wine/Proton socket errors appear.
- [ ] Tune Proton version / any missing runtime libs.

## Step 5 — Terraform / env / bot wiring (mirror Abiotic Factor) — DONE 2026-06-14

- [x] **Bot code:** `discord_bot/games.py` (`WINDROSE`), `discord_bot/jobs.py`
      (`start/stop_windrose_server`), `discord_bot/bot.py` (`/start-windrose`, `/stop-windrose`).
      Tests added; `pytest` 36 passed.
- [x] **`scripts/teardown.sh`:** windrose webhook branch + `docker stop -t 90 windrose-server`
      (long timeout so RocksDB flushes during `wineserver -k`). (`scripts/start.sh` is generic.)
- [x] **`terraform/windrose/`** (`main.tf`, `cloud-init.tftpl`, `.terraform.lock.hcl`).
      `terraform fmt` + `validate` pass. Firewall opens **7777 TCP + UDP** (+ SSH, ICMP); IPv4-only
      A record (no AAAA). Game container env: `SERVER_NAME`, `SERVER_PASSWORD`, `MAX_PLAYERS`,
      `USE_DIRECT_CONNECTION=true`, `SERVER_PORT=7777`. Persists `/mnt/windrose-install/{steamcmd,
      steam,windrose}` + `/gamedata` on the Hetzner volume (proton/steamcmd persist across boots).
- [x] **`Dockerfile`** (job-runner stage) COPYs `terraform/windrose/*`.
- [x] **`.github/workflows/build-image.yml`:** added `windrose` image (target `windrose`,
      `Dockerfile.steamcmd`). docker-compose.yml needs NO change (it doesn't list per-game images).
- [x] **`job-runner.env.example`:** added `TF_VAR_restic_windrose_*` + `TF_VAR_windrose_*`.

### Data layout / sizes (measured on windrose-vm 2026-06-14)
- **Game install is ~2.9 GB** (R5 = 2.8 GB), NOT 35 GB. The docs' 35 GB is total-disk-with-client
  headroom. The install volume holds steamcmd + GE-Proton + game + ~2× headroom during updates →
  **~10–15 GB is plenty** for `windrose-install`.
- **Install vs backup are cleanly separated:** game files live on the install volume
  (`/opt/windrose`, incl. `R5/Binaries`, `R5/Content`, DLLs); `R5/Saved` is a symlink →
  `/gamedata` (ephemeral, restic-backed). No game files leak into `/gamedata`; saves don't bloat
  the install volume.
- **`/gamedata` contents:** `SaveProfiles/` (the world RocksDB — KEEP), `Logs/` (R5.log +
  accumulating `R5-backup-*.log` — EXCLUDE), `Config/CrashReportClient/` (crash junk — EXCLUDE).
  ✅ Fixed: added a `windrose` branch to `docker/backup/backup.sh` excluding `Logs` +
  `Config/CrashReportClient`.
- ⚠️ **GAP — `ServerDescription.json` is on the install volume (`/opt/windrose/R5/`), NOT in
  `/gamedata`, so it is NOT in the restic backup.** It holds `WorldIslandId`, which must match the
  world folder in `SaveProfiles/`. Normal start/stop is fine (install volume persists). But if the
  install volume is ever lost/recreated and saves are restored from restic to a fresh `/gamedata`,
  `start.sh` regenerates a NEW `ServerDescription.json` with a NEW `WorldIslandId` → the restored
  world is orphaned (server creates an empty new world). mornedhels deliberately bundles
  ServerDescription.json into its backup for this reason. **Recommended fix (not yet done):** have
  `start.sh` mirror `ServerDescription.json` into `/gamedata` after patching, and restore it back
  to `R5/` on boot if missing — so the WorldIslandId rides with the saves in the backup. (Use a
  copy, not a symlink — the server may rewrite the file and break a symlink, like the log rotation.)
  ✅ **DONE & validated (2026-06-14).** `start.sh` now: (1) before the first-boot check, if
  `R5/ServerDescription.json` is missing but `${GAMEDATA_PATH}/ServerDescription.json` exists,
  copies it back (restore); (2) after the jq patch, mirrors `R5/ServerDescription.json` →
  `${GAMEDATA_PATH}/ServerDescription.json` so backups capture it. `backup.sh` keeps it (only
  `Logs` + `Config/CrashReportClient` are excluded). Copy, not symlink, because our `mv` patch and
  the game's atomic rewrites would clobber a symlink at that path. WorldDescription.json already
  lives under `SaveProfiles/.../Worlds/<id>/` → already backed up. Tested all 3 paths on
  windrose-vm: normal restart (skip gen, mirror matches), restore (restores config → skips gen →
  loads same world CDF419), fresh boot (still generates a new world + writes mirror — generation
  NOT broken).

### Deployment prerequisites (manual, before first `/start-windrose`)
- [ ] **Create the Hetzner volume named `windrose-install`** (the TF uses `data.hcloud_volume`,
      i.e. it must already exist — same as abiotic-factor's `abiotic-factor-install`).
      **~10–15 GB** is enough (game is only ~3 GB).
- [ ] **Create the restic repo** for windrose saves (`restic init`) and set the
      `TF_VAR_restic_windrose_*` values in the real `job-runner.env`.
- [ ] Set the remaining `TF_VAR_windrose_*` (subdomain, server name, password, discord webhook).
- [ ] Build/push the `windrose` image (CI does this on merge) so cloud-init can pull
      `ghcr.io/strayer/.../windrose:latest`.

### Not yet validated end-to-end
- [ ] A real Hetzner deploy via `/start-windrose` (TF apply → cloud-init → server ready webhook)
      and `/stop-windrose` (graceful save → backup → destroy). Individual pieces are validated on
      windrose-vm; the full terraform/cloud-init path on Hetzner is untested.
