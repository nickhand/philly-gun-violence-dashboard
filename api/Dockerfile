FROM python:3.13-slim-trixie
COPY --from=ghcr.io/astral-sh/uv:0.9.18 /uv /uvx /bin/

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

# Install supercronic for running cron jobs in production.
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
ARG SUPERCRONIC_URL=https://github.com/aptible/supercronic/releases/latest/download/supercronic-linux-amd64
RUN curl -fsSL "$SUPERCRONIC_URL" -o /usr/local/bin/supercronic \
    && chmod +x /usr/local/bin/supercronic

# Copy lockfiles and minimal sources first to maximize cache reuse.
COPY dashboard-utils/pyproject.toml dashboard-utils/uv.lock dashboard-utils/README.md /app/dashboard-utils/
COPY dashboard-utils/src/ /app/dashboard-utils/src/
COPY api/pyproject.toml api/uv.lock /app/api/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project /app/dashboard-utils --locked --no-install-project && \
    uv sync --project /app/api --locked --no-install-project

# Copy source code only after dependencies are installed.
COPY dashboard-utils/ /app/dashboard-utils/
COPY api/ /app/api/

# Install the source code into the environment.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project /app/dashboard-utils --locked && \
    uv sync --project /app/api --locked 

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app/api
EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
