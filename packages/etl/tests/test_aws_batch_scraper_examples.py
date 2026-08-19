"""Smoke tests for aws-batch-scraper examples."""

import sys
from pathlib import Path

from aws_batch_scraper.types import ScrapeStatus, WorkItem

from etl.chrome_release import (
    PINNED_CHROME_FILENAME,
    PINNED_CHROME_SHA256,
    PINNED_CHROME_VERSION,
)


def test_courts_image_pins_supported_ubuntu_snapshot_and_chrome() -> None:
    """The release image must use one immutable, scanner-supported runtime."""
    dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"
    source = dockerfile.read_text()

    expected_base = (
        "FROM public.ecr.aws/ubuntu/ubuntu:26.04@"
        "sha256:889d056d5c6c0bfb55789ff3710681d68e50713cb562d2196dc07110599c7a6f"
    )
    expected_chrome = f"ADD --checksum=sha256:{PINNED_CHROME_SHA256}"
    expected_product_version = PINNED_CHROME_VERSION.removesuffix("-1")

    assert expected_base in source
    assert "ARG UBUNTU_SNAPSHOT=20260819T160000Z" in source
    assert 'test "$UBUNTU_SNAPSHOT" = "20260819T160000Z"' in source
    assert source.count('apt-get -S "$UBUNTU_SNAPSHOT"') == 3
    assert 'apt-get -S "$UBUNTU_SNAPSHOT" --error-on=any update' in source
    assert "--yes --no-install-recommends full-upgrade" in source
    assert source.index("rm -rf /var/lib/apt/lists/*") < source.index(
        'apt-get -S "$UBUNTU_SNAPSHOT" --error-on=any update'
    )
    assert "snapshot.ubuntu.com_ubuntu_${UBUNTU_SNAPSHOT}_dists_${suite}_InRelease" in source
    assert source.count("|| exit 1;") >= 2
    assert "apt-get update" not in source
    assert "snapshot.debian.org" not in source
    assert (
        "ADD --checksum=sha256:c1f53878bdada693da7fb64a28c06b7dd65a43b8452e6fcad670c0d09c77f293"
    ) in source
    assert (
        "ADD --checksum=sha256:6077d27c6b6f8b23590cb01ff877ed8c804a67a5442cc32b5a33da10d2bd0e90"
    ) in source
    assert "openssl_3.5.5-1ubuntu3.3_amd64.deb" in source
    assert "ca-certificates_20260601~26.04.1_all.deb" in source
    assert expected_chrome in source
    assert PINNED_CHROME_FILENAME in source
    assert f'= "{PINNED_CHROME_VERSION}"' in source
    assert f'= "{expected_product_version}"' in source
    assert "/etc/apt/sources.list.d/google-chrome.list" in source
    assert "/etc/cron.daily/google-chrome" in source
    assert "/etc/default/google-chrome" in source
    sandbox_path = "/opt/google/chrome/chrome-sandbox"
    absence_check = f"test ! -e {sandbox_path}"
    assert source.count(sandbox_path) == 2
    assert absence_check in source
    assert source.index(sandbox_path) < source.index(absence_check)
    assert "chmod 0755 /opt/google/chrome/chrome-sandbox" not in source
    assert "chmod 4755 /opt/google/chrome/chrome-sandbox" not in source
    assert "ENV UV_PYTHON=/usr/bin/python3" in source
    assert "ENV UV_PYTHON_DOWNLOADS=never" in source
    assert "playwright install" not in source
    assert "PLAYWRIGHT_BROWSERS_PATH" not in source
    assert "test ! -e /ms-playwright" in source
    assert "/usr/bin/pebble" in source
    assert "ENV HOME=/tmp/app-home" in source
    assert "ENV XDG_CACHE_HOME=/tmp/app-home/.cache" in source
    assert "ENV XDG_CONFIG_HOME=/tmp/app-home/.config" in source
    assert "test -x /bin/false" in source
    assert '( /bin/false; test "$?" -eq 1 )' in source
    assert "ENTRYPOINT []" in source


def test_courts_image_declares_writable_tmp_volume() -> None:
    """Fargate must preserve writable /tmp permissions for the non-root app user."""
    dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"
    source = dockerfile.read_text()

    chmod = "RUN chmod 1777 /tmp"
    volume = 'VOLUME ["/tmp"]'
    assert chmod in source
    assert volume in source
    assert source.index(chmod) < source.index(volume) < source.index("USER app")


def test_courts_image_does_not_install_system_pip_or_venv() -> None:
    """The uv-managed app environment must not need Ubuntu's pip/venv packages."""
    dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"
    source = dockerfile.read_text()

    assert "python3-pip" not in source
    assert "python3-venv" not in source


def test_courts_image_strips_all_setuid_and_setgid_bits_after_installs() -> None:
    """The final courts image must contain no privilege-bearing file modes."""
    dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"
    source = dockerfile.read_text()

    strip_command = "find / -xdev -type f -perm /6000 -exec chmod a-s {} +"
    enumerate_command = 'privileged_paths="$(find / -xdev -type f -perm /6000 -print)"'
    absence_check = 'test -z "$privileged_paths"'
    assert strip_command in source
    assert enumerate_command in source
    assert absence_check in source
    assert source.rindex("uv sync") < source.index(strip_command) < source.index("USER app")


def test_daily_homicide_workflow_installs_the_same_exact_chrome() -> None:
    """The host-run homicide job must not use a drifting runner browser."""
    repo_root = Path(__file__).resolve().parents[3]
    source = (repo_root / ".github/workflows/daily-homicide-sync.yml").read_text()
    product_version = PINNED_CHROME_VERSION.removesuffix("-1")

    assert PINNED_CHROME_FILENAME in source
    assert PINNED_CHROME_SHA256 in source
    assert f"'{PINNED_CHROME_VERSION}'" in source
    assert f"'{product_version}'" in source
    assert "python3 packages/etl/src/etl/chrome_release.py" in source
    assert "--retry 3 --retry-all-errors --max-time 120" in source
    assert "--allow-downgrades" in source
    assert "playwright install" not in source
    assert "/etc/apt/sources.list.d/google-chrome.list" in source
    assert source.index("Verify pinned Chrome is still the signed stable release") < source.index(
        "aws-actions/configure-aws-credentials"
    )
    assert source.index("Install exact Google Chrome release") < source.index(
        "aws-actions/configure-aws-credentials"
    )
    assert source.index("aws-actions/configure-aws-credentials") < source.index("Run homicides ETL")


def test_etl_quality_uses_the_signed_chrome_freshness_verifier() -> None:
    """Container CI must reject a Chrome pin that is no longer stable."""
    repo_root = Path(__file__).resolve().parents[3]
    source = (repo_root / ".github/workflows/etl-quality.yml").read_text()

    assert "uv run python -m etl.chrome_release" in source


def test_etl_quality_browser_smoke_matches_fargate_security_profile() -> None:
    """Container CI must not relax seccomp to launch the courts browser."""
    repo_root = Path(__file__).resolve().parents[3]
    source = (repo_root / ".github/workflows/etl-quality.yml").read_text()

    assert "--security-opt seccomp=unconfined" not in source
    assert "chromium_sandbox=False" in source
    assert "chromium_sandbox=True" not in source
    assert "test ! -e /opt/google/chrome/chrome-sandbox" in source
    privilege_enumeration = 'privileged_paths="$(find / -xdev -type f -perm /6000 -print)"'
    assert "runtime_flags=(--rm --read-only --cap-drop ALL" in source
    assert "inspection_runtime_flags=(--rm --read-only --network none" in source
    assert "--user root philly-courts-scraper:ci" in source
    assert source.count(privilege_enumeration) == 1
    assert 'test -z "$privileged_paths"' in source
    assert "--forbid-chrome-sandbox" in source
    assert "--forbid-setuid-setgid-files" in source
    assert "--required-chrome-sandbox-sha256" not in source
    assert "root:root:755" not in source
    assert "root:root:4755" not in source
    assert "image_entrypoint=" in source
    assert "{{json .Config.Entrypoint}}" in source
    assert "test -x /bin/false" in source
    assert "philly-courts-scraper:ci /bin/false" in source


def test_release_and_smoke_run_standalone_chrome_freshness_script() -> None:
    """Release gates must not depend on separately installed ETL metadata."""
    repo_root = Path(__file__).resolve().parents[3]
    justfile = (repo_root / "Justfile").read_text()
    recipe = (repo_root / "packages/aws-batch-scraper/just/aws-batch-scraper.just").read_text()
    smoke = (repo_root / ".github/workflows/production-smoke.yml").read_text()

    script = "packages/etl/src/etl/chrome_release.py"
    assert f'aws_batch_scraper_browser_freshness_script := "{script}"' in justfile
    assert 'python3 "{{aws_batch_scraper_browser_freshness_script}}"' in recipe
    assert f"python3 {script}" in smoke


def test_simple_scraper_example_imports_and_scrapes() -> None:
    """The documented simple scraper example should import and satisfy the contract."""
    repo_root = Path(__file__).resolve().parents[2]
    example_path = repo_root / "aws-batch-scraper" / "examples" / "simple_scraper"
    sys.path.insert(0, str(example_path))
    try:
        from simple_scraper.inputs import load_items
        from simple_scraper.scraper import SimpleScraper

        items = load_items(config=None)  # ty: ignore[invalid-argument-type]
        result = SimpleScraper()(WorkItem(item_id="alpha"))
    finally:
        sys.path.remove(str(example_path))

    assert [item.item_id for item in items] == ["alpha", "beta", "missing-gamma"]
    assert result.status == ScrapeStatus.SUCCESS
    assert result.data == {"item_id": "alpha", "extra": {}}
