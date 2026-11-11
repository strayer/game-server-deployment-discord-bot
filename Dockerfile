FROM python:3.14.8@sha256:455fc8bf2552c51738d27fde570c22bb0146d22f2e16e32a9baff8d2da94daf6 AS build

COPY --from=ghcr.io/astral-sh/uv:0.13.3@sha256:bee0a2a458fd956c5df7b8b4c5fed2257b0af34866e3da7b51db0be3acb375d1 /uv /bin/uv

ENV PYTHONFAULTHANDLER=1 \
  PYTHONUNBUFFERED=1 \
  PYTHONHASHSEED=random \
  PIP_DISABLE_PIP_VERSION_CHECK=on \
  PIP_DEFAULT_TIMEOUT=100 \
  # Use the virtual environment automatically
  VIRTUAL_ENV=/opt/.venv \
  # Place executables in the environment at the front of the path
  PATH="/opt/.venv/bin:$PATH"

WORKDIR /opt

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-install-project

WORKDIR /app

COPY discord_bot/ ./discord_bot/

FROM python:3.14.8-slim@sha256:fbecd461fc72d21b2143c6eaba25143738079154a6d0ea3da3aec724f50eed4a AS runtime-discord-bot

ENV \
  # Use the virtual environment automatically
  VIRTUAL_ENV=/opt/.venv \
  # Place executables in the environment at the front of the path
  PATH="/opt/.venv/bin:$PATH"

WORKDIR /app

COPY --from=build /opt/.venv/ /opt/.venv/
COPY --from=build /app/ /app/

CMD [ "python", "-m", "discord_bot.bot" ]

FROM python:3.14.8-slim@sha256:fbecd461fc72d21b2143c6eaba25143738079154a6d0ea3da3aec724f50eed4a AS runtime-job-runner

ENV \
  # Use the virtual environment automatically
  VIRTUAL_ENV=/opt/.venv \
  # Place executables in the environment at the front of the path
  PATH="/opt/.venv/bin:$PATH"

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# openssh-client + rsync power the SSH stop / restic-backup teardown step
# (discord_bot/remote_ops.py).
RUN apt-get update && \
  apt-get install --no-install-recommends -y ca-certificates openssh-client rsync && \
  rm -rf /var/lib/apt/lists

WORKDIR /app

COPY --from=build /opt/.venv/ /opt/.venv/
COPY --from=build /app/ /app/

CMD [ "rq", "worker", "-c", "discord_bot.sentry", "--with-scheduler" ]

FROM python:3.14.8-slim@sha256:fbecd461fc72d21b2143c6eaba25143738079154a6d0ea3da3aec724f50eed4a AS runtime-server-launch-watcher

ENV \
  # Use the virtual environment automatically
  VIRTUAL_ENV=/opt/.venv \
  # Place executables in the environment at the front of the path
  PATH="/opt/.venv/bin:$PATH"

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

WORKDIR /app

COPY --from=build /opt/.venv/ /opt/.venv/
COPY --from=build /app/ /app/

CMD [ "python", "-m", "discord_bot.server_launch_watcher" ]
