FROM python:3.14-slim-trixie@sha256:ce40764625a4ff50df3548277632e7f96c4e77fe75fa848aae9885476e7df5a4
COPY --from=ghcr.io/astral-sh/uv:0.12.0@sha256:606e70c71c852d03f611b1e56a195d08648507018a7057fab82c4974c4eae105 /uv /uvx /bin/

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy

# Omit development dependencies
ENV UV_NO_DEV=1

# Ensure installed tools can be executed out of the box
ENV UV_TOOL_BIN_DIR=/usr/local/bin

# Use a shared virtual environment for both projects.
ENV UV_PROJECT_ENVIRONMENT=/app/.venv

# Install a pinned and verified Supercronic binary for the external scheduler.
ARG SUPERCRONIC_URL=https://github.com/aptible/supercronic/releases/download/v0.2.49/supercronic-linux-amd64
ARG SUPERCRONIC_SHA256SUM=a53ae236602c7338aba3fbaff40bda6300eae3b9fedb8261eb06cfe3724430c1
RUN python -c "import sys; from hashlib import sha256; from pathlib import Path; from urllib.request import urlopen; data = urlopen('$SUPERCRONIC_URL', timeout=60).read(); actual = sha256(data).hexdigest(); expected = '$SUPERCRONIC_SHA256SUM'; actual == expected or sys.exit(f'Supercronic checksum mismatch: {actual}'); Path('/usr/local/bin/supercronic').write_bytes(data)" \
    && chmod +x /usr/local/bin/supercronic

# Copy lockfiles and minimal sources first to maximize cache reuse.
COPY packages/dashboard-utils/pyproject.toml packages/dashboard-utils/uv.lock /app/dashboard-utils/
COPY packages/dashboard-utils/src/ /app/dashboard-utils/src/
COPY packages/api/pyproject.toml packages/api/uv.lock /app/api/
RUN touch /app/dashboard-utils/README.md /app/api/README.md

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project /app/dashboard-utils --locked --no-install-project && \
    uv sync --project /app/api --locked --no-install-project

# Copy only runtime sources after dependencies are installed. Tests, local
# recipes, and documentation must not perturb the production image identity.
COPY packages/dashboard-utils/src/ /app/dashboard-utils/src/
COPY packages/api/app/ /app/api/app/
COPY packages/api/scripts/ /app/api/scripts/
COPY packages/api/crontab /app/api/crontab

# Install the source code into the environment.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project /app/dashboard-utils --locked && \
    uv sync --project /app/api --locked

# Runtime writes belong on Fly's temporary filesystem. Keep application code,
# the shared virtual environment, and scheduler configuration image-owned so a
# compromised non-root process cannot rewrite the executable deployment.
ENV HOME=/tmp
ENV XDG_CACHE_HOME=/tmp/.cache
ENV XDG_CONFIG_HOME=/tmp/.config
ENV TMPDIR=/tmp
ENV PYTHONDONTWRITEBYTECODE=1
RUN groupadd --system app \
    && useradd --system --gid app --home-dir /tmp --no-create-home \
        --shell /usr/sbin/nologin app

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app/api
USER app
EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
