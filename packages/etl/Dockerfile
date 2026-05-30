FROM python:3.13-slim-trixie
COPY --from=ghcr.io/astral-sh/uv:0.9.18 /uv /uvx /bin/

# Install the project into `/app`
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

# Copy lockfiles and minimal sources first to maximize cache reuse.
COPY packages/aws-batch-scraper/pyproject.toml packages/aws-batch-scraper/uv.lock packages/aws-batch-scraper/README.md /app/aws-batch-scraper/
COPY packages/aws-batch-scraper/src/ /app/aws-batch-scraper/src/
COPY packages/dashboard-utils/pyproject.toml packages/dashboard-utils/uv.lock packages/dashboard-utils/README.md /app/dashboard-utils/
COPY packages/dashboard-utils/src/ /app/dashboard-utils/src/
COPY packages/etl/pyproject.toml packages/etl/uv.lock packages/etl/README.md /app/etl/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project /app/aws-batch-scraper --locked --no-install-project && \
    uv sync --project /app/dashboard-utils --locked --no-install-project && \
    uv sync --project /app/etl --locked --no-install-project

# Copy source code only after dependencies are installed.
COPY packages/aws-batch-scraper/ /app/aws-batch-scraper/
COPY packages/dashboard-utils/ /app/dashboard-utils/
COPY packages/etl/ /app/etl/

# Install the source code into the environment.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project /app/aws-batch-scraper --locked && \
    uv sync --project /app/dashboard-utils --locked && \
    uv sync --project /app/etl --locked

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

# Install Playwright browser binaries and system dependencies for portal scraping.
RUN uv run --project /app/etl playwright install chromium --with-deps

# Reset the entrypoint, don't invoke `uv`
ENTRYPOINT []

# Runs the SQS worker — long-polls the queue, scrapes incidents, writes results to S3
WORKDIR /app/etl
CMD ["uv", "run", "gv-dashboard-etl", "courts", "worker"]
