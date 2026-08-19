# Copy the official Python runtime from an immutable donor without carrying its
# vulnerable Debian userspace into the final image.
FROM python:3.13-slim-trixie@sha256:ffb752e139c0a19692a43af8d8523b274222dd68eebad5d583b45c2201c6e30a AS python-runtime

# Pin the exact linux/amd64 Sid manifest used by the ECR release build, then
# bring every base package forward to one signed, dated Debian snapshot.
FROM debian:sid-20260803-slim@sha256:76b6251aaac0ebb6aca1afbc780717aab7e455038c07cb0cb23facb33d241c7d

RUN printf '%s\n' \
        'Types: deb' \
        'URIs: http://snapshot.debian.org/archive/debian/20260819T000000Z' \
        'Suites: sid' \
        'Components: main' \
        'Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg' \
        'Check-Valid-Until: no' \
        > /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get full-upgrade --yes --no-install-recommends \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        libbz2-1.0 \
        libc6 \
        libdb5.3t64 \
        libffi8 \
        libgdbm6t64 \
        liblzma5 \
        libncursesw6 \
        libreadline8t64 \
        libsqlite3-0 \
        libssl3t64 \
        libtinfo6 \
        libuuid1 \
        libzstd1 \
        netbase \
        tzdata \
        zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY --from=python-runtime /usr/local /usr/local
COPY --from=ghcr.io/astral-sh/uv:0.12.0@sha256:606e70c71c852d03f611b1e56a195d08648507018a7057fab82c4974c4eae105 /uv /uvx /bin/

# Install the project into `/app`
WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy

# Omit development dependencies
ENV UV_NO_DEV=1

# Use the immutable donor's Python even after each package's `.python-version`
# is copied, and never download another interpreter during the image build.
ENV UV_PYTHON=/usr/local/bin/python3
ENV UV_PYTHON_DOWNLOADS=never

# Ensure installed tools can be executed out of the box
ENV UV_TOOL_BIN_DIR=/usr/local/bin

# Use a shared virtual environment for both projects.
ENV UV_PROJECT_ENVIRONMENT=/app/.venv

# Install browser binaries into a fixed runtime-readable path.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

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

# Runtime state belongs on the task's writable temporary volume. Application
# code, the virtual environment, and browser binaries remain image-owned and
# can therefore run with a read-only root filesystem. Set these after the build
# steps so uv's build cache and bytecode compilation retain their intended paths.
ENV HOME=/tmp
ENV XDG_CACHE_HOME=/tmp/.cache
ENV XDG_CONFIG_HOME=/tmp/.config
ENV TMPDIR=/tmp
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# The scraper does not need root privileges at runtime. Keep installed code and
# browser executables owned by root; the app user only needs to read/execute them.
# Preserve standard sticky /tmp permissions when Fargate populates the matching
# task bind mount from this image volume.
RUN chmod 1777 /tmp \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /tmp --no-create-home \
        --shell /usr/sbin/nologin app

VOLUME ["/tmp"]

# Reset the entrypoint, don't invoke `uv`
ENTRYPOINT []

# Runs the SQS worker — long-polls the queue, scrapes incidents, writes results to S3
WORKDIR /app/etl
USER app
CMD ["gv-dashboard-etl", "courts", "worker"]
