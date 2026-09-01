FROM python:3.14.7 AS build

COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /bin/uv

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

FROM python:3.14.7-slim AS runtime-discord-bot

ENV \
  # Use the virtual environment automatically
  VIRTUAL_ENV=/opt/.venv \
  # Place executables in the environment at the front of the path
  PATH="/opt/.venv/bin:$PATH"

WORKDIR /app

COPY --from=build /opt/.venv/ /opt/.venv/
COPY --from=build /app/ /app/

CMD [ "python", "-m", "discord_bot.bot" ]

FROM python:3.14.7-slim AS runtime-job-runner

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

FROM python:3.14.7-slim AS runtime-server-launch-watcher

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
