FROM python:3.13-slim-trixie
COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /uvx /bin/

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

# Install a verified Supercronic release for production cron jobs. Do not use
# the mutable releases/latest URL in a reproducible release image.
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
ARG SUPERCRONIC_URL=https://github.com/aptible/supercronic/releases/download/v0.2.49/supercronic-linux-amd64
ARG SUPERCRONIC_SHA1SUM=e63c11a9726b775a6a11801e81af4f3fb926aa68
RUN curl -fsSL "$SUPERCRONIC_URL" -o /usr/local/bin/supercronic \
    && echo "$SUPERCRONIC_SHA1SUM  /usr/local/bin/supercronic" | sha1sum -c - \
    && chmod +x /usr/local/bin/supercronic

# Copy lockfiles and minimal sources first to maximize cache reuse.
COPY packages/dashboard-utils/pyproject.toml packages/dashboard-utils/uv.lock packages/dashboard-utils/README.md /app/dashboard-utils/
COPY packages/dashboard-utils/src/ /app/dashboard-utils/src/
COPY packages/api/pyproject.toml packages/api/uv.lock /app/api/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project /app/dashboard-utils --locked --no-install-project && \
    uv sync --project /app/api --locked --no-install-project

# Copy source code only after dependencies are installed.
COPY packages/dashboard-utils/ /app/dashboard-utils/
COPY packages/api/ /app/api/

# Install the source code into the environment.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project /app/dashboard-utils --locked && \
    uv sync --project /app/api --locked 

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app/api
EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
