"""Verify that the pinned production Chrome package is still current.

The container build uses a checksum-pinned Google Chrome ``.deb``.  This
module independently verifies Google's signed APT metadata and fails when the
stable Linux package no longer matches that pin.  It deliberately performs no
installation and mutates no system keyring.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Final
from urllib.request import urlopen

__all__ = [
    "ChromeReleaseError",
    "PINNED_CHROME_FILENAME",
    "PINNED_CHROME_PRODUCT_VERSION",
    "PINNED_CHROME_SHA256",
    "PINNED_CHROME_VERSION",
    "verify_pinned_chrome_release",
]

GOOGLE_SIGNING_KEY_URL: Final = "https://dl.google.com/linux/linux_signing_key.pub"
GOOGLE_SIGNING_KEY_FINGERPRINT: Final = "EB4C1BFD4F042F6DDDCCEC917721F63BD38B4796"
GOOGLE_REPOSITORY_URL: Final = "https://dl.google.com/linux/chrome/deb"
GOOGLE_INRELEASE_URL: Final = f"{GOOGLE_REPOSITORY_URL}/dists/stable/InRelease"
GOOGLE_PACKAGES_PATH: Final = "main/binary-amd64/Packages.gz"
GOOGLE_PACKAGES_URL: Final = f"{GOOGLE_REPOSITORY_URL}/dists/stable/{GOOGLE_PACKAGES_PATH}"

PINNED_CHROME_VERSION: Final = "151.0.7922.173-1"
PINNED_CHROME_PRODUCT_VERSION: Final = "151.0.7922.173"
PINNED_CHROME_FILENAME: Final = (
    "pool/main/g/google-chrome-stable/google-chrome-stable_151.0.7922.173-1_amd64.deb"
)
PINNED_CHROME_SHA256: Final = "878e5ab495b8a694980fca61bc09b37e651ccedce2291c73434d16e48a2646fd"

_MAX_KEY_BYTES: Final = 1_000_000
_MAX_INRELEASE_BYTES: Final = 1_000_000
_MAX_PACKAGES_BYTES: Final = 10_000_000
_MAX_PACKAGES_UNCOMPRESSED_BYTES: Final = 50_000_000
_DOWNLOAD_TIMEOUT_SECONDS: Final = 30.0
_COMMAND_TIMEOUT_SECONDS: Final = 30.0
# Chrome Stable normally republishes within a weekly cadence.  Fourteen days
# rejects replayed metadata without making a quiet release week an outage.
_MAX_INRELEASE_AGE: Final = timedelta(days=14)
_MAX_CLOCK_SKEW: Final = timedelta(minutes=5)

Fetcher = Callable[[str, int], bytes]
CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
Clock = Callable[[], datetime]


class ChromeReleaseError(RuntimeError):
    """Raised when the signed stable-channel metadata cannot prove freshness."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _download(url: str, max_bytes: int) -> bytes:
    """Download one fixed Google metadata URL with an explicit size bound."""
    with urlopen(url, timeout=_DOWNLOAD_TIMEOUT_SECONDS) as response:  # noqa: S310
        body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise ChromeReleaseError(f"Chrome metadata exceeded {max_bytes} bytes")
    if not body:
        raise ChromeReleaseError("Chrome metadata response was empty")
    return body


def _run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run one local signature command without invoking a shell."""
    return subprocess.run(  # noqa: S603
        list(command),
        check=False,
        capture_output=True,
        text=True,
        timeout=_COMMAND_TIMEOUT_SECONDS,
    )


def _require_success(
    runner: CommandRunner,
    command: Sequence[str],
    *,
    label: str,
) -> subprocess.CompletedProcess[str]:
    result = runner(command)
    if result.returncode != 0:
        raise ChromeReleaseError(f"{label} failed")
    return result


def _primary_fingerprints(colon_output: str) -> tuple[str, ...]:
    """Return every primary-key fingerprint from GnuPG colon output."""
    awaiting_primary_fingerprint = False
    fingerprints: list[str] = []
    for line in colon_output.splitlines():
        fields = line.split(":")
        record_type = fields[0] if fields else ""
        if record_type == "pub":
            if awaiting_primary_fingerprint:
                raise ChromeReleaseError("Google signing key omitted a primary fingerprint")
            awaiting_primary_fingerprint = True
            continue
        if record_type == "sub":
            if awaiting_primary_fingerprint:
                raise ChromeReleaseError("Google signing key omitted a primary fingerprint")
            awaiting_primary_fingerprint = False
            continue
        if awaiting_primary_fingerprint and record_type == "fpr" and len(fields) > 9:
            fingerprint = fields[9]
            if fingerprint:
                fingerprints.append(fingerprint)
                awaiting_primary_fingerprint = False
    if awaiting_primary_fingerprint or not fingerprints:
        raise ChromeReleaseError("Google signing key omitted a primary fingerprint")
    return tuple(fingerprints)


def _verify_signature(
    *,
    signing_key: bytes,
    inrelease: bytes,
    directory: Path,
    runner: CommandRunner,
) -> bytes:
    """Return the authenticated cleartext from one pinned signing key."""
    key_path = directory / "google-linux-signing-key.asc"
    keyring_path = directory / "google-linux-signing-key.gpg"
    inrelease_path = directory / "InRelease"
    gnupg_home = directory / "gnupg"
    gnupg_home.mkdir(mode=0o700)
    key_path.write_bytes(signing_key)
    inrelease_path.write_bytes(inrelease)

    shown = _require_success(
        runner,
        [
            "gpg",
            "--batch",
            "--homedir",
            str(gnupg_home),
            "--show-keys",
            "--with-colons",
            str(key_path),
        ],
        label="Google signing-key inspection",
    )
    if _primary_fingerprints(shown.stdout) != (GOOGLE_SIGNING_KEY_FINGERPRINT,):
        raise ChromeReleaseError(
            "Google signing-key bundle must contain exactly one pinned primary fingerprint"
        )

    _require_success(
        runner,
        [
            "gpg",
            "--batch",
            "--yes",
            "--homedir",
            str(gnupg_home),
            "--dearmor",
            "--output",
            str(keyring_path),
            str(key_path),
        ],
        label="Google signing-key conversion",
    )
    verified = _require_success(
        runner,
        [
            "gpgv",
            "--output",
            "-",
            "--keyring",
            str(keyring_path),
            str(inrelease_path),
        ],
        label="Google Chrome repository signature verification",
    )
    if not verified.stdout:
        raise ChromeReleaseError(
            "Google Chrome signature verification returned no authenticated cleartext"
        )
    return verified.stdout.encode("utf-8")


def _inrelease_sha256(inrelease: bytes, path: str) -> tuple[str, int]:
    """Read one exact file checksum and size from the signed SHA256 section."""
    try:
        text = inrelease.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ChromeReleaseError("Google InRelease metadata was not UTF-8") from exc

    in_sha256 = False
    matches: list[tuple[str, int]] = []
    for line in text.splitlines():
        if line == "SHA256:":
            in_sha256 = True
            continue
        if in_sha256 and line and not line.startswith(" "):
            break
        if not in_sha256 or not line.strip():
            continue
        fields = line.split()
        if len(fields) == 3 and fields[2] == path:
            digest, size_text, _ = fields
            if len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest
            ):
                raise ChromeReleaseError("Google InRelease contained an invalid SHA256 digest")
            try:
                size = int(size_text)
            except ValueError as exc:
                raise ChromeReleaseError("Google InRelease contained an invalid file size") from exc
            if size < 1:
                raise ChromeReleaseError("Google InRelease contained an invalid file size")
            matches.append((digest, size))
    if len(matches) != 1:
        raise ChromeReleaseError(f"Google InRelease did not identify exactly one {path} artifact")
    return matches[0]


def _require_fresh_inrelease(inrelease: bytes, *, now: datetime) -> None:
    """Reject signed metadata for a different channel or a replayed release."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Chrome freshness clock must return a timezone-aware datetime")
    try:
        text = inrelease.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ChromeReleaseError("Google InRelease metadata was not UTF-8") from exc
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if line in {"MD5Sum:", "SHA1:", "SHA256:"}:
            break
        name, separator, value = line.partition(":")
        if separator and name and name not in fields:
            fields[name] = value.strip()
    if fields.get("Origin") != "Google LLC":
        raise ChromeReleaseError("Google InRelease identified an unexpected repository origin")
    if fields.get("Suite") != "stable" or fields.get("Codename") != "stable":
        raise ChromeReleaseError("Google InRelease did not identify the stable channel")
    if "amd64" not in fields.get("Architectures", "").split():
        raise ChromeReleaseError("Google InRelease did not advertise amd64 packages")
    date_value = fields.get("Date")
    if not date_value:
        raise ChromeReleaseError("Google InRelease omitted its publication date")
    try:
        published_at = parsedate_to_datetime(date_value)
    except (TypeError, ValueError) as exc:
        raise ChromeReleaseError("Google InRelease had an invalid publication date") from exc
    if published_at.tzinfo is None or published_at.utcoffset() is None:
        raise ChromeReleaseError("Google InRelease had an invalid publication date")
    age = now.astimezone(UTC) - published_at.astimezone(UTC)
    if age < -_MAX_CLOCK_SKEW:
        raise ChromeReleaseError("Google InRelease publication date is in the future")
    if age > _MAX_INRELEASE_AGE:
        raise ChromeReleaseError("Google InRelease metadata is stale")


def _verify_packages_artifact(inrelease: bytes, packages_gzip: bytes) -> bytes:
    expected_digest, expected_size = _inrelease_sha256(inrelease, GOOGLE_PACKAGES_PATH)
    if len(packages_gzip) != expected_size:
        raise ChromeReleaseError("Google Packages metadata size did not match InRelease")
    actual_digest = hashlib.sha256(packages_gzip).hexdigest()
    if actual_digest != expected_digest:
        raise ChromeReleaseError("Google Packages metadata checksum did not match InRelease")
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(packages_gzip)) as compressed:
            packages = compressed.read(_MAX_PACKAGES_UNCOMPRESSED_BYTES + 1)
    except (EOFError, OSError) as exc:
        raise ChromeReleaseError("Google Packages metadata was not valid gzip data") from exc
    if len(packages) > _MAX_PACKAGES_UNCOMPRESSED_BYTES:
        raise ChromeReleaseError("Google Packages metadata expanded beyond its size limit")
    return packages


def _package_stanzas(packages: bytes) -> list[Mapping[str, str]]:
    """Parse the simple deb822 fields needed from an APT Packages document."""
    try:
        text = packages.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ChromeReleaseError("Google Packages metadata was not UTF-8") from exc

    stanzas: list[Mapping[str, str]] = []
    for raw_stanza in text.strip().split("\n\n"):
        fields: dict[str, str] = {}
        for line in raw_stanza.splitlines():
            if not line or line.startswith((" ", "\t")):
                continue
            name, separator, value = line.partition(":")
            if not separator or not name or name in fields:
                raise ChromeReleaseError("Google Packages metadata contained malformed fields")
            fields[name] = value.strip()
        if fields:
            stanzas.append(fields)
    if not stanzas:
        raise ChromeReleaseError("Google Packages metadata contained no packages")
    return stanzas


def _require_current_pin(packages: bytes) -> None:
    matches = [
        stanza
        for stanza in _package_stanzas(packages)
        if stanza.get("Package") == "google-chrome-stable" and stanza.get("Architecture") == "amd64"
    ]
    if len(matches) != 1:
        raise ChromeReleaseError(
            "Google Packages metadata did not contain one amd64 stable Chrome package"
        )
    package = matches[0]
    observed = (
        package.get("Version"),
        package.get("Filename"),
        package.get("SHA256"),
    )
    expected = (
        PINNED_CHROME_VERSION,
        PINNED_CHROME_FILENAME,
        PINNED_CHROME_SHA256,
    )
    if observed != expected:
        raise ChromeReleaseError(
            "Pinned Chrome is no longer the signed stable Linux release: "
            f"expected {PINNED_CHROME_VERSION}, observed {package.get('Version', 'missing')}"
        )


def verify_pinned_chrome_release(
    *,
    fetcher: Fetcher = _download,
    runner: CommandRunner = _run,
    clock: Clock = _utc_now,
) -> None:
    """Require the Dockerfile's Chrome pin to equal Google's signed stable metadata."""
    signing_key = fetcher(GOOGLE_SIGNING_KEY_URL, _MAX_KEY_BYTES)
    inrelease = fetcher(GOOGLE_INRELEASE_URL, _MAX_INRELEASE_BYTES)
    packages_gzip = fetcher(GOOGLE_PACKAGES_URL, _MAX_PACKAGES_BYTES)
    with tempfile.TemporaryDirectory(prefix="chrome-release-") as raw_directory:
        verified_inrelease = _verify_signature(
            signing_key=signing_key,
            inrelease=inrelease,
            directory=Path(raw_directory),
            runner=runner,
        )
    _require_fresh_inrelease(verified_inrelease, now=clock())
    packages = _verify_packages_artifact(verified_inrelease, packages_gzip)
    _require_current_pin(packages)


def main() -> int:
    """Run the signed Chrome freshness gate."""
    try:
        verify_pinned_chrome_release()
    except (ChromeReleaseError, OSError, subprocess.SubprocessError) as exc:
        print(f"Chrome freshness check failed: {exc}", file=sys.stderr)
        return 1
    print(f"Chrome pin is current: {PINNED_CHROME_VERSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
