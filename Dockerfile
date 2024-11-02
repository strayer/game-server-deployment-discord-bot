# ==========================================
# Stage: Build
# ==========================================
FROM python:3.11.1 AS build

ENV UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:0.4.28 /uv /bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
  --mount=type=bind,source=uv.lock,target=uv.lock \
  --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
  uv sync --frozen --no-install-project --no-editable

COPY discord_bot/ ./discord_bot/

RUN --mount=type=cache,target=/root/.cache/uv \
  uv sync --frozen --no-editable

# ==========================================
# Stage: Runtime Discord Bot
# ==========================================
FROM python:3.11.1-slim AS runtime-discord-bot

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH"

COPY --from=build --chown=app:app /app/.venv /app/.venv

CMD [ "python", "-m", "discord_bot.bot" ]

# ==========================================
# Stage: Runtime Job Runner
# ==========================================
FROM python:3.11.1-slim AS runtime-job-runner

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install terraform
ARG TERRAFORM_VERSION=1.3.6
RUN export PACKAGES="curl gnupg libdigest-sha-perl unzip" && \
  export TERRAFORM_ARCH="$(arch | sed s/aarch64/arm64/ | sed s/x86_64/amd64/)" && \
  apt-get update && apt-get install --no-install-recommends -y $PACKAGES  && \
  mkdir /terraformdl && \
  cd /terraformdl && \
  curl -L https://keybase.io/hashicorp/pgp_keys.asc | gpg --import - && \
  curl -LO https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_${TERRAFORM_ARCH}.zip && \
  curl -LO https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_SHA256SUMS.sig && \
  curl -LO https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_SHA256SUMS && \
  gpg --verify terraform_${TERRAFORM_VERSION}_SHA256SUMS.sig terraform_${TERRAFORM_VERSION}_SHA256SUMS && \
  shasum --algorithm 256 --ignore-missing --check terraform_${TERRAFORM_VERSION}_SHA256SUMS && \
  unzip terraform_${TERRAFORM_VERSION}_linux_${TERRAFORM_ARCH}.zip && \
  mv terraform /usr/local/bin && \
  chmod +x /usr/local/bin/terraform && \
  apt-get purge -y --auto-remove $PACKAGES && \
  rm -rf /var/lib/apt/lists

RUN apt-get update && \
  apt-get install --no-install-recommends -y ca-certificates curl openssh-client rsync bzip2 jq && \
  rm -rf /var/lib/apt/lists

WORKDIR /app

COPY --from=build --chown=app:app /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH"

COPY scripts/ /app/scripts/
COPY terraform/terraform-entrypoint.sh /app/terraform/

COPY terraform/valheim/main.tf terraform/valheim/.terraform.lock.hcl terraform/valheim/cloud-init.tftpl /app/terraform/valheim/
COPY terraform/factorio/main.tf terraform/factorio/.terraform.lock.hcl terraform/factorio/cloud-init.tftpl /app/terraform/factorio/

ENV TF_DATA_DIR_BASE=/terraform/init

ENTRYPOINT [ "/app/terraform/terraform-entrypoint.sh" ]

CMD [ "rq", "worker", "-c", "discord_bot.sentry", "--with-scheduler" ]

# ==========================================
# Stage: Runtime Server Launch Watcher
# ==========================================
FROM python:3.11.1-slim AS runtime-server-launch-watcher

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

WORKDIR /app

COPY --from=build --chown=app:app /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH"

CMD [ "python", "-m", "discord_bot.server_launch_watcher" ]
