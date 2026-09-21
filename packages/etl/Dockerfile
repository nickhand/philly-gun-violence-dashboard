# Use an ECR-supported LTS userspace and pin its exact linux/amd64 manifest.
FROM public.ecr.aws/ubuntu/ubuntu:26.04@sha256:99b345756d0ddb56dd7ab9c8d26f6ab41364506c00757a8c5b7ee793ea07fca3 AS ubuntu-base

# Ubuntu 26.04's stock deb822 sources use Canonical's signed archive and support
# apt snapshots. Validate the build argument before every apt transaction so a
# caller cannot silently replace the reviewed package set with another date.
ARG UBUNTU_SNAPSHOT=20260921T180000Z

# The minimal Ubuntu base intentionally omits CA roots, but apt snapshots use
# HTTPS. Bootstrap the exact CA dependency pair recorded in Canonical's signed
# resolute-security Packages index for this snapshot before the first apt call.
ADD --checksum=sha256:0cea6b98673ff88218b7e5f18c1bd42f06bdfcae6c1ebc9964adf3bc41420c19 \
    https://snapshot.ubuntu.com/ubuntu/20260921T180000Z/pool/main/o/openssl/openssl_3.5.5-1ubuntu3.5_amd64.deb \
    /tmp/openssl.deb
ADD --checksum=sha256:6077d27c6b6f8b23590cb01ff877ed8c804a67a5442cc32b5a33da10d2bd0e90 \
    https://snapshot.ubuntu.com/ubuntu/20260921T180000Z/pool/main/c/ca-certificates/ca-certificates_20260601~26.04.1_all.deb \
    /tmp/ca-certificates.deb

RUN DEBIAN_FRONTEND=noninteractive dpkg --install \
        /tmp/openssl.deb /tmp/ca-certificates.deb \
    && test "$(dpkg-query --show --showformat='${Version}' openssl)" \
        = "3.5.5-1ubuntu3.5" \
    && test "$(dpkg-query --show --showformat='${Version}' ca-certificates)" \
        = "20260601~26.04.1" \
    && test -s /etc/ssl/certs/ca-certificates.crt \
    && rm -f /tmp/openssl.deb /tmp/ca-certificates.deb

# Canonical reverted its CVE-2026-87766 backport (USN-8779-2). Build the
# checksum-pinned upstream fix as a real replacement package in a separate stage;
# keep package ownership/version evidence and omit all build tools from runtime.
FROM ubuntu-base AS bubblewrap-build
ADD --checksum=sha256:9760d007363e3abba7c747489910f9f82d9fca53ba3bd3282e396fa3c97a3314 \
    https://github.com/containers/bubblewrap/releases/download/v0.12.0/bubblewrap-0.12.0.tar.xz \
    /tmp/bubblewrap.tar.xz
RUN test "$UBUNTU_SNAPSHOT" = "20260921T180000Z" \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get -S "$UBUNTU_SNAPSHOT" --error-on=any update \
    && DEBIAN_FRONTEND=noninteractive apt-get -S "$UBUNTU_SNAPSHOT" \
        --yes --no-install-recommends install \
        build-essential meson pkg-config libcap-dev libselinux1-dev xz-utils \
    && mkdir /build \
    && python3 -c \
        "import tarfile; tarfile.open('/tmp/bubblewrap.tar.xz').extractall('/build', filter='data')" \
    && cd /build/bubblewrap-0.12.0 \
    && CFLAGS="$(dpkg-buildflags --get CFLAGS)" \
        CPPFLAGS="$(dpkg-buildflags --get CPPFLAGS)" \
        LDFLAGS="$(dpkg-buildflags --get LDFLAGS)" \
        meson setup build --prefix=/usr --buildtype=release \
        -Dman=disabled -Dbash_completion=disabled -Dzsh_completion=disabled \
        -Dselinux=enabled \
    && meson compile -C build \
    && meson test -C build test-utils --print-errorlogs \
    && DESTDIR=/package meson install -C build \
    && test "$(/package/usr/bin/bwrap --version)" = "bubblewrap 0.12.0" \
    && mkdir -p /package/DEBIAN /package/usr/share/doc/bubblewrap \
    && cp COPYING COPYING.LIB LICENSE /package/usr/share/doc/bubblewrap/ \
    && printf '%s\n' \
        'Package: bubblewrap' \
        'Version: 0.12.0-0philly1' \
        'Architecture: amd64' \
        'Maintainer: Philadelphia Gun Violence Dashboard <noreply@github.com>' \
        'Depends: libc6 (>= 2.43), libcap2 (>= 1:2.10), libselinux1 (>= 3.1)' \
        'Homepage: https://github.com/containers/bubblewrap' \
        'Description: Upstream Bubblewrap security release for the courts image' \
        > /package/DEBIAN/control \
    # Python tar creation also works under amd64 emulation, where this Ubuntu
    # GNU tar requires unsupported stat syscalls. Keep the standard deb layout.
    && python3 -c \
        "import tarfile; from pathlib import Path; Path('/debian-binary').write_text('2.0\\n'); control = tarfile.open('/control.tar.gz', 'w:gz', format=tarfile.GNU_FORMAT); control.add('/package/DEBIAN/control', arcname='./control'); control.close(); data = tarfile.open('/data.tar.gz', 'w:gz', format=tarfile.GNU_FORMAT); data.add('/package/usr', arcname='./usr'); data.close()" \
    && ar rD /bubblewrap.deb /debian-binary /control.tar.gz /data.tar.gz \
    && dpkg-deb --info /bubblewrap.deb

FROM ubuntu-base AS runtime
COPY --from=bubblewrap-build /bubblewrap.deb /tmp/bubblewrap.deb
# Fetch the exact signed Google Chrome package as a checksum-pinned build input.
# Installing the local deb through apt lets Ubuntu resolve its runtime libraries
# from the same signed snapshot as the rest of the image.
# BEGIN GENERATED: chrome-lock-package
ADD --checksum=sha256:29e0e4b5af01213915ffdb7f4e49a11956dc5fc591165c85af8688dcdff907ac \
    https://dl.google.com/linux/chrome/deb/pool/main/g/google-chrome-stable/google-chrome-stable_153.0.8010.52-1_amd64.deb \
    /tmp/google-chrome-stable.deb
# END GENERATED: chrome-lock-package

# The September 21 snapshot includes Canonical's security backports for
# OpenSSL, Perl, Python, libcurl, and libaom. Pin and
# assert it below so stale packages cannot silently return to the image.
#
# Fargate's default seccomp profile cannot start Chrome's nested namespace
# sandbox. The courts worker therefore disables that sandbox, so the runtime
# image removes the otherwise unused privilege-bearing helper entirely.
RUN test "$UBUNTU_SNAPSHOT" = "20260921T180000Z" \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get -S "$UBUNTU_SNAPSHOT" --error-on=any update \
    && for suite in resolute resolute-updates resolute-backports resolute-security; do \
        test -f \
            "/var/lib/apt/lists/snapshot.ubuntu.com_ubuntu_${UBUNTU_SNAPSHOT}_dists_${suite}_InRelease" \
            || exit 1; \
        find /var/lib/apt/lists -maxdepth 1 -type f \
            -name "snapshot.ubuntu.com_ubuntu_${UBUNTU_SNAPSHOT}_dists_${suite}_*_binary-amd64_Packages.lz4" \
            -print -quit | grep -q . \
            || exit 1; \
    done \
    && DEBIAN_FRONTEND=noninteractive apt-get -S "$UBUNTU_SNAPSHOT" \
        --yes --no-install-recommends full-upgrade \
    && DEBIAN_FRONTEND=noninteractive apt-get -S "$UBUNTU_SNAPSHOT" \
        --yes --no-install-recommends install \
        ca-certificates \
        netbase \
        python3 \
        tzdata \
        /tmp/google-chrome-stable.deb /tmp/bubblewrap.deb \
    && test "$(dpkg-query --show --showformat='${Version}' google-chrome-stable)" \
        = "153.0.8010.52-1" \
    && test "$(dpkg-query --show --showformat='${Version}' libcurl3t64-gnutls)" \
        = "8.18.0-1ubuntu2.5" \
    && test "$(dpkg-query --show --showformat='${Version}' libaom3)" \
        = "3.13.1-2ubuntu0.1" \
    && test "$(dpkg-query --show --showformat='${Version}' bubblewrap)" \
        = "0.12.0-0philly1" \
    && test "$(bwrap --version)" = "bubblewrap 0.12.0" \
    && test -z "$(dpkg --audit)" \
    && test "$(google-chrome --product-version)" = "153.0.8010.52" \
    && python3 -c 'import sys; assert sys.version_info >= (3, 13), sys.version' \
    && rm -f \
        /tmp/google-chrome-stable.deb /tmp/bubblewrap.deb \
        /opt/google/chrome/chrome-sandbox \
        /etc/apt/sources.list.d/google-chrome.list \
        /etc/apt/trusted.gpg.d/google-chrome.gpg \
        /etc/cron.daily/google-chrome \
        /etc/default/google-chrome \
        /usr/share/keyrings/google-linux-signing-keyring.gpg \
        /usr/bin/pebble \
    && test ! -e /opt/google/chrome/chrome-sandbox \
    && rm -rf /opt/google/chrome/cron \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12.0@sha256:606e70c71c852d03f611b1e56a195d08648507018a7057fab82c4974c4eae105 /uv /uvx /bin/

# Install the project into `/app`.
WORKDIR /app

# Enable bytecode compilation.
ENV UV_COMPILE_BYTECODE=1

# Copy from the cache instead of linking since it's a mounted volume.
ENV UV_LINK_MODE=copy

# Omit development dependencies.
ENV UV_NO_DEV=1

# Use Ubuntu's supported native Python and never download another interpreter.
ENV UV_PYTHON=/usr/bin/python3
ENV UV_PYTHON_DOWNLOADS=never

# Ensure installed tools can be executed out of the box.
ENV UV_TOOL_BIN_DIR=/usr/local/bin

# Use a shared virtual environment for all three projects.
ENV UV_PROJECT_ENVIRONMENT=/app/.venv

# Copy lockfiles and minimal sources first to maximize cache reuse.
COPY packages/aws-batch-scraper/pyproject.toml packages/aws-batch-scraper/uv.lock /app/aws-batch-scraper/
COPY packages/aws-batch-scraper/src/ /app/aws-batch-scraper/src/
COPY packages/dashboard-utils/pyproject.toml packages/dashboard-utils/uv.lock /app/dashboard-utils/
COPY packages/dashboard-utils/src/ /app/dashboard-utils/src/
COPY packages/etl/pyproject.toml packages/etl/uv.lock /app/etl/
RUN touch \
    /app/aws-batch-scraper/README.md \
    /app/dashboard-utils/README.md \
    /app/etl/README.md

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project /app/aws-batch-scraper --locked --no-install-project \
    && uv sync --project /app/dashboard-utils --locked --no-install-project \
    && uv sync --project /app/etl --locked --no-install-project

# Copy only runtime sources after dependencies are installed. Tests, local
# recipes, examples, and documentation must not perturb the release image.
COPY packages/aws-batch-scraper/src/ /app/aws-batch-scraper/src/
COPY packages/dashboard-utils/src/ /app/dashboard-utils/src/
COPY packages/etl/src/ /app/etl/src/

# Install the source code into the environment and then fail closed if the
# runtime drifted from the reviewed Python, Playwright, or Chrome contracts.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project /app/aws-batch-scraper --locked \
    && uv sync --project /app/dashboard-utils --locked \
    && uv sync --project /app/etl --locked \
    && /app/.venv/bin/python -c \
        "import importlib.metadata as m, sys; assert sys.version_info >= (3, 13), sys.version; assert m.version('playwright') == '1.62.0'" \
    && test "$(google-chrome --product-version)" = "153.0.8010.52" \
    && test ! -e /ms-playwright \
    && test ! -e /root/.cache/ms-playwright

# Place executables in the environment at the front of the path.
ENV PATH="/app/.venv/bin:$PATH"

# Runtime state belongs on the task's writable temporary volume. Application
# code, the virtual environment, and Google Chrome remain image-owned and can
# therefore run with a read-only root filesystem. Set these after the build
# steps so uv's build cache and bytecode compilation retain their intended paths.
ENV HOME=/tmp/app-home
ENV XDG_CACHE_HOME=/tmp/app-home/.cache
ENV XDG_CONFIG_HOME=/tmp/app-home/.config
ENV TMPDIR=/tmp
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# The scraper does not need root privileges at runtime. Keep installed code and
# browser executables owned by root; the app user only needs to read/execute them.
# Preserve standard sticky /tmp permissions when Fargate populates the matching
# task bind mount from this image volume.
RUN chmod 1777 /tmp \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /tmp/app-home --no-create-home \
        --shell /usr/sbin/nologin app

# No runtime path needs setuid or setgid execution. Strip every privilege bit
# after all OS and application installs, then fail closed if any remain. The
# monitor task's inert default command must also exist and return false directly.
RUN test -x /bin/false \
    && ( /bin/false; test "$?" -eq 1 ) \
    && find / -xdev -type f -perm /6000 -exec chmod a-s {} + \
    && privileged_paths="$(find / -xdev -type f -perm /6000 -print)" \
    && test -z "$privileged_paths"

VOLUME ["/tmp"]

# Reset the entrypoint; don't invoke uv at runtime.
ENTRYPOINT []

# Run the SQS worker: long-poll the queue, scrape incidents, and write results to S3.
WORKDIR /app/etl
USER app
CMD ["gv-dashboard-etl", "courts", "worker"]
