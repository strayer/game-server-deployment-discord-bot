This document provides guidance for AI agents on how to interact with and modify this software project.

## Project Overview

This project is a Discord bot for managing game servers. It uses Python and Docker to automate the deployment and management of dedicated game servers for Valheim, Factorio, Enshrouded, Abiotic Factor, and Windrose on Hetzner Cloud. Servers are provisioned by calling the **Hetzner Cloud API directly** (the `hcloud` Python SDK) — there is no Terraform and no separate state database; the API itself is the source of truth, keyed by a fixed naming convention.

The core components are:

-   **Discord Bot:** A Python application using the `hikari` and `lightbulb` libraries to interact with the Discord API. It provides slash commands to start and stop game servers.
-   **Job Runner:** A Python application using `rq` (Redis Queue) to process background jobs, such as starting and stopping game servers.
-   **Provisioner:** `discord_bot/provisioner.py` — imperative provisioning against the Hetzner Cloud API (servers, firewalls, SSH keys, install volumes). Replaces the former per-game Terraform.
-   **Docker:** The entire application is containerized using Docker and Docker Compose for development and production environments.

## Core Technologies

-   **Python:** The primary language for the bot and job runner. Key libraries: `hikari`, `lightbulb`, `rq`, `loguru`, `sentry-sdk`, `hcloud` (Hetzner SDK), `jinja2` (cloud-init rendering).
-   **Docker / Docker Compose:** Containerization and orchestration of the services.
-   **Hetzner Cloud:** The cloud provider where the game servers are deployed; managed directly via the `hcloud` SDK.
-   **Redis:** Message broker for the `rq` job queue, and per-game locks / command cooldowns.
-   **GitHub Actions:** CI/CD — builds/pushes Docker images and lints Python.

> **No DNS.** Servers are reached by IP (used only for occasional SSH debug + the
> readiness webhook). There is no Cloudflare provider, A record, or rDNS PTR.

## Project Structure

-   `discord_bot/`: Python source for the Discord bot and job runner.
    -   `bot.py`: Discord bot entry point (slash commands).
    -   `jobs.py`: rq jobs for start/stop; worker-side start-guard + Discord error reporting.
    -   `games.py`: per-game config — `ServerSpec` (server type, location, firewall ports, optional install volume, container stop strategy) + naming-convention helpers.
    -   `provisioner.py`: Hetzner API deploy/destroy.
    -   `cloud_init/`: Jinja2 renderer (`__init__.py`) + per-game `*.tftpl` templates.
    -   `remote_ops.py`: SSH stop + restic backup + rsync (the teardown step), keyed off the API-discovered IP and the shared `/sshkey/sshkey` key.
    -   `server_launch_watcher.py`: runs ON the game VM; posts the "ready" webhook.
    -   `db.py`: Redis helpers (cooldowns).
-   `docker/`: Game/server Docker build context and helper scripts.
-   `.github/workflows/`: GitHub Actions workflows for CI/CD.

## Server Creation Workflow

1.  **Discord Slash Command** — a user runs e.g. `/start-enshrouded`; `discord_bot/bot.py` receives it.
2.  **Authorization and Cooldown** — checks `is_authorized_channel` and `cooldown`; on failure responds with an error and stops.
3.  **Job Enqueueing** — on success the bot responds ("…start trigger received…") and enqueues `start_enshrouded_server` from `discord_bot/jobs.py`. (The command path is intentionally unchanged from the Terraform era — no bot-side existence checks.)
4.  **Job Execution** — the `job-runner` picks up the job and runs it under the per-game Redis lock.
5.  **Start-guard** — the worker checks `client.servers.get_by_name("<game>-server")`. If it already exists, the deploy is refused (a safe no-op) and a warning is posted to Discord — this fixes the old race where a second `/start` could destroy a live server.
6.  **Provisioning (`provisioner.deploy`)** — ordered: validate the bot SSH key (adopt-or-recreate) and collect *all* project keys → resolve-or-create the install volume (volume games) → render cloud-init → delete-and-recreate the firewall → create the server (all project keys, firewall, inline volume) → wait for the create action and read the IPv4. Failures roll back best-effort and post a clear Discord message + Sentry event.
7.  **Server Configuration (cloud-init)** — the rendered `discord_bot/cloud_init/<game>.tftpl` runs on the new VM: installs Docker, restores the restic backup, starts the game container, and launches the watcher.
8.  **Final Notification** — the on-VM `server_launch_watcher` posts the "server is ready" webhook once the game logs the readiness marker. `deploy()` does **not** wait for readiness.

Teardown (`/stop` → `provisioner.destroy`) is ordered: SSH stop the container + restic backup **while the server is alive** → (volume games) ACPI shutdown, wait for "off", detach the volume → delete the server → delete the firewall. The shared bot SSH key and install volumes are never deleted.

## Development Workflow

### Prerequisites

-   Docker and Docker Compose
-   Python 3.11
-   `uv` for Python package management

### Getting Started

1.  Copy `discord-bot.env.example` to `discord-bot.env` and `job-runner.env.example` to `job-runner.env` and fill in the required environment variables (Hetzner token via `HCLOUD_TOKEN`/`TF_VAR_hcloud_token`, restic creds, per-game server config, Discord webhooks).
2.  Run `docker-compose up --build` to build and start the application.

### Making Changes

-   **Discord Bot / Provisioner:** Modify the Python files in `discord_bot/`.
-   **Per-game infra:** Edit the game's `ServerSpec` in `discord_bot/games.py`.
-   **cloud-init:** Edit `discord_bot/cloud_init/<game>.tftpl` (Terraform-style `${ name }` placeholders; values come from `TF_VAR_<name>` env, `ServerSpec.cloud_init_defaults`, or the Game's bot messages).
-   **Docker:** Modify the `Dockerfile` or files in `docker/`.

### Linting and Formatting

-   **Python:** `ruff check .` and `ruff format .`.

### Testing

-   `uv run pytest` (unit tests under `tests/`, including the cloud-init render-all-five check). Manual end-to-end testing against Hetzner is still required for full deploys.

## Architectural Patterns

-   **Microservices:** Separate Discord bot and job-runner services.
-   **Asynchronous Processing:** An `rq` job queue keeps the bot responsive while long deploys run in the background.
-   **API as state:** No state DB and no Terraform — every resource is named by convention (`<game>-server`, `<game>-firewall`, the shared `discord-bot` SSH key, `<game>-install` volumes), so the Hetzner API is queried directly for what is deployed. Ownership is by name: the bot only manages its own named resources and never deletes install volumes or unrelated SSH keys.

## How to Add a New Game

1.  Add a new `Game` (with its `ServerSpec`: location, firewall ports, optional install volume, stop strategy) to `discord_bot/games.py`.
2.  Add `discord_bot/cloud_init/<game>.tftpl` and the matching `TF_VAR_*` entries to `job-runner.env.example`.
3.  Add slash commands in `discord_bot/bot.py` and `start_/stop_` job functions in `discord_bot/jobs.py`.
4.  Add the game's readiness regex to `discord_bot/server_launch_watcher.py`.
5.  Add the game server image build to `docker/` + `Dockerfile.steamcmd` and `.github/workflows/build-image.yml`.
