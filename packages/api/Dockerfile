FROM python:3.14.9-slim-trixie@sha256:b347e2dcbc7f0b6f9fb7182e9da6a187fb10ae715e0692518c1aed0eec94a700
COPY --from=ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff /uv /uvx /bin/

# Distrust both the compromised emSign root and its AAA cross-signing path.
# https://emudhra.we-have-a-problem.com/#workarounds
RUN sed -i \
        -e 's|^mozilla/emSign_ECC_Root_CA_-_G3.crt|!&|' \
        -e 's|^mozilla/Comodo_AAA_Services_root.crt|!&|' \
        /etc/ca-certificates.conf \
    && update-ca-certificates --fresh \
    && test ! -e /etc/ssl/certs/emSign_ECC_Root_CA_-_G3.pem \
    && test ! -e /etc/ssl/certs/Comodo_AAA_Services_root.pem

# The interpreter and ensurepip seed must both carry the fixed vendored CA bundle.
RUN python -c "import ensurepip, pip, pip._vendor.certifi as certifi; assert tuple(map(int, pip.__version__.split('.'))) >= (26, 2, 2); assert tuple(map(int, ensurepip.version().split('.'))) >= (26, 2, 2); assert tuple(map(int, certifi.__version__.split('.'))) >= (2026, 10, 19)"

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
