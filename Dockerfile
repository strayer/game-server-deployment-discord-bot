FROM python:3.15.2@sha256:e4bc83a3314d078d651f06c8440e9a03ba892ee2f6577437f174abd8731fb343 AS build

COPY --from=ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 /uv /bin/uv

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

FROM python:3.15.2-slim@sha256:08a4c22c92b79ec821a7ad49768480039ee5b7accac3955228e75366e30abc8e AS runtime-discord-bot

ENV \
  # Use the virtual environment automatically
  VIRTUAL_ENV=/opt/.venv \
  # Place executables in the environment at the front of the path
  PATH="/opt/.venv/bin:$PATH"

WORKDIR /app

COPY --from=build /opt/.venv/ /opt/.venv/
COPY --from=build /app/ /app/

CMD [ "python", "-m", "discord_bot.bot" ]

FROM python:3.15.2-slim@sha256:08a4c22c92b79ec821a7ad49768480039ee5b7accac3955228e75366e30abc8e AS runtime-job-runner

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

FROM python:3.15.2-slim@sha256:08a4c22c92b79ec821a7ad49768480039ee5b7accac3955228e75366e30abc8e AS runtime-server-launch-watcher

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
