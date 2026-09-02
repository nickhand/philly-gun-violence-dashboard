"""Validate and update the pinned production Chrome package lock.

The container build uses a checksum-pinned Google Chrome ``.deb``.  This
module loads the repository's strict lock contract, independently verifies
Google's signed APT metadata, and can resolve a new lock without installing the
package or mutating the system keyring.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Final, cast
from urllib.request import urlopen

__all__ = [
    "CHROME_LOCK_PATH",
    "ChromeLock",
    "ChromeLockUpdate",
    "ChromeReleaseError",
    "PINNED_CHROME_EXECUTABLE_SHA256",
    "PINNED_CHROME_FILENAME",
    "PINNED_CHROME_PRODUCT_VERSION",
    "PINNED_CHROME_SHA256",
    "PINNED_CHROME_VERSION",
    "load_chrome_lock",
    "resolve_current_chrome_lock",
    "update_chrome_lock",
    "verify_pinned_chrome_release",
]

GOOGLE_SIGNING_KEY_URL: Final = "https://dl.google.com/linux/linux_signing_key.pub"
GOOGLE_SIGNING_KEY_FINGERPRINT: Final = "EB4C1BFD4F042F6DDDCCEC917721F63BD38B4796"
GOOGLE_REPOSITORY_URL: Final = "https://dl.google.com/linux/chrome/deb"
GOOGLE_INRELEASE_URL: Final = f"{GOOGLE_REPOSITORY_URL}/dists/stable/InRelease"
GOOGLE_PACKAGES_PATH: Final = "main/binary-amd64/Packages.gz"
GOOGLE_PACKAGES_URL: Final = f"{GOOGLE_REPOSITORY_URL}/dists/stable/{GOOGLE_PACKAGES_PATH}"
CHROME_LOCK_PATH: Final = Path(__file__).resolve().parents[2] / "chrome-lock.json"

_MAX_KEY_BYTES: Final = 1_000_000
_MAX_INRELEASE_BYTES: Final = 1_000_000
_MAX_PACKAGES_BYTES: Final = 10_000_000
_MAX_PACKAGES_UNCOMPRESSED_BYTES: Final = 50_000_000
_MAX_DEB_BYTES: Final = 500_000_000
_MAX_EXECUTABLE_BYTES: Final = 300_000_000
_DOWNLOAD_TIMEOUT_SECONDS: Final = 30.0
_COMMAND_TIMEOUT_SECONDS: Final = 30.0
# Chrome Stable normally republishes within a weekly cadence.  Fourteen days
# rejects replayed metadata without making a quiet release week an outage.
_MAX_INRELEASE_AGE: Final = timedelta(days=14)
_MAX_CLOCK_SKEW: Final = timedelta(minutes=5)
_LOCK_SCHEMA_VERSION: Final = 1
_CHROME_PACKAGE_NAME: Final = "google-chrome-stable"
_CHROME_ARCHITECTURE: Final = "amd64"
_CHROME_EXECUTABLE_PATH: Final = "/opt/google/chrome/chrome"
_CHROME_VERSION_PATTERN: Final = re.compile(r"^(?P<product>[1-9][0-9]*\.[0-9]+\.[0-9]+\.[0-9]+)-1$")
_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_AR_MAGIC: Final = b"!<arch>\n"
_AR_HEADER_SIZE: Final = 60
_AR_FILE_MAGIC: Final = b"`\n"
_DATA_ARCHIVE_NAMES: Final = frozenset({"data.tar", "data.tar.bz2", "data.tar.gz", "data.tar.xz"})

Fetcher = Callable[[str, int], bytes]
CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
Clock = Callable[[], datetime]


class ChromeReleaseError(RuntimeError):
    """Raised when the signed stable-channel metadata cannot prove freshness."""


@dataclass(frozen=True)
class ChromeSourceLock:
    """Authenticated repository coordinates stored in the Chrome lock."""

    repository: str
    suite: str
    component: str


@dataclass(frozen=True)
class ChromePackageLock:
    """Exact Debian package identity stored in the Chrome lock."""

    name: str
    architecture: str
    version: str
    product_version: str
    filename: str
    sha256: str


@dataclass(frozen=True)
class ChromeExecutableLock:
    """Exact installed browser payload identity stored in the Chrome lock."""

    path: str
    sha256: str


@dataclass(frozen=True)
class ChromeLock:
    """Strict, reproducible Chrome build-input contract."""

    schema_version: int
    source: ChromeSourceLock
    package: ChromePackageLock
    executable: ChromeExecutableLock


@dataclass(frozen=True)
class ChromeLockUpdate:
    """Result of resolving and, if necessary, atomically updating the lock."""

    lock: ChromeLock
    changed: bool


def _exact_object(
    value: object,
    *,
    label: str,
    keys: frozenset[str],
) -> dict[str, object]:
    if type(value) is not dict:
        raise ChromeReleaseError(f"{label} must be a JSON object")
    object_value = cast("dict[str, object]", value)
    actual = frozenset(object_value)
    if actual != keys:
        missing = ", ".join(sorted(keys - actual)) or "none"
        unexpected = ", ".join(sorted(actual - keys)) or "none"
        raise ChromeReleaseError(
            f"{label} keys were invalid (missing: {missing}; unexpected: {unexpected})"
        )
    return object_value


def _required_string(value: object, *, label: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ChromeReleaseError(f"{label} must be a non-empty trimmed string")
    return value


def _sha256(value: object, *, label: str) -> str:
    digest = _required_string(value, label=label)
    if _SHA256_PATTERN.fullmatch(digest) is None:
        raise ChromeReleaseError(f"{label} must be a lowercase SHA-256 digest")
    return digest


def _package_lock(value: object, *, label: str) -> ChromePackageLock:
    fields = _exact_object(
        value,
        label=label,
        keys=frozenset(
            {
                "name",
                "architecture",
                "version",
                "product_version",
                "filename",
                "sha256",
            }
        ),
    )
    name = _required_string(fields["name"], label=f"{label}.name")
    architecture = _required_string(fields["architecture"], label=f"{label}.architecture")
    version = _required_string(fields["version"], label=f"{label}.version")
    product_version = _required_string(fields["product_version"], label=f"{label}.product_version")
    filename = _required_string(fields["filename"], label=f"{label}.filename")
    digest = _sha256(fields["sha256"], label=f"{label}.sha256")
    if name != _CHROME_PACKAGE_NAME:
        raise ChromeReleaseError(f"{label}.name must be {_CHROME_PACKAGE_NAME}")
    if architecture != _CHROME_ARCHITECTURE:
        raise ChromeReleaseError(f"{label}.architecture must be {_CHROME_ARCHITECTURE}")
    version_match = _CHROME_VERSION_PATTERN.fullmatch(version)
    if version_match is None:
        raise ChromeReleaseError(f"{label}.version was not a supported Chrome deb version")
    if product_version != version_match.group("product"):
        raise ChromeReleaseError(f"{label}.product_version did not match its package version")
    expected_filename = (
        f"pool/main/g/google-chrome-stable/google-chrome-stable_{version}_{architecture}.deb"
    )
    if filename != expected_filename:
        raise ChromeReleaseError(f"{label}.filename did not match its package version")
    return ChromePackageLock(
        name=name,
        architecture=architecture,
        version=version,
        product_version=product_version,
        filename=filename,
        sha256=digest,
    )


def _without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ChromeReleaseError(f"Chrome lock contained duplicate key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise ChromeReleaseError(f"Chrome lock contained invalid JSON constant: {value}")


def load_chrome_lock(path: Path = CHROME_LOCK_PATH) -> ChromeLock:
    """Load and strictly validate one authoritative Chrome lock file."""
    if path.is_symlink() or not path.is_file():
        raise ChromeReleaseError(f"Chrome lock must be a regular file: {path}")
    try:
        source_text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise ChromeReleaseError(f"Could not read Chrome lock: {path}") from exc
    if "\r" in source_text or not source_text.endswith("\n"):
        raise ChromeReleaseError("Chrome lock must use LF lines and end with a newline")
    try:
        raw = json.loads(
            source_text,
            object_pairs_hook=_without_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except json.JSONDecodeError as exc:
        raise ChromeReleaseError(f"Chrome lock was not valid JSON: {path}") from exc
    root = _exact_object(
        raw,
        label="Chrome lock",
        keys=frozenset({"schema_version", "source", "package", "executable"}),
    )
    schema_version = root["schema_version"]
    if type(schema_version) is not int or schema_version != _LOCK_SCHEMA_VERSION:
        raise ChromeReleaseError(f"Chrome lock schema_version must be {_LOCK_SCHEMA_VERSION}")
    source = _exact_object(
        root["source"],
        label="Chrome lock source",
        keys=frozenset({"repository", "suite", "component"}),
    )
    repository = _required_string(source["repository"], label="Chrome lock source.repository")
    suite = _required_string(source["suite"], label="Chrome lock source.suite")
    component = _required_string(source["component"], label="Chrome lock source.component")
    if repository != GOOGLE_REPOSITORY_URL:
        raise ChromeReleaseError(f"Chrome lock source.repository must be {GOOGLE_REPOSITORY_URL}")
    if suite != "stable":
        raise ChromeReleaseError("Chrome lock source.suite must be stable")
    if component != "main":
        raise ChromeReleaseError("Chrome lock source.component must be main")
    executable = _exact_object(
        root["executable"],
        label="Chrome lock executable",
        keys=frozenset({"path", "sha256"}),
    )
    executable_path = _required_string(executable["path"], label="Chrome lock executable.path")
    if executable_path != _CHROME_EXECUTABLE_PATH:
        raise ChromeReleaseError(f"Chrome lock executable.path must be {_CHROME_EXECUTABLE_PATH}")
    return ChromeLock(
        schema_version=schema_version,
        source=ChromeSourceLock(
            repository=repository,
            suite=suite,
            component=component,
        ),
        package=_package_lock(root["package"], label="Chrome lock package"),
        executable=ChromeExecutableLock(
            path=executable_path,
            sha256=_sha256(executable["sha256"], label="Chrome lock executable.sha256"),
        ),
    )


def _lock_payload(lock: ChromeLock) -> dict[str, object]:
    return {
        "schema_version": lock.schema_version,
        "source": {
            "repository": lock.source.repository,
            "suite": lock.source.suite,
            "component": lock.source.component,
        },
        "package": {
            "name": lock.package.name,
            "architecture": lock.package.architecture,
            "version": lock.package.version,
            "product_version": lock.package.product_version,
            "filename": lock.package.filename,
            "sha256": lock.package.sha256,
        },
        "executable": {
            "path": lock.executable.path,
            "sha256": lock.executable.sha256,
        },
    }


def _render_lock(lock: ChromeLock) -> bytes:
    return (json.dumps(_lock_payload(lock), indent=2) + "\n").encode("utf-8")


CHROME_LOCK: Final = load_chrome_lock()
PINNED_CHROME_VERSION: Final = CHROME_LOCK.package.version
PINNED_CHROME_PRODUCT_VERSION: Final = CHROME_LOCK.package.product_version
PINNED_CHROME_FILENAME: Final = CHROME_LOCK.package.filename
PINNED_CHROME_SHA256: Final = CHROME_LOCK.package.sha256
PINNED_CHROME_EXECUTABLE_SHA256: Final = CHROME_LOCK.executable.sha256


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _download(url: str, max_bytes: int) -> bytes:
    """Download one fixed Google artifact URL with an explicit size bound."""
    with urlopen(url, timeout=_DOWNLOAD_TIMEOUT_SECONDS) as response:  # noqa: S310
        body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise ChromeReleaseError(f"Chrome download exceeded {max_bytes} bytes")
    if not body:
        raise ChromeReleaseError("Chrome download response was empty")
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


def _stable_package(packages: bytes) -> ChromePackageLock:
    """Return the one stable amd64 Chrome package from authenticated metadata."""
    matches = [
        stanza
        for stanza in _package_stanzas(packages)
        if stanza.get("Package") == _CHROME_PACKAGE_NAME
        and stanza.get("Architecture") == _CHROME_ARCHITECTURE
    ]
    if len(matches) != 1:
        raise ChromeReleaseError(
            "Google Packages metadata did not contain one amd64 stable Chrome package"
        )
    package_fields = matches[0]
    version = package_fields.get("Version")
    product_version = ""
    if version is not None:
        version_match = _CHROME_VERSION_PATTERN.fullmatch(version)
        if version_match is not None:
            product_version = version_match.group("product")
    return _package_lock(
        {
            "name": package_fields.get("Package"),
            "architecture": package_fields.get("Architecture"),
            "version": version,
            "product_version": product_version,
            "filename": package_fields.get("Filename"),
            "sha256": package_fields.get("SHA256"),
        },
        label="Google stable Chrome package",
    )


def _version_key(version: str) -> tuple[int, int, int, int]:
    """Return the numeric Chrome product version from a validated deb version."""
    match = _CHROME_VERSION_PATTERN.fullmatch(version)
    if match is None:  # pragma: no cover - every caller holds a validated lock
        raise ChromeReleaseError("Chrome package version was not valid")
    components = tuple(int(component) for component in match.group("product").split("."))
    if len(components) != 4:  # pragma: no cover - enforced by the pattern
        raise ChromeReleaseError("Chrome product version did not have four components")
    return (components[0], components[1], components[2], components[3])


def _authenticated_stable_package(
    *,
    fetcher: Fetcher,
    runner: CommandRunner,
    clock: Clock,
) -> ChromePackageLock:
    """Resolve stable Chrome only through Google's pinned signing identity."""
    signing_key = fetcher(GOOGLE_SIGNING_KEY_URL, _MAX_KEY_BYTES)
    inrelease = fetcher(GOOGLE_INRELEASE_URL, _MAX_INRELEASE_BYTES)
    with tempfile.TemporaryDirectory(prefix="chrome-release-") as raw_directory:
        verified_inrelease = _verify_signature(
            signing_key=signing_key,
            inrelease=inrelease,
            directory=Path(raw_directory),
            runner=runner,
        )
    _require_fresh_inrelease(verified_inrelease, now=clock())
    packages_gzip = fetcher(GOOGLE_PACKAGES_URL, _MAX_PACKAGES_BYTES)
    packages = _verify_packages_artifact(verified_inrelease, packages_gzip)
    return _stable_package(packages)


def _require_current_pin(package: ChromePackageLock) -> None:
    observed = (
        package.version,
        package.filename,
        package.sha256,
    )
    expected = (
        PINNED_CHROME_VERSION,
        PINNED_CHROME_FILENAME,
        PINNED_CHROME_SHA256,
    )
    if observed != expected:
        raise ChromeReleaseError(
            "Pinned Chrome is no longer the signed stable Linux release: "
            f"expected {PINNED_CHROME_VERSION}, observed {package.version}"
        )


def _ar_members(archive: bytes) -> dict[str, bytes]:
    """Parse the regular ar members used by a Debian package."""
    if not archive.startswith(_AR_MAGIC):
        raise ChromeReleaseError("Chrome package was not a Debian ar archive")
    members: dict[str, bytes] = {}
    offset = len(_AR_MAGIC)
    while offset < len(archive):
        if len(archive) - offset < _AR_HEADER_SIZE:
            raise ChromeReleaseError("Chrome Debian archive had a truncated member header")
        header = archive[offset : offset + _AR_HEADER_SIZE]
        offset += _AR_HEADER_SIZE
        if header[58:60] != _AR_FILE_MAGIC:
            raise ChromeReleaseError("Chrome Debian archive had an invalid member header")
        try:
            raw_name = header[:16].decode("ascii").rstrip()
            size = int(header[48:58].decode("ascii").strip())
        except (UnicodeDecodeError, ValueError) as exc:
            raise ChromeReleaseError("Chrome Debian archive had invalid member metadata") from exc
        name = raw_name.removesuffix("/")
        if not name or raw_name.startswith("/") or name in members:
            raise ChromeReleaseError("Chrome Debian archive had invalid member names")
        member_end = offset + size
        if size < 0 or member_end > len(archive):
            raise ChromeReleaseError("Chrome Debian archive had a truncated member")
        members[name] = archive[offset:member_end]
        offset = member_end + (size % 2)
        if offset > len(archive):
            raise ChromeReleaseError("Chrome Debian archive had invalid padding")
    return members


def _chrome_executable_sha256(deb: bytes) -> str:
    """Hash Chrome's executable from a deb without installing or extracting it."""
    members = _ar_members(deb)
    if members.get("debian-binary") != b"2.0\n":
        raise ChromeReleaseError("Chrome package had an invalid Debian format version")
    data_names = _DATA_ARCHIVE_NAMES.intersection(members)
    if len(data_names) != 1:
        raise ChromeReleaseError(
            "Chrome package did not contain exactly one supported data archive"
        )
    data_archive = members[next(iter(data_names))]
    target = _CHROME_EXECUTABLE_PATH.removeprefix("/")
    try:
        with tarfile.open(fileobj=io.BytesIO(data_archive), mode="r:*") as archive:
            matches = [
                member
                for member in archive.getmembers()
                if member.name.removeprefix("./") == target
            ]
            if len(matches) != 1 or not matches[0].isfile():
                raise ChromeReleaseError(
                    f"Chrome package did not contain one regular {_CHROME_EXECUTABLE_PATH}"
                )
            member = matches[0]
            if member.size < 1 or member.size > _MAX_EXECUTABLE_BYTES:
                raise ChromeReleaseError("Chrome executable had an invalid size")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise ChromeReleaseError("Chrome executable could not be read")
            executable = extracted.read(_MAX_EXECUTABLE_BYTES + 1)
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise ChromeReleaseError("Chrome package data archive was invalid") from exc
    if len(executable) != member.size:
        raise ChromeReleaseError("Chrome executable size did not match its archive entry")
    return hashlib.sha256(executable).hexdigest()


def resolve_current_chrome_lock(
    *,
    fetcher: Fetcher = _download,
    runner: CommandRunner = _run,
    clock: Clock = _utc_now,
) -> ChromeLock:
    """Authenticate, download, and hash the current stable Chrome release."""
    package = _authenticated_stable_package(
        fetcher=fetcher,
        runner=runner,
        clock=clock,
    )
    deb = fetcher(f"{GOOGLE_REPOSITORY_URL}/{package.filename}", _MAX_DEB_BYTES)
    actual_package_sha256 = hashlib.sha256(deb).hexdigest()
    if actual_package_sha256 != package.sha256:
        raise ChromeReleaseError("Chrome package checksum did not match signed Packages metadata")
    return ChromeLock(
        schema_version=_LOCK_SCHEMA_VERSION,
        source=ChromeSourceLock(
            repository=GOOGLE_REPOSITORY_URL,
            suite="stable",
            component="main",
        ),
        package=package,
        executable=ChromeExecutableLock(
            path=_CHROME_EXECUTABLE_PATH,
            sha256=_chrome_executable_sha256(deb),
        ),
    )


def _atomic_write_lock(path: Path, lock: ChromeLock) -> None:
    """Replace one existing lock using a same-directory temporary file."""
    if path.name != CHROME_LOCK_PATH.name:
        raise ChromeReleaseError("Chrome updater may write only chrome-lock.json")
    if path.is_symlink() or not path.is_file():
        raise ChromeReleaseError(f"Chrome lock must be a regular file: {path}")
    mode = stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as temporary:
            os.fchmod(temporary.fileno(), mode)
            temporary.write(_render_lock(lock))
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def update_chrome_lock(
    lock_path: Path = CHROME_LOCK_PATH,
    *,
    fetcher: Fetcher = _download,
    runner: CommandRunner = _run,
    clock: Clock = _utc_now,
) -> ChromeLockUpdate:
    """Resolve stable Chrome and atomically update the lock only on change."""
    current = load_chrome_lock(lock_path)
    resolved = resolve_current_chrome_lock(
        fetcher=fetcher,
        runner=runner,
        clock=clock,
    )
    if _version_key(resolved.package.version) < _version_key(current.package.version):
        raise ChromeReleaseError(
            "Refusing to replace the Chrome lock with an older signed stable release: "
            f"current {current.package.version}, observed {resolved.package.version}"
        )
    if current == resolved:
        return ChromeLockUpdate(lock=resolved, changed=False)
    _atomic_write_lock(lock_path, resolved)
    return ChromeLockUpdate(lock=resolved, changed=True)


def verify_pinned_chrome_release(
    *,
    fetcher: Fetcher = _download,
    runner: CommandRunner = _run,
    clock: Clock = _utc_now,
) -> None:
    """Require the lock's Chrome pin to equal Google's signed stable metadata."""
    package = _authenticated_stable_package(
        fetcher=fetcher,
        runner=runner,
        clock=clock,
    )
    _require_current_pin(package)


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
