FROM python:3.12.5 as build

ENV PYTHONFAULTHANDLER=1 \
  PYTHONUNBUFFERED=1 \
  PYTHONHASHSEED=random \
  PIP_NO_CACHE_DIR=off \
  PIP_DISABLE_PIP_VERSION_CHECK=on \
  PIP_DEFAULT_TIMEOUT=100 \
  POETRY_NO_INTERACTION=1 \
  POETRY_VIRTUALENVS_CREATE=false \
  PATH="$PATH:/runtime/bin" \
  PYTHONPATH="$PYTHONPATH:/runtime/lib/python3.11/site-packages" \
  # Versions:
  POETRY_VERSION=1.2.2

RUN pip install "poetry==$POETRY_VERSION"

WORKDIR /app

COPY pyproject.toml poetry.lock ./

RUN poetry export --without-hashes --no-interaction --no-ansi -f requirements.txt -o requirements.txt && \
  pip install --prefix=/runtime --force-reinstall -r requirements.txt

COPY discord_bot/ ./discord_bot/

# prepend poetry and venv to path
ENV PATH="$POETRY_HOME/bin:$VENV_PATH/bin:$PATH"

FROM python:3.12.5-slim AS runtime-discord-bot

WORKDIR /app

COPY --from=build /runtime /usr/local
COPY --from=build /app/ /app/

CMD [ "python", "-m", "discord_bot.bot" ]

FROM python:3.12.5-slim AS runtime-job-runner

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

COPY --from=build /runtime /usr/local
COPY --from=build /app/ /app/

COPY scripts/ /app/scripts/
COPY terraform/terraform-entrypoint.sh /app/terraform/

COPY terraform/valheim/main.tf terraform/valheim/.terraform.lock.hcl terraform/valheim/cloud-init.tftpl /app/terraform/valheim/
COPY terraform/factorio/main.tf terraform/factorio/.terraform.lock.hcl terraform/factorio/cloud-init.tftpl /app/terraform/factorio/

ENV TF_DATA_DIR_BASE=/terraform/init

ENTRYPOINT [ "/app/terraform/terraform-entrypoint.sh" ]

CMD [ "rq", "worker", "-c", "discord_bot.sentry", "--with-scheduler" ]

FROM python:3.12.5-slim AS runtime-server-launch-watcher

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

WORKDIR /app

COPY --from=build /runtime /usr/local
COPY --from=build /app/ /app/

CMD [ "python", "-m", "discord_bot.server_launch_watcher" ]
