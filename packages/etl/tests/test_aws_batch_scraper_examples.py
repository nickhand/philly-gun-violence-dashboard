"""Smoke tests for aws-batch-scraper examples."""

import sys
from pathlib import Path

from aws_batch_scraper.types import ScrapeStatus, WorkItem


def test_courts_image_pins_snapshot_runtime_and_python_donor() -> None:
    """The release image must use immutable bases and one signed OS snapshot."""
    dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"
    source = dockerfile.read_text()

    expected_donor = (
        "FROM python:3.13-slim-trixie@"
        "sha256:ffb752e139c0a19692a43af8d8523b274222dd68eebad5d583b45c2201c6e30a "
        "AS python-runtime"
    )
    expected_final = (
        "FROM debian:sid-20260803-slim@"
        "sha256:76b6251aaac0ebb6aca1afbc780717aab7e455038c07cb0cb23facb33d241c7d"
    )
    snapshot = "http://snapshot.debian.org/archive/debian/20260819T000000Z"
    runtime_packages = (
        "ca-certificates",
        "libbz2-1.0",
        "libc6",
        "libdb5.3t64",
        "libffi8",
        "libgdbm6t64",
        "liblzma5",
        "libncursesw6",
        "libreadline8t64",
        "libsqlite3-0",
        "libssl3t64",
        "libtinfo6",
        "libuuid1",
        "libzstd1",
        "netbase",
        "tzdata",
        "zlib1g",
    )

    assert expected_donor in source
    assert expected_final in source
    assert source.index(expected_donor) < source.index(expected_final)
    assert snapshot in source
    assert "Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg" in source
    assert "Check-Valid-Until: no" in source
    assert "apt-get full-upgrade --yes --no-install-recommends" in source
    assert all(package in source for package in runtime_packages)
    copy_python = "COPY --from=python-runtime /usr/local /usr/local"
    assert source.index("apt-get full-upgrade") < source.index(copy_python)
    assert "debian:forky-slim" not in source
    assert "ENV UV_PYTHON=/usr/local/bin/python3" in source
    assert "ENV UV_PYTHON_DOWNLOADS=never" in source


def test_courts_image_declares_writable_tmp_volume() -> None:
    """Fargate must preserve writable /tmp permissions for the non-root app user."""
    dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"
    source = dockerfile.read_text()

    chmod = "RUN chmod 1777 /tmp"
    volume = 'VOLUME ["/tmp"]'
    assert chmod in source
    assert volume in source
    assert source.index(chmod) < source.index(volume) < source.index("USER app")


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
