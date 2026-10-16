#!/usr/bin/env python3
"""Build the scraper image, retrying only identified upstream HTTP failures."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

# SHA256 of Canonical's observed 108-byte HTTP 503 response body. Never accept
# these bytes: BuildKit rejects them, and a retry must still pass ADD's checksum.
CANONICAL_503_SHA256 = "212a2d2e355cec068c4c4f041281aa42b663d3defcb647b11974f362712159fc"
BUILD_COMMAND = (
    "docker",
    "build",
    "--progress=plain",
    "--file",
    "packages/etl/Dockerfile",
    "--tag",
    "philly-courts-scraper:ci",
    ".",
)
MAX_ATTEMPTS = 3
BUILD_ARCHIVE: Path | None = None
_DIGEST_MISMATCH = re.compile(r"digest mismatch sha256:([0-9a-f]{64}):")
_HTTP_TRANSIENT = re.compile(
    r"\b(?:429\s+Too\s+Many\s+Requests|502\s+Bad\s+Gateway|"
    r"503\s+Service\s+Unavailable|504\s+Gateway\s+Timeout)\b"
    r"|\b(?:HTTP(?:/[0-9.]+)?(?: status)?|status code)\s*[:=]?\s*(?:429|502|503|504)\b",
    re.IGNORECASE,
)


def transient_download_failure(output: str) -> bool:
    """Require every reported build error to be a recognized download failure."""
    mismatches = _DIGEST_MISMATCH.findall(output)
    if any(digest != CANONICAL_503_SHA256 for digest in mismatches):
        return False
    errors = [line for line in output.splitlines() if re.search(r"(?:^|\s)(?:ERROR:|E:)", line)]
    if not errors:
        return False
    apt_transient = any(
        "E: Failed to fetch http" in line and _HTTP_TRANSIENT.search(line) for line in errors
    )
    for line in errors:
        if _DIGEST_MISMATCH.search(line):
            continue
        if "did not complete successfully: exit code:" in line:
            if apt_transient and "apt-get" in line and line.endswith("exit code: 100"):
                continue
            return False
        if _HTTP_TRANSIENT.search(line) and re.search(r"https?://|download|fetch", line, re.I):
            continue
        if apt_transient and (
            "E: Some index files failed to download" in line
            or "E: Unable to fetch some archives" in line
        ):
            continue
        return False
    return True


def run_build() -> subprocess.CompletedProcess[str]:
    """Stream normal build output while retaining a bounded diagnostic tail."""
    tail: deque[str] = deque(maxlen=4000)
    archive = BUILD_ARCHIVE.open("rb") if BUILD_ARCHIVE is not None else None
    try:
        with subprocess.Popen(
            BUILD_COMMAND,
            stdin=archive,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        ) as process:
            assert process.stdout is not None
            for line in process.stdout:
                print(line, end="", flush=True)
                tail.append(line[-8192:])
            return subprocess.CompletedProcess(BUILD_COMMAND, process.wait(), "".join(tail))
    finally:
        if archive is not None:
            archive.close()


def build_with_retry(
    runner: Callable[[], subprocess.CompletedProcess[str]] = run_build,
    sleeper: Callable[[float], None] = time.sleep,
) -> int:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        result = runner()
        if result.returncode == 0:
            return 0
        # Never restart work interrupted by a signal (including shell encoding).
        if result.returncode < 0 or result.returncode >= 128:
            return result.returncode
        if attempt == MAX_ATTEMPTS or not transient_download_failure(result.stdout):
            return result.returncode
        delay = 20 * attempt
        print(
            f"Upstream download failed; retrying scraper build in {delay}s "
            f"(attempt {attempt + 1}/{MAX_ATTEMPTS}).",
            file=sys.stderr,
            flush=True,
        )
        sleeper(delay)
    raise AssertionError("unreachable")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-tag")
    args = parser.parse_args()
    if args.release_tag is None:
        sys.exit(build_with_retry())
    # Release context comes exclusively from the exact commit, including on retries.
    if re.fullmatch(r"[0-9a-f]{40}", args.release_tag) is None:
        parser.error("release tag must be a full commit SHA")
    if subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip() != args.release_tag:
        parser.error("release tag must equal HEAD")
    with tempfile.TemporaryDirectory(prefix="scraper-release-") as directory:
        BUILD_ARCHIVE = Path(directory) / "source.tar"
        with BUILD_ARCHIVE.open("wb") as stream:
            subprocess.run(["git", "archive", "--format=tar", "HEAD"], stdout=stream, check=True)
        BUILD_COMMAND = (
            "docker",
            "build",
            "--progress=plain",
            "--platform",
            "linux/amd64",
            "--label",
            f"org.opencontainers.image.revision={args.release_tag}",
            "--file",
            "packages/etl/Dockerfile",
            "--tag",
            f"ujs-scraper:{args.release_tag}",
            "-",
        )
        sys.exit(build_with_retry())
