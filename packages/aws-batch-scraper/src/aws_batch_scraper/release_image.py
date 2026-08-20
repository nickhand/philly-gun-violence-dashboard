"""Fail-closed release checks for immutable scraper container images."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

FULL_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
IMAGE_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
AWS_ACCOUNT_ID_PATTERN = re.compile(r"^[0-9]{12}$")
ECR_REPOSITORY_PATTERN = re.compile(r"^(?=.{2,256}$)[a-z0-9]+(?:[._/-][a-z0-9]+)*$")
AWS_REGION_PATTERN = re.compile(r"^[a-z]{2}(?:-[a-z0-9]+)+-[0-9]+$")
REVISION_LABEL = "org.opencontainers.image.revision"
GRYPE_VERSION = "0.116.1"
GRYPE_IMAGE = (
    "docker.io/anchore/grype@"
    "sha256:1e71065c0a4cff3e6bd3b8add525ffac4343eb4971694eb90a31cf6d4d3e85db"
)
GRYPE_DB_SCHEMA_MAJOR = 6
GRYPE_DB_MAX_AGE = timedelta(hours=24)
# Provider captures are build inputs, so their freshness is anchored to the
# checksum-pinned DB build. Together these bounds cap provider age at 48 hours.
GRYPE_PROVIDER_MAX_AGE_AT_BUILD = timedelta(hours=24)
SYFT_VERSION = "1.50.0"
SYFT_SCHEMA_VERSION = "16.1.10"
SYFT_IMAGE = (
    "docker.io/anchore/syft@sha256:1288ea4c8b38767b4e620c1e312c8cb26b6e887a99b4f07ab6cd19fc6f225026"
)
LOCAL_SCAN_PLATFORM = "linux/amd64"
LOCAL_SCAN_CLOCK_SKEW = timedelta(minutes=5)
LOCAL_SCAN_MAX_REPORT_BYTES = 512 * 1024 * 1024
LOCAL_COMMAND_TIMEOUT_SECONDS = 30 * 60
REMOTE_SCAN_MAX_AGE = timedelta(hours=1)
REMOTE_VULNERABILITY_SOURCE_MAX_AGE = timedelta(hours=24)
SCAN_POLL_INTERVAL_SECONDS = 10.0
SCAN_MAX_ATTEMPTS = 180
_SCAN_PENDING_STATUSES = frozenset({"IN_PROGRESS", "PENDING"})
_SCAN_SUCCESS_STATUSES = frozenset({"COMPLETE"})
_SCAN_SEVERITIES = frozenset({"UNDEFINED", "INFORMATIONAL", "LOW", "MEDIUM", "HIGH", "CRITICAL"})
_AWS_CLI_ERROR_PATTERN = re.compile(
    r"An error occurred \((?P<code>[A-Za-z][A-Za-z0-9]+)\) when calling the "
    r"[A-Za-z][A-Za-z0-9]+ operation:"
)
_GRYPE_DB_SCHEMA_PATTERN = re.compile(r"^v(?P<major>[0-9]+)\.[0-9]+\.[0-9]+$")
_PACKAGE_REQUIREMENT_PATTERN = re.compile(
    r"^(?P<type>[a-z0-9][a-z0-9+._-]*):"
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9+._-]*)="
    r"(?P<version>[^\s,=]+)$"
)
_CHROME_DEB_VERSION_PATTERN = re.compile(r"^(?P<browser>[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)-1$")
_CHROME_EXECUTABLE = "/opt/google/chrome/chrome"
_CHROME_SANDBOX = "/opt/google/chrome/chrome-sandbox"
_PLAYWRIGHT_NODE_SUFFIX = "/site-packages/playwright/driver/node"
_CHROME_CPE_CONTROL = "cpe:2.3:a:google:chrome:151.0.7922.34:*:*:*:*:*:*:*"
_GRYPE_SEVERITIES = frozenset({"Unknown", "Negligible", "Low", "Medium", "High", "Critical"})
_IMAGE_MANIFEST_MEDIA_TYPES = frozenset(
    {
        "application/vnd.docker.distribution.manifest.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
    }
)
_IMAGE_CONFIG_MEDIA_TYPES = frozenset(
    {
        "application/vnd.docker.container.image.v1+json",
        "application/vnd.oci.image.config.v1+json",
    }
)

CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
Sleeper = Callable[[float], None]
Clock = Callable[[], datetime]


class ReleaseIntegrityError(RuntimeError):
    """Raised when an image cannot be proven safe to publish."""


def _current_utc_time() -> datetime:
    return datetime.now(timezone.utc)


def _clock_time(clock: Clock) -> datetime:
    timestamp = clock()
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("Local scan clock must return a timezone-aware datetime")
    return timestamp.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class PackageRequirement:
    """One exact package identity that must be present in the image SBOM."""

    package_type: str
    name: str
    version: str

    @classmethod
    def parse(cls, value: str) -> PackageRequirement:
        """Parse ``type:name=version`` without accepting ambiguous text."""
        match = _PACKAGE_REQUIREMENT_PATTERN.fullmatch(value)
        if match is None:
            raise ValueError("Required SBOM packages must use exact type:name=version entries")
        return cls(
            package_type=match.group("type"),
            name=match.group("name"),
            version=match.group("version"),
        )

    @property
    def canonical(self) -> str:
        """Return the stable serialized requirement."""
        return f"{self.package_type}:{self.name}={self.version}"


@dataclass(frozen=True, slots=True)
class ReleaseTarget:
    """One exact ECR repository and immutable commit tag."""

    account_id: str
    repository: str
    region: str
    tag: str
    profile: str | None = None

    def __post_init__(self) -> None:
        if AWS_ACCOUNT_ID_PATTERN.fullmatch(self.account_id) is None:
            raise ValueError("AWS account id must contain exactly 12 digits")
        if ECR_REPOSITORY_PATTERN.fullmatch(self.repository) is None:
            raise ValueError("ECR repository name is invalid")
        if AWS_REGION_PATTERN.fullmatch(self.region) is None:
            raise ValueError("AWS region is invalid")
        if FULL_COMMIT_PATTERN.fullmatch(self.tag) is None:
            raise ValueError("SCRAPER_IMAGE_TAG must be a full lowercase 40-character commit SHA")
        if self.profile is not None and (
            not self.profile.strip() or any(character.isspace() for character in self.profile)
        ):
            raise ValueError("AWS profile must be a non-blank token when provided")

    def aws_command(self, *arguments: str) -> list[str]:
        """Build an AWS CLI command without interpolating shell text."""
        command = ["aws"]
        if self.profile is not None:
            command.extend(("--profile", self.profile))
        command.extend(("--region", self.region, *arguments))
        return command

    @property
    def repository_uri(self) -> str:
        """Return the only ECR repository URI this release may target."""
        return f"{self.account_id}.dkr.ecr.{self.region}.amazonaws.com/{self.repository}"


def _default_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=LOCAL_COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ReleaseIntegrityError(
            f"Command exceeded the {LOCAL_COMMAND_TIMEOUT_SECONDS}-second safety limit"
        ) from exc


def _checked_output(
    runner: CommandRunner,
    command: Sequence[str],
    *,
    label: str,
) -> str:
    result = runner(command)
    if result.returncode != 0:
        raise ReleaseIntegrityError(f"{label} command failed")
    return result.stdout


def _json_output(
    runner: CommandRunner,
    command: Sequence[str],
    *,
    label: str,
) -> dict[str, Any]:
    output = _checked_output(runner, command, label=label)
    return _parse_json_object(output, label=label)


def _parse_json_object(output: str, *, label: str) -> dict[str, Any]:
    """Parse one command response as a JSON object or fail closed."""
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ReleaseIntegrityError(f"{label} returned malformed JSON") from exc
    if not isinstance(value, dict):
        raise ReleaseIntegrityError(f"{label} did not return a JSON object")
    return value


def validate_release_source(
    tag: str,
    *,
    runner: CommandRunner = _default_runner,
) -> str:
    """Require the exact full HEAD commit and a clean tracked/untracked tree."""
    head = _checked_output(
        runner,
        ["git", "rev-parse", "--verify", "HEAD"],
        label="Git revision inspection",
    ).strip()
    if FULL_COMMIT_PATTERN.fullmatch(head) is None:
        raise ReleaseIntegrityError("Git HEAD is not a full lowercase 40-character commit SHA")
    if tag != head:
        raise ReleaseIntegrityError("SCRAPER_IMAGE_TAG must exactly equal the full Git HEAD SHA")

    status = _checked_output(
        runner,
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        label="Git worktree inspection",
    )
    if status.strip():
        raise ReleaseIntegrityError(
            "Scraper release images must be built from a completely clean checkout"
        )
    return head


def require_remote_tag_absent(
    target: ReleaseTarget,
    *,
    runner: CommandRunner = _default_runner,
) -> None:
    """Reject an ECR tag that already names any remote image."""
    payload = _json_output(
        runner,
        target.aws_command(
            "ecr",
            "list-images",
            "--registry-id",
            target.account_id,
            "--repository-name",
            target.repository,
            "--filter",
            "tagStatus=TAGGED",
            "--output",
            "json",
        ),
        label="ECR tag inspection",
    )
    image_ids = payload.get("imageIds")
    if not isinstance(image_ids, list):
        raise ReleaseIntegrityError("ECR tag inspection omitted imageIds")
    for image_id in image_ids:
        if not isinstance(image_id, dict):
            raise ReleaseIntegrityError("ECR tag inspection returned an invalid image ID")
        remote_tag = image_id.get("imageTag")
        if remote_tag is not None and not isinstance(remote_tag, str):
            raise ReleaseIntegrityError("ECR tag inspection returned a non-string tag")
        if remote_tag == target.tag:
            raise ReleaseIntegrityError(f"ECR tag {target.tag} already exists and is immutable")


def require_immutable_repository(
    target: ReleaseTarget,
    *,
    runner: CommandRunner = _default_runner,
) -> None:
    """Require ECR itself to close the absent-tag check/push race."""
    payload = _json_output(
        runner,
        target.aws_command(
            "ecr",
            "describe-repositories",
            "--registry-id",
            target.account_id,
            "--repository-names",
            target.repository,
            "--output",
            "json",
        ),
        label="ECR repository policy inspection",
    )
    repositories = payload.get("repositories")
    if (
        not isinstance(repositories, list)
        or len(repositories) != 1
        or not isinstance(repositories[0], dict)
    ):
        raise ReleaseIntegrityError("ECR policy inspection did not return one repository")
    repository = repositories[0]
    if repository.get("registryId") != target.account_id:
        raise ReleaseIntegrityError("ECR policy inspection returned the wrong registry account")
    if repository.get("repositoryName") != target.repository:
        raise ReleaseIntegrityError("ECR policy inspection returned the wrong repository")
    if repository.get("repositoryUri") != target.repository_uri:
        raise ReleaseIntegrityError("ECR policy inspection returned the wrong repository URI")
    if repository.get("imageTagMutability") != "IMMUTABLE":
        raise ReleaseIntegrityError(
            "ECR repository must enforce exact IMMUTABLE tag mutability before release"
        )
    scanning = repository.get("imageScanningConfiguration")
    if not isinstance(scanning, dict) or scanning.get("scanOnPush") is not True:
        raise ReleaseIntegrityError("ECR repository must enable scan-on-push before release")


def preflight_release(
    target: ReleaseTarget,
    *,
    runner: CommandRunner = _default_runner,
) -> None:
    """Validate source identity and remote tag absence before build or push."""
    validate_release_source(target.tag, runner=runner)
    require_immutable_repository(target, runner=runner)
    require_remote_tag_absent(target, runner=runner)


def verify_local_image(
    image: str,
    tag: str,
    *,
    runner: CommandRunner = _default_runner,
) -> None:
    """Require the locally built image to carry the expected commit label."""
    if not image.strip() or any(character.isspace() for character in image):
        raise ValueError("Local image name must be a non-blank token")
    if FULL_COMMIT_PATTERN.fullmatch(tag) is None:
        raise ValueError("Image revision must be a full lowercase 40-character commit SHA")
    output = _checked_output(
        runner,
        ["docker", "image", "inspect", "--format", "{{json .Config.Labels}}", image],
        label="Local image inspection",
    )
    try:
        labels = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ReleaseIntegrityError("Local image labels were malformed") from exc
    if not isinstance(labels, dict) or labels.get(REVISION_LABEL) != tag:
        raise ReleaseIntegrityError(f"Local image must carry {REVISION_LABEL}={tag}")


def parse_package_requirements(value: str) -> tuple[PackageRequirement, ...]:
    """Parse a comma-delimited set of unique, exact SBOM requirements."""
    raw_requirements = value.split(",") if value else []
    if not raw_requirements or any(not item for item in raw_requirements):
        raise ValueError("At least one exact required SBOM package must be configured")
    requirements = tuple(PackageRequirement.parse(item) for item in raw_requirements)
    identities = [(item.package_type, item.name) for item in requirements]
    if len(set(identities)) != len(identities):
        raise ValueError("Required SBOM package identities must be unique")

    playwright = next(
        (
            item
            for item in requirements
            if item.package_type == "python" and item.name == "playwright"
        ),
        None,
    )
    if playwright is not None:
        required_browser_identities = {
            ("deb", "google-chrome-stable"),
            ("binary", "node"),
        }
        if not required_browser_identities.issubset(identities):
            raise ValueError(
                "Playwright images must pin deb:google-chrome-stable and binary:node "
                "in the SBOM contract"
            )
    return requirements


def _scanner_run_prefix(
    image: str,
    *,
    network_none: bool,
    mounts: Sequence[tuple[Path, str, bool]] = (),
    environment: Sequence[tuple[str, str]] = (),
    tmpfs_size: str | None = None,
) -> list[str]:
    """Build a non-root, capability-free scanner-container command prefix."""
    command = ["docker", "run", "--rm"]
    if network_none:
        command.extend(("--network", "none"))
    command.extend(
        (
            "--read-only",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
        )
    )
    if tmpfs_size is not None:
        command.extend(
            (
                "--tmpfs",
                f"/tmp:rw,nosuid,nodev,noexec,mode=1777,size={tmpfs_size}",
            )
        )
    for source, destination, readonly in mounts:
        mount = f"type=bind,src={source.resolve()},dst={destination}"
        if readonly:
            mount = f"{mount},readonly"
        command.extend(("--mount", mount))
    for name, value in environment:
        command.extend(("--env", f"{name}={value}"))
    return [*command, image]


def _scanner_version(
    image: str,
    *,
    runner: CommandRunner,
    label: str,
) -> str:
    command = _scanner_run_prefix(image, network_none=True)
    output = _checked_output(runner, [*command, "version"], label=label)
    versions = [
        line.partition(":")[2].strip()
        for line in output.splitlines()
        if line.startswith("Version:")
    ]
    if len(versions) != 1 or not versions[0]:
        raise ReleaseIntegrityError(f"{label} did not report one version")
    return versions[0]


def _inspect_local_image(
    image: str,
    *,
    runner: CommandRunner,
) -> dict[str, str]:
    if not image.strip() or any(character.isspace() for character in image):
        raise ValueError("Local image name must be a non-blank token")
    output = _checked_output(
        runner,
        ["docker", "image", "inspect", image],
        label="Local scan image inspection",
    )
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ReleaseIntegrityError("Local scan image inspection returned malformed JSON") from exc
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise ReleaseIntegrityError("Local scan image inspection did not return one image")
    record = payload[0]
    image_id = record.get("Id")
    operating_system = record.get("Os")
    architecture = record.get("Architecture")
    if not isinstance(image_id, str) or IMAGE_DIGEST_PATTERN.fullmatch(image_id) is None:
        raise ReleaseIntegrityError("Local scan image inspection returned an invalid image ID")
    if not isinstance(operating_system, str) or not operating_system:
        raise ReleaseIntegrityError("Local scan image inspection omitted the operating system")
    if not isinstance(architecture, str) or not architecture:
        raise ReleaseIntegrityError("Local scan image inspection omitted the architecture")
    return {
        "image_id": image_id,
        "platform": f"{operating_system}/{architecture}",
    }


def _export_final_filesystem(
    image_id: str,
    destination: Path,
    *,
    runner: CommandRunner,
) -> None:
    """Export one stopped container's merged root filesystem and remove it."""
    container_id = _checked_output(
        runner,
        [
            "docker",
            "container",
            "create",
            "--network",
            "none",
            "--entrypoint",
            "/bin/true",
            image_id,
        ],
        label="Final filesystem container creation",
    ).strip()
    if re.fullmatch(r"[0-9a-f]{64}", container_id) is None:
        raise ReleaseIntegrityError("Docker returned an invalid filesystem-audit container ID")
    export_error: ReleaseIntegrityError | None = None
    try:
        _checked_output(
            runner,
            [
                "docker",
                "container",
                "export",
                "--output",
                str(destination),
                container_id,
            ],
            label="Final filesystem export",
        )
    except ReleaseIntegrityError as exc:
        export_error = exc
    cleanup = runner(["docker", "container", "rm", "--force", "--volumes", container_id])
    if cleanup.returncode != 0:
        raise ReleaseIntegrityError(
            "Could not remove the stopped filesystem-audit container"
        ) from export_error
    if export_error is not None:
        raise export_error
    if destination.is_symlink() or not destination.is_file() or destination.stat().st_size < 1:
        raise ReleaseIntegrityError("Docker did not export a valid final filesystem archive")


def validate_final_filesystem_archive(
    path: Path,
    *,
    image_id: str,
    forbid_chrome_sandbox: bool,
    forbid_setuid_setgid_files: bool,
) -> dict[str, Any]:
    """Audit merged runtime file modes without executing any image binary."""
    members = 0
    regular_files = 0
    chrome_sandbox_present = False
    privileged_paths: list[str] = []
    try:
        with tarfile.open(path, mode="r:*") as archive:
            for member in archive:
                members += 1
                normalized = "/" + member.name.removeprefix("./").lstrip("/")
                if normalized == _CHROME_SANDBOX:
                    chrome_sandbox_present = True
                if member.isfile():
                    regular_files += 1
                    if member.mode & 0o6000:
                        privileged_paths.append(normalized)
    except (OSError, tarfile.TarError) as exc:
        raise ReleaseIntegrityError("Final filesystem export was not a valid tar archive") from exc
    if members < 1 or regular_files < 1:
        raise ReleaseIntegrityError("Final filesystem export did not contain regular files")
    if forbid_chrome_sandbox and chrome_sandbox_present:
        raise ReleaseIntegrityError("Final filesystem retained the forbidden Chrome sandbox helper")
    if forbid_setuid_setgid_files and privileged_paths:
        rendered = ", ".join(sorted(privileged_paths)[:10])
        suffix = "" if len(privileged_paths) <= 10 else f" (+{len(privileged_paths) - 10} more)"
        raise ReleaseIntegrityError(
            f"Final filesystem retained setuid/setgid files: {rendered}{suffix}"
        )
    return {
        "schema_version": 1,
        "image_id": image_id,
        "archive_sha256": _sha256_file(path),
        "members": members,
        "regular_files": regular_files,
        "chrome_sandbox_present": chrome_sandbox_present,
        "setuid_setgid_files": len(privileged_paths),
        "chrome_sandbox_policy": "forbidden" if forbid_chrome_sandbox else "permitted",
        "setuid_setgid_policy": "forbidden" if forbid_setuid_setgid_files else "permitted",
    }


def _load_json_file(path: Path, *, label: str) -> dict[str, Any]:
    """Read a bounded regular JSON file and require an object at its root."""
    if path.is_symlink() or not path.is_file():
        raise ReleaseIntegrityError(f"{label} was not written as a regular file")
    size = path.stat().st_size
    if size < 1 or size > LOCAL_SCAN_MAX_REPORT_BYTES:
        raise ReleaseIntegrityError(f"{label} has an invalid size")
    try:
        value = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseIntegrityError(f"{label} contained invalid JSON") from exc
    if not isinstance(value, dict):
        raise ReleaseIntegrityError(f"{label} did not contain a JSON object")
    return value


def _aware_timestamp(value: object, *, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ReleaseIntegrityError(f"{label} timestamp was missing")
    try:
        timestamp = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReleaseIntegrityError(f"{label} timestamp was invalid") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ReleaseIntegrityError(f"{label} timestamp was not timezone-aware")
    return timestamp.astimezone(timezone.utc)


def _require_fresh_timestamp(
    value: object,
    *,
    label: str,
    now: datetime,
    max_age: timedelta,
) -> datetime:
    timestamp = _aware_timestamp(value, label=label)
    if timestamp > now + LOCAL_SCAN_CLOCK_SKEW:
        raise ReleaseIntegrityError(f"{label} timestamp was in the future")
    if now - timestamp > max_age:
        raise ReleaseIntegrityError(f"{label} timestamp was stale")
    return timestamp


def _artifact_versions(
    artifacts: list[object],
    requirement: PackageRequirement,
) -> tuple[set[str], list[dict[str, Any]]]:
    matches: list[dict[str, Any]] = []
    versions: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ReleaseIntegrityError("Syft SBOM contained a malformed artifact")
        if (
            artifact.get("type") == requirement.package_type
            and artifact.get("name") == requirement.name
        ):
            version = artifact.get("version")
            if not isinstance(version, str) or not version:
                raise ReleaseIntegrityError(
                    "Syft SBOM omitted the version for "
                    f"{requirement.package_type}:{requirement.name}"
                )
            versions.add(version)
            matches.append(artifact)
    return versions, matches


def _require_package_evidence(
    requirement: PackageRequirement,
    artifacts: list[dict[str, Any]],
) -> None:
    for artifact in artifacts:
        purl = artifact.get("purl")
        locations = artifact.get("locations")
        if not isinstance(purl, str) or not purl:
            raise ReleaseIntegrityError(f"Syft SBOM omitted the PURL for {requirement.canonical}")
        if not isinstance(locations, list) or not locations:
            raise ReleaseIntegrityError(
                f"Syft SBOM omitted file evidence for {requirement.canonical}"
            )

    expected_cpe: str | None = None
    if requirement.package_type == "binary" and requirement.name == "node":
        expected_cpe = f"cpe:2.3:a:nodejs:node.js:{requirement.version}:"
    if expected_cpe is None:
        return
    if requirement.package_type == "binary" and requirement.name == "node":
        has_playwright_node = False
        for artifact in artifacts:
            locations = artifact.get("locations")
            if isinstance(locations, list) and any(
                isinstance(location, dict)
                and isinstance(location.get("path"), str)
                and location["path"].endswith(_PLAYWRIGHT_NODE_SUFFIX)
                for location in locations
            ):
                has_playwright_node = True
        if not has_playwright_node:
            raise ReleaseIntegrityError(
                "Syft SBOM did not bind Node to the Playwright driver executable"
            )
    for artifact in artifacts:
        cpes = artifact.get("cpes")
        if isinstance(cpes, list) and any(
            isinstance(record, dict)
            and isinstance(record.get("cpe"), str)
            and record["cpe"].startswith(expected_cpe)
            for record in cpes
        ):
            return
    raise ReleaseIntegrityError(
        f"Syft SBOM did not provide the vulnerability-matching CPE for {requirement.canonical}"
    )


def _require_chrome_file_evidence(
    files: Sequence[object],
    *,
    path: str,
    label: str,
    expected_sha256: str,
    expected_mode: int,
) -> str:
    records = [
        record
        for record in files
        if isinstance(record, dict)
        and isinstance(record.get("location"), dict)
        and record["location"].get("path") == path
    ]
    if len(records) != 1:
        raise ReleaseIntegrityError(f"Syft SBOM did not identify one exact Chrome {label}")
    record = records[0]
    metadata = record.get("metadata")
    if (
        not isinstance(metadata, dict)
        or metadata.get("type") != "RegularFile"
        or metadata.get("mode") != expected_mode
        or metadata.get("userID") != 0
        or metadata.get("groupID") != 0
    ):
        raise ReleaseIntegrityError(f"Chrome {label} evidence had unsafe type, mode, or ownership")
    executable_metadata = record.get("executable")
    if not isinstance(executable_metadata, dict) or executable_metadata.get("format") != "elf":
        raise ReleaseIntegrityError(f"Chrome {label} evidence was not an ELF binary")
    digests = record.get("digests")
    if not isinstance(digests, list):
        raise ReleaseIntegrityError(f"Chrome {label} evidence omitted file digests")
    sha256_values = [
        digest.get("value")
        for digest in digests
        if isinstance(digest, dict)
        and digest.get("algorithm") == "sha256"
        and isinstance(digest.get("value"), str)
    ]
    if len(sha256_values) != 1 or re.fullmatch(r"[0-9a-f]{64}", sha256_values[0]) is None:
        raise ReleaseIntegrityError(f"Chrome {label} evidence omitted one SHA-256 digest")
    observed_sha256 = f"sha256:{sha256_values[0]}"
    if observed_sha256 != expected_sha256:
        raise ReleaseIntegrityError(
            f"Chrome {label} bytes did not match the checksum-pinned deb payload"
        )
    return observed_sha256


def _require_no_setid_files(payload: dict[str, Any]) -> None:
    """Reject every final-image file carrying a setuid or setgid mode bit."""
    files = payload.get("files")
    if not isinstance(files, list):
        raise ReleaseIntegrityError("Syft SBOM omitted final-image file evidence")
    violations: list[str] = []
    for record in files:
        if not isinstance(record, dict):
            continue
        metadata = record.get("metadata")
        if not isinstance(metadata, dict) or not isinstance((mode := metadata.get("mode")), int):
            continue
        # Syft serializes mode as the octal digits in a decimal integer. The
        # leading digit therefore carries sticky/setgid/setuid (1/2/4).
        special_bits = mode // 10_000_000
        if special_bits & 0o6:
            location = record.get("location")
            path = location.get("path") if isinstance(location, dict) else None
            violations.append(path if isinstance(path, str) else "<unknown>")
    if violations:
        rendered = ", ".join(sorted(violations)[:10])
        suffix = "" if len(violations) <= 10 else f" (+{len(violations) - 10} more)"
        raise ReleaseIntegrityError(f"Final image retained setuid/setgid files: {rendered}{suffix}")


def _require_chrome_evidence(
    payload: dict[str, Any],
    requirement: PackageRequirement,
    artifacts: Sequence[dict[str, Any]],
    *,
    expected_executable_sha256: str,
    expected_sandbox_sha256: str | None,
    forbid_sandbox: bool,
) -> dict[str, Any]:
    """Bind the Chrome CPE scan to its exact deb package and runtime files."""
    if len(artifacts) != 1:
        raise ReleaseIntegrityError("Syft SBOM contained ambiguous Google Chrome packages")
    artifact = artifacts[0]
    purl = artifact.get("purl")
    if not isinstance(purl, str) or not purl.startswith(
        f"pkg:deb/ubuntu/google-chrome-stable@{requirement.version}?"
    ):
        raise ReleaseIntegrityError("Google Chrome SBOM package omitted its exact Ubuntu PURL")
    metadata = artifact.get("metadata")
    package_files = metadata.get("files") if isinstance(metadata, dict) else None
    owned_paths = (
        {
            record.get("path")
            for record in package_files
            if isinstance(record, dict) and isinstance(record.get("path"), str)
        }
        if isinstance(package_files, list)
        else set()
    )
    if not {_CHROME_EXECUTABLE, _CHROME_SANDBOX}.issubset(owned_paths):
        raise ReleaseIntegrityError("Google Chrome deb did not own its expected package files")

    version_match = _CHROME_DEB_VERSION_PATTERN.fullmatch(requirement.version)
    if version_match is None:
        raise ReleaseIntegrityError("Google Chrome deb version was not an exact upstream -1 build")
    files = payload.get("files")
    if not isinstance(files, list):
        raise ReleaseIntegrityError("Syft SBOM omitted file-level Chrome evidence")
    observed_executable_sha256 = _require_chrome_file_evidence(
        files,
        path=_CHROME_EXECUTABLE,
        label="executable",
        expected_sha256=expected_executable_sha256,
        expected_mode=755,
    )
    sandbox_records = [
        record
        for record in files
        if isinstance(record, dict)
        and isinstance(record.get("location"), dict)
        and record["location"].get("path") == _CHROME_SANDBOX
    ]
    if forbid_sandbox:
        if sandbox_records:
            raise ReleaseIntegrityError("Final image retained the forbidden Chrome sandbox helper")
        observed_sandbox_sha256: str | None = None
    else:
        if expected_sandbox_sha256 is None:
            raise ReleaseIntegrityError(
                "Google Chrome SBOM contract omitted its expected sandbox digest"
            )
        observed_sandbox_sha256 = _require_chrome_file_evidence(
            files,
            path=_CHROME_SANDBOX,
            label="setuid sandbox",
            expected_sha256=expected_sandbox_sha256,
            expected_mode=40000755,
        )
    browser_version = version_match.group("browser")
    return {
        "package": requirement.canonical,
        "purl": purl,
        "version": browser_version,
        "executable": _CHROME_EXECUTABLE,
        "executable_sha256": observed_executable_sha256,
        "sandbox": _CHROME_SANDBOX,
        "sandbox_present": not forbid_sandbox,
        "sandbox_sha256": observed_sandbox_sha256,
        "sandbox_policy": "forbidden" if forbid_sandbox else "setuid",
        "cpe": f"cpe:2.3:a:google:chrome:{browser_version}:*:*:*:*:*:*:*",
    }


def validate_syft_sbom(
    payload: dict[str, Any],
    *,
    image: str,
    image_id: str,
    requirements: Sequence[PackageRequirement],
    expected_chrome_executable_sha256: str | None = None,
    expected_chrome_sandbox_sha256: str | None = None,
    forbid_chrome_sandbox: bool = False,
    forbid_setuid_setgid_files: bool = False,
) -> dict[str, Any]:
    """Validate image identity, schema, and exact package evidence in a Syft SBOM."""
    descriptor = payload.get("descriptor")
    if not isinstance(descriptor, dict) or descriptor.get("name") != "syft":
        raise ReleaseIntegrityError("SBOM was not generated by Syft")
    if descriptor.get("version") != SYFT_VERSION:
        raise ReleaseIntegrityError(f"SBOM was not generated by Syft {SYFT_VERSION}")
    schema = payload.get("schema")
    if not isinstance(schema, dict) or schema.get("version") != SYFT_SCHEMA_VERSION:
        raise ReleaseIntegrityError(f"SBOM did not use Syft schema {SYFT_SCHEMA_VERSION}")

    source = payload.get("source")
    metadata = source.get("metadata") if isinstance(source, dict) else None
    if (
        not isinstance(source, dict)
        or source.get("type") != "image"
        or not isinstance(metadata, dict)
    ):
        raise ReleaseIntegrityError("Syft SBOM did not describe one container image")
    if metadata.get("imageID") != image_id:
        raise ReleaseIntegrityError("Syft SBOM did not match the inspected local image ID")
    manifest_digest = metadata.get("manifestDigest")
    if (
        not isinstance(manifest_digest, str)
        or IMAGE_DIGEST_PATTERN.fullmatch(manifest_digest) is None
    ):
        raise ReleaseIntegrityError("Syft SBOM omitted a valid image manifest digest")
    tags = metadata.get("tags")
    if not isinstance(tags, list) or image not in tags:
        raise ReleaseIntegrityError("Syft SBOM did not retain the requested local image tag")

    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ReleaseIntegrityError("Syft SBOM did not contain any packages")
    if forbid_setuid_setgid_files:
        _require_no_setid_files(payload)

    observed: dict[str, str] = {}
    chrome: dict[str, Any] | None = None
    for requirement in requirements:
        versions, matched_artifacts = _artifact_versions(artifacts, requirement)
        if versions != {requirement.version}:
            rendered = ", ".join(sorted(versions)) if versions else "missing"
            raise ReleaseIntegrityError(
                f"SBOM package {requirement.package_type}:{requirement.name} expected "
                f"{requirement.version}, found {rendered}"
            )
        _require_package_evidence(requirement, matched_artifacts)
        if requirement.package_type == "deb" and requirement.name == "google-chrome-stable":
            if expected_chrome_executable_sha256 is None:
                raise ReleaseIntegrityError(
                    "Google Chrome SBOM contract omitted its expected executable digest"
                )
            if expected_chrome_sandbox_sha256 is None and not forbid_chrome_sandbox:
                raise ReleaseIntegrityError(
                    "Google Chrome SBOM contract omitted its expected sandbox digest"
                )
            if expected_chrome_sandbox_sha256 is not None and forbid_chrome_sandbox:
                raise ReleaseIntegrityError(
                    "Chrome sandbox digest and forbidden-sandbox policy are mutually exclusive"
                )
            chrome = _require_chrome_evidence(
                payload,
                requirement,
                matched_artifacts,
                expected_executable_sha256=expected_chrome_executable_sha256,
                expected_sandbox_sha256=expected_chrome_sandbox_sha256,
                forbid_sandbox=forbid_chrome_sandbox,
            )
        observed[requirement.canonical] = requirement.version
    if chrome is None and expected_chrome_executable_sha256 is not None:
        raise ReleaseIntegrityError(
            "Chrome executable digest was configured without a Google Chrome package"
        )
    if chrome is None and expected_chrome_sandbox_sha256 is not None:
        raise ReleaseIntegrityError(
            "Chrome sandbox digest was configured without a Google Chrome package"
        )
    if chrome is None and forbid_chrome_sandbox:
        raise ReleaseIntegrityError(
            "Forbidden Chrome sandbox policy was configured without a Google Chrome package"
        )
    return {
        "image_id": image_id,
        "manifest_digest": manifest_digest,
        "packages": observed,
        "chrome": chrome,
        "setuid_setgid_files_forbidden": forbid_setuid_setgid_files,
    }


def validate_cyclonedx_sbom(
    payload: dict[str, Any],
    *,
    manifest_digest: str,
    requirements: Sequence[PackageRequirement],
    now: datetime,
) -> None:
    """Require a current CycloneDX companion SBOM for the same exact image."""
    if payload.get("bomFormat") != "CycloneDX" or payload.get("specVersion") != "1.7":
        raise ReleaseIntegrityError("CycloneDX SBOM did not use specification 1.7")
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        raise ReleaseIntegrityError("CycloneDX SBOM omitted metadata")
    _require_fresh_timestamp(
        metadata.get("timestamp"),
        label="CycloneDX generation",
        now=now,
        max_age=timedelta(hours=1),
    )
    component = metadata.get("component")
    if not isinstance(component, dict) or component.get("version") != manifest_digest:
        raise ReleaseIntegrityError("CycloneDX SBOM did not match the image manifest digest")
    tools = metadata.get("tools")
    tool_components = tools.get("components") if isinstance(tools, dict) else None
    if not isinstance(tool_components, list) or not any(
        isinstance(tool, dict)
        and tool.get("name") == "syft"
        and tool.get("version") == SYFT_VERSION
        for tool in tool_components
    ):
        raise ReleaseIntegrityError("CycloneDX SBOM omitted the pinned Syft identity")
    components = payload.get("components")
    if not isinstance(components, list) or not components:
        raise ReleaseIntegrityError("CycloneDX SBOM did not contain components")
    for requirement in requirements:
        matching_components = []
        for record in components:
            if not isinstance(record, dict):
                continue
            properties = record.get("properties")
            if not isinstance(properties, list):
                continue
            package_types = {
                prop.get("value")
                for prop in properties
                if isinstance(prop, dict) and prop.get("name") == "syft:package:type"
            }
            if (
                record.get("name") == requirement.name
                and record.get("version") == requirement.version
                and requirement.package_type in package_types
                and isinstance(record.get("purl"), str)
                and record["purl"]
            ):
                matching_components.append(record)
        if len(matching_components) != 1:
            raise ReleaseIntegrityError(
                f"CycloneDX SBOM omitted required component {requirement.canonical}"
            )


def _require_grype_configuration(payload: dict[str, Any]) -> None:
    descriptor = payload.get("descriptor")
    if not isinstance(descriptor, dict) or descriptor.get("name") != "grype":
        raise ReleaseIntegrityError("Vulnerability report was not generated by Grype")
    if descriptor.get("version") != GRYPE_VERSION:
        raise ReleaseIntegrityError(
            f"Vulnerability report was not generated by Grype {GRYPE_VERSION}"
        )
    configuration = descriptor.get("configuration")
    if not isinstance(configuration, dict):
        raise ReleaseIntegrityError("Grype report omitted its configuration")
    required_values = {
        "only-fixed": False,
        "only-notfixed": False,
        "ignore-wontfix": "",
        "fail-on-severity": "high",
    }
    for key, expected in required_values.items():
        if configuration.get(key) != expected:
            raise ReleaseIntegrityError(f"Grype report used unsafe {key} filtering")
    for key in ("vex-documents", "vex-add"):
        if configuration.get(key) not in (None, []):
            raise ReleaseIntegrityError(f"Grype report used unreviewed {key} suppression")
    if configuration.get("ignore") != []:
        raise ReleaseIntegrityError("Grype report contained vulnerability ignore rules")
    if configuration.get("exclude") != []:
        raise ReleaseIntegrityError("Grype report excluded paths from its scan")
    if configuration.get("match-upstream-kernel-headers") is not True:
        raise ReleaseIntegrityError("Grype report enabled built-in kernel-header suppressions")
    external_sources = configuration.get("externalSources")
    if not isinstance(external_sources, dict) or external_sources.get("enable") is not False:
        raise ReleaseIntegrityError("Offline Grype scan enabled external vulnerability sources")
    match = configuration.get("match")
    stock = match.get("stock") if isinstance(match, dict) else None
    if not isinstance(stock, dict) or stock.get("using-cpes") is not True:
        raise ReleaseIntegrityError("Grype report disabled binary CPE matching")
    database = configuration.get("db")
    if not isinstance(database, dict):
        raise ReleaseIntegrityError("Grype report omitted database validation settings")
    if database.get("auto-update") is not False:
        raise ReleaseIntegrityError("Offline Grype scan unexpectedly enabled database updates")
    if database.get("validate-by-hash-on-start") is not True:
        raise ReleaseIntegrityError("Grype did not validate its database hash")
    if database.get("validate-age") is not True:
        raise ReleaseIntegrityError("Grype did not validate its database age")


def _require_grype_database(
    payload: dict[str, Any],
    *,
    required_providers: set[str],
    now: datetime,
) -> dict[str, str]:
    descriptor = payload.get("descriptor")
    database = descriptor.get("db") if isinstance(descriptor, dict) else None
    if not isinstance(database, dict):
        raise ReleaseIntegrityError("Grype report omitted vulnerability database metadata")
    status = database.get("status")
    if not isinstance(status, dict) or status.get("valid") is not True:
        raise ReleaseIntegrityError("Grype vulnerability database was not valid")
    schema = status.get("schemaVersion")
    match = _GRYPE_DB_SCHEMA_PATTERN.fullmatch(schema) if isinstance(schema, str) else None
    if match is None or int(match.group("major")) != GRYPE_DB_SCHEMA_MAJOR:
        raise ReleaseIntegrityError(
            f"Grype database did not use supported schema major {GRYPE_DB_SCHEMA_MAJOR}"
        )
    built = _require_fresh_timestamp(
        status.get("built"),
        label="Grype database build",
        now=now,
        max_age=GRYPE_DB_MAX_AGE,
    )
    source = status.get("from")
    if not isinstance(source, str):
        raise ReleaseIntegrityError("Grype database omitted its source URL")
    parsed = urlparse(source)
    checksums = parse_qs(parsed.query).get("checksum", [])
    if (
        parsed.scheme != "https"
        or parsed.hostname != "grype.anchore.io"
        or len(checksums) != 1
        or IMAGE_DIGEST_PATTERN.fullmatch(checksums[0]) is None
    ):
        raise ReleaseIntegrityError("Grype database source was not checksum-pinned HTTPS")

    providers = database.get("providers")
    if not isinstance(providers, dict):
        raise ReleaseIntegrityError("Grype database omitted provider metadata")
    if not required_providers:
        raise ValueError("At least one Grype database provider must be required")
    for provider_name in required_providers:
        provider = providers.get(provider_name)
        if not isinstance(provider, dict):
            raise ReleaseIntegrityError(
                f"Grype database omitted required {provider_name} provider metadata"
            )
        captured = _aware_timestamp(
            provider.get("captured"),
            label=f"Grype {provider_name} provider capture",
        )
        if captured > built:
            raise ReleaseIntegrityError(
                f"Grype {provider_name} provider capture timestamp postdated the database build"
            )
        if built - captured > GRYPE_PROVIDER_MAX_AGE_AT_BUILD:
            raise ReleaseIntegrityError(
                f"Grype {provider_name} provider capture timestamp was stale when the database "
                "was built"
            )
    return {
        "schema": schema,
        "built": built.isoformat(),
        "source": source,
    }


def _grype_severity_counts(
    payload: dict[str, Any],
    *,
    label: str,
) -> dict[str, int]:
    ignored = payload.get("ignoredMatches")
    # Grype omits this optional array when empty; an explicit non-empty or
    # malformed value still proves a suppression occurred.
    if ignored is not None and (not isinstance(ignored, list) or ignored):
        raise ReleaseIntegrityError(f"{label} contained ignored vulnerability matches")
    matches = payload.get("matches")
    if not isinstance(matches, list):
        raise ReleaseIntegrityError(f"{label} omitted vulnerability matches")
    severity_counts = {severity: 0 for severity in sorted(_GRYPE_SEVERITIES)}
    for match_record in matches:
        if not isinstance(match_record, dict):
            raise ReleaseIntegrityError(f"{label} contained a malformed match")
        vulnerability = match_record.get("vulnerability")
        severity = vulnerability.get("severity") if isinstance(vulnerability, dict) else None
        if not isinstance(severity, str) or severity not in _GRYPE_SEVERITIES:
            raise ReleaseIntegrityError(f"{label} contained an unknown severity value")
        severity_counts[severity] += 1
    return severity_counts


def _validate_grype_matches(
    payload: dict[str, Any],
    *,
    scanner_returncode: int,
    label: str,
) -> dict[str, int]:
    severity_counts = _grype_severity_counts(payload, label=label)

    critical = severity_counts["Critical"]
    high = severity_counts["High"]
    unknown = severity_counts["Unknown"]
    blocked = bool(critical or high or unknown)
    if scanner_returncode not in {0, 2}:
        raise ReleaseIntegrityError(f"{label} command failed before a policy result")
    if (scanner_returncode == 2) != bool(critical or high):
        raise ReleaseIntegrityError(f"{label} exit status disagreed with its severity threshold")
    if blocked:
        raise ReleaseIntegrityError(
            f"{label} blocked release: "
            f"{critical} Critical, {high} High, and {unknown} Unknown findings"
        )
    return severity_counts


def validate_grype_report(
    payload: dict[str, Any],
    *,
    image_id: str,
    manifest_digest: str,
    expected_distro_name: str,
    expected_distro_version: str,
    now: datetime,
    scanner_returncode: int,
) -> dict[str, Any]:
    """Require an unsuppressed, fresh, identity-bound zero-severity report."""
    _require_grype_configuration(payload)
    descriptor = payload["descriptor"]
    scan_time = _require_fresh_timestamp(
        descriptor.get("timestamp"),
        label="Grype scan",
        now=now,
        max_age=timedelta(hours=1),
    )
    source = payload.get("source")
    target = source.get("target") if isinstance(source, dict) else None
    if (
        not isinstance(source, dict)
        or source.get("type") != "image"
        or not isinstance(target, dict)
    ):
        raise ReleaseIntegrityError("Grype report did not describe one container image")
    if target.get("imageID") != image_id or target.get("manifestDigest") != manifest_digest:
        raise ReleaseIntegrityError("Grype report did not match the exact SBOM image identity")
    distro_record = payload.get("distro")
    distro = distro_record.get("name") if isinstance(distro_record, dict) else None
    distro_version = distro_record.get("version") if isinstance(distro_record, dict) else None
    if distro != expected_distro_name or distro_version != expected_distro_version:
        raise ReleaseIntegrityError(
            "Grype report did not identify the expected image distribution release"
        )
    database = _require_grype_database(
        payload,
        required_providers={distro, "github", "nvd"},
        now=now,
    )
    severity_counts = _validate_grype_matches(
        payload,
        scanner_returncode=scanner_returncode,
        label="Grype image report",
    )
    return {
        "scan_time": scan_time.isoformat(),
        "database": database,
        "severity_counts": severity_counts,
        "distro": distro,
        "distro_version": distro_version,
    }


def validate_chrome_grype_report(
    payload: dict[str, Any],
    *,
    cpe: str,
    now: datetime,
    scanner_returncode: int,
) -> dict[str, Any]:
    """Require a fresh, unsuppressed NVD scan of the exact validated Chrome CPE."""
    _require_grype_configuration(payload)
    descriptor = payload["descriptor"]
    scan_time = _require_fresh_timestamp(
        descriptor.get("timestamp"),
        label="Grype Chrome scan",
        now=now,
        max_age=timedelta(hours=1),
    )
    source = payload.get("source")
    if not isinstance(source, dict) or source.get("type") != "cpe" or source.get("target") != cpe:
        raise ReleaseIntegrityError("Grype Chrome report did not scan the exact validated CPE")
    distro = payload.get("distro")
    if not isinstance(distro, dict) or distro.get("name") != "":
        raise ReleaseIntegrityError("Grype Chrome report unexpectedly used a distribution")
    database = _require_grype_database(
        payload,
        required_providers={"nvd"},
        now=now,
    )
    severity_counts = _validate_grype_matches(
        payload,
        scanner_returncode=scanner_returncode,
        label="Grype Chrome CPE report",
    )
    return {
        "scan_time": scan_time.isoformat(),
        "database": database,
        "severity_counts": severity_counts,
        "cpe": cpe,
        "provider": "nvd",
    }


def validate_chrome_control_report(
    payload: dict[str, Any],
    *,
    now: datetime,
    scanner_returncode: int,
) -> dict[str, Any]:
    """Prove the offline NVD/CPE path detects a known-vulnerable Chrome build."""
    _require_grype_configuration(payload)
    descriptor = payload["descriptor"]
    scan_time = _require_fresh_timestamp(
        descriptor.get("timestamp"),
        label="Grype Chrome control scan",
        now=now,
        max_age=timedelta(hours=1),
    )
    source = payload.get("source")
    if (
        not isinstance(source, dict)
        or source.get("type") != "cpe"
        or source.get("target") != _CHROME_CPE_CONTROL
    ):
        raise ReleaseIntegrityError("Grype Chrome control did not scan its exact CPE")
    distro = payload.get("distro")
    if not isinstance(distro, dict) or distro.get("name") != "":
        raise ReleaseIntegrityError("Grype Chrome control unexpectedly used a distribution")
    database = _require_grype_database(
        payload,
        required_providers={"nvd"},
        now=now,
    )
    counts = _grype_severity_counts(payload, label="Grype Chrome control report")
    if scanner_returncode != 2:
        raise ReleaseIntegrityError("Grype Chrome control did not trigger its severity gate")
    if counts["Critical"] < 1 or counts["High"] < 1 or counts["Unknown"]:
        raise ReleaseIntegrityError(
            "Grype Chrome control did not prove current Critical/High NVD coverage"
        )
    return {
        "scan_time": scan_time.isoformat(),
        "database": database,
        "severity_counts": counts,
        "cpe": _CHROME_CPE_CONTROL,
        "provider": "nvd",
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise ReleaseIntegrityError(f"Could not hash {path.name}") from exc
    return f"sha256:{digest.hexdigest()}"


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    except OSError as exc:
        raise ReleaseIntegrityError(f"Could not write {path.name}") from exc


def _write_new_json_file(path: Path, payload: dict[str, Any]) -> None:
    """Create a JSON artifact without following or overwriting an existing path."""
    try:
        with path.open("x") as handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    except OSError as exc:
        raise ReleaseIntegrityError(f"Could not create {path.name}") from exc


def _copy_scan_artifacts(
    source: Path,
    destination: Path,
    *,
    names: Sequence[str],
) -> None:
    try:
        destination.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ReleaseIntegrityError("Could not create the local scan output directory") from exc
    if destination.is_symlink() or not destination.is_dir():
        raise ReleaseIntegrityError("Local scan output must be a real directory")
    for name in names:
        target = destination / name
        if target.exists() or target.is_symlink():
            raise ReleaseIntegrityError(f"Local scan output already exists: {target}")
    for name in names:
        try:
            shutil.copy2(source / name, destination / name)
        except OSError as exc:
            raise ReleaseIntegrityError(f"Could not preserve local scan artifact {name}") from exc


def _copy_failed_scan_artifacts(
    source: Path,
    destination: Path,
    *,
    names: Sequence[str],
    message: str,
) -> None:
    """Preserve explicitly unverified evidence without minting a success receipt."""
    try:
        destination.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ReleaseIntegrityError("Could not create the failed-scan output directory") from exc
    if destination.is_symlink() or not destination.is_dir():
        raise ReleaseIntegrityError("Failed-scan output must be a real directory")
    targets = [destination / f"UNVERIFIED-{name}" for name in names]
    failure = destination / "FAILED.json"
    if any(target.exists() or target.is_symlink() for target in [*targets, failure]):
        raise ReleaseIntegrityError("Failed-scan output artifacts already exist")
    for name, target in zip(names, targets, strict=True):
        try:
            shutil.copy2(source / name, target)
        except OSError as exc:
            raise ReleaseIntegrityError(
                f"Could not preserve failed local scan artifact {name}"
            ) from exc
    _write_json_file(
        failure,
        {
            "schema_version": 1,
            "status": "failed",
            "verified": False,
            "message": message,
        },
    )


def scan_local_image(
    image: str,
    *,
    requirements: Sequence[PackageRequirement],
    expected_distro_name: str,
    expected_distro_version: str,
    expected_chrome_executable_sha256: str | None = None,
    expected_chrome_sandbox_sha256: str | None = None,
    forbid_chrome_sandbox: bool = False,
    forbid_setuid_setgid_files: bool = False,
    output_directory: Path | None = None,
    expected_platform: str = LOCAL_SCAN_PLATFORM,
    runner: CommandRunner = _default_runner,
    clock: Clock = _current_utc_time,
) -> dict[str, Any]:
    """Scan an exact saved image without exposing it to a networked scanner."""
    if not requirements:
        raise ValueError("At least one exact required SBOM package must be configured")
    for label, value in (
        ("name", expected_distro_name),
        ("version", expected_distro_version),
    ):
        if not value or any(character.isspace() for character in value):
            raise ValueError(f"Expected distribution {label} must be a non-blank token")
    for label, digest in (
        ("executable", expected_chrome_executable_sha256),
        ("sandbox", expected_chrome_sandbox_sha256),
    ):
        if digest is not None and IMAGE_DIGEST_PATTERN.fullmatch(digest) is None:
            raise ValueError(f"Expected Chrome {label} digest must be a lowercase SHA-256")
    if expected_chrome_sandbox_sha256 is not None and forbid_chrome_sandbox:
        raise ValueError(
            "Chrome sandbox digest and forbidden-sandbox policy are mutually exclusive"
        )
    _clock_time(clock)

    grype_version = _scanner_version(
        GRYPE_IMAGE,
        runner=runner,
        label="Pinned Grype identity check",
    )
    if grype_version != GRYPE_VERSION:
        raise ReleaseIntegrityError(
            f"Pinned Grype image reported {grype_version}, expected {GRYPE_VERSION}"
        )
    syft_version = _scanner_version(
        SYFT_IMAGE,
        runner=runner,
        label="Pinned Syft identity check",
    )
    if syft_version != SYFT_VERSION:
        raise ReleaseIntegrityError(
            f"Pinned Syft image reported {syft_version}, expected {SYFT_VERSION}"
        )

    image_record = _inspect_local_image(image, runner=runner)
    if image_record["platform"] != expected_platform:
        raise ReleaseIntegrityError(
            f"Local image platform was {image_record['platform']}, expected {expected_platform}"
        )

    with tempfile.TemporaryDirectory(prefix="aws-batch-scraper-image-scan-") as temporary:
        root = Path(temporary)
        cache = root / "grype-cache"
        scratch = root / "scratch"
        sbom_output = root / "sbom-output"
        report_output = root / "report-output"
        for directory in (cache, scratch, sbom_output, report_output):
            directory.mkdir()

        grype_config = root / "grype.yaml"
        _write_json_file(grype_config, {"ignore": []})

        db_command = _scanner_run_prefix(
            GRYPE_IMAGE,
            network_none=False,
            mounts=((cache, "/cache", False),),
            environment=(
                ("GRYPE_DB_CACHE_DIR", "/cache/db"),
                ("GRYPE_DB_AUTO_UPDATE", "true"),
                ("GRYPE_DB_REQUIRE_UPDATE_CHECK", "true"),
                ("GRYPE_DB_VALIDATE_BY_HASH_ON_START", "true"),
                ("GRYPE_DB_VALIDATE_AGE", "true"),
                ("GRYPE_DB_MAX_ALLOWED_BUILT_AGE", "24h"),
                ("GRYPE_CHECK_FOR_APP_UPDATE", "false"),
            ),
            tmpfs_size="512m",
        )
        _checked_output(runner, [*db_command, "db", "update"], label="Grype database update")

        archive = root / "image.tar"
        _checked_output(
            runner,
            ["docker", "image", "save", "--output", str(archive), image],
            label="Local image archive export",
        )
        if archive.is_symlink() or not archive.is_file() or archive.stat().st_size < 1:
            raise ReleaseIntegrityError("Docker did not export a valid local image archive")

        filesystem_archive = root / "filesystem.tar"
        _export_final_filesystem(
            image_record["image_id"],
            filesystem_archive,
            runner=runner,
        )
        filesystem_audit = validate_final_filesystem_archive(
            filesystem_archive,
            image_id=image_record["image_id"],
            forbid_chrome_sandbox=forbid_chrome_sandbox,
            forbid_setuid_setgid_files=forbid_setuid_setgid_files,
        )
        filesystem_audit_path = report_output / "filesystem-audit.json"
        _write_json_file(filesystem_audit_path, filesystem_audit)

        syft_command = _scanner_run_prefix(
            SYFT_IMAGE,
            network_none=True,
            mounts=(
                (archive, "/scan/image.tar", True),
                (scratch, "/tmp", False),
                (sbom_output, "/out", False),
            ),
            environment=(
                ("SYFT_CHECK_FOR_APP_UPDATE", "false"),
                ("SYFT_CACHE_DIR", "/tmp/syft-cache"),
            ),
        )
        _checked_output(
            runner,
            [
                *syft_command,
                "docker-archive:/scan/image.tar",
                "--output",
                "syft-json=/out/sbom.syft.json",
                "--output",
                "cyclonedx-json=/out/sbom.cdx.json",
            ],
            label="Offline Syft SBOM generation",
        )
        syft_path = sbom_output / "sbom.syft.json"
        cyclonedx_path = sbom_output / "sbom.cdx.json"
        syft_payload = _load_json_file(syft_path, label="Syft SBOM")
        sbom = validate_syft_sbom(
            syft_payload,
            image=image,
            image_id=image_record["image_id"],
            requirements=requirements,
            expected_chrome_executable_sha256=expected_chrome_executable_sha256,
            expected_chrome_sandbox_sha256=expected_chrome_sandbox_sha256,
            forbid_chrome_sandbox=forbid_chrome_sandbox,
            forbid_setuid_setgid_files=forbid_setuid_setgid_files,
        )
        validate_cyclonedx_sbom(
            _load_json_file(cyclonedx_path, label="CycloneDX SBOM"),
            manifest_digest=sbom["manifest_digest"],
            requirements=requirements,
            now=_clock_time(clock),
        )

        report_path = report_output / "grype.json"
        grype_command = _scanner_run_prefix(
            GRYPE_IMAGE,
            network_none=True,
            mounts=(
                (syft_path, "/scan/sbom.syft.json", True),
                (cache, "/cache", True),
                (grype_config, "/scan/grype.yaml", True),
                (report_output, "/out", False),
            ),
            environment=(
                ("GRYPE_DB_CACHE_DIR", "/cache/db"),
                ("GRYPE_DB_AUTO_UPDATE", "false"),
                ("GRYPE_DB_VALIDATE_BY_HASH_ON_START", "true"),
                ("GRYPE_DB_VALIDATE_AGE", "true"),
                ("GRYPE_DB_MAX_ALLOWED_BUILT_AGE", "24h"),
                ("GRYPE_CHECK_FOR_APP_UPDATE", "false"),
                ("GRYPE_MATCH_UPSTREAM_KERNEL_HEADERS", "true"),
            ),
            tmpfs_size="64m",
        )
        scan_result = runner(
            [
                *grype_command,
                "--config",
                "/scan/grype.yaml",
                "--fail-on",
                "high",
                "--output",
                "json",
                "--file",
                "/out/grype.json",
                "sbom:/scan/sbom.syft.json",
            ]
        )
        chrome_record = sbom.get("chrome")
        chrome_cpe: str | None = None
        chrome_report_path: Path | None = None
        chrome_scan_result: subprocess.CompletedProcess[str] | None = None
        chrome_control_path: Path | None = None
        chrome_control_result: subprocess.CompletedProcess[str] | None = None
        if chrome_record is not None:
            if not isinstance(chrome_record, dict) or not isinstance(chrome_record.get("cpe"), str):
                raise ReleaseIntegrityError("Validated Chrome evidence was malformed")
            chrome_cpe = chrome_record["cpe"]
            chrome_report_path = report_output / "grype.chrome.json"
            chrome_scan_result = runner(
                [
                    *grype_command,
                    "--config",
                    "/scan/grype.yaml",
                    "--fail-on",
                    "high",
                    "--output",
                    "json",
                    "--file",
                    "/out/grype.chrome.json",
                    chrome_cpe,
                ]
            )
            chrome_control_path = report_output / "grype.chrome-control.json"
            chrome_control_result = runner(
                [
                    *grype_command,
                    "--config",
                    "/scan/grype.yaml",
                    "--fail-on",
                    "high",
                    "--output",
                    "json",
                    "--file",
                    "/out/grype.chrome-control.json",
                    _CHROME_CPE_CONTROL,
                ]
            )
        raw_artifact_names = [
            "filesystem-audit.json",
            "sbom.syft.json",
            "sbom.cdx.json",
            "grype.json",
        ]
        shutil.copy2(syft_path, report_output / "sbom.syft.json")
        shutil.copy2(cyclonedx_path, report_output / "sbom.cdx.json")
        if chrome_report_path is not None:
            raw_artifact_names.append("grype.chrome.json")
        if chrome_control_path is not None:
            raw_artifact_names.append("grype.chrome-control.json")
        try:
            report = validate_grype_report(
                _load_json_file(report_path, label="Grype vulnerability report"),
                image_id=sbom["image_id"],
                manifest_digest=sbom["manifest_digest"],
                expected_distro_name=expected_distro_name,
                expected_distro_version=expected_distro_version,
                now=_clock_time(clock),
                scanner_returncode=scan_result.returncode,
            )
            chrome_report: dict[str, Any] | None = None
            chrome_control: dict[str, Any] | None = None
            if (
                chrome_report_path is not None
                and chrome_scan_result is not None
                and chrome_cpe is not None
                and chrome_control_path is not None
                and chrome_control_result is not None
            ):
                chrome_report = validate_chrome_grype_report(
                    _load_json_file(chrome_report_path, label="Grype Chrome CPE report"),
                    cpe=chrome_cpe,
                    now=_clock_time(clock),
                    scanner_returncode=chrome_scan_result.returncode,
                )
                chrome_control = validate_chrome_control_report(
                    _load_json_file(
                        chrome_control_path,
                        label="Grype Chrome coverage-control report",
                    ),
                    now=_clock_time(clock),
                    scanner_returncode=chrome_control_result.returncode,
                )
        except ReleaseIntegrityError as exc:
            if output_directory is not None:
                _copy_failed_scan_artifacts(
                    report_output,
                    output_directory,
                    names=raw_artifact_names,
                    message=str(exc),
                )
            raise
        final_image_record = _inspect_local_image(image, runner=runner)
        if final_image_record != image_record:
            raise ReleaseIntegrityError(
                "Local image identity changed during its vulnerability scan"
            )

        receipt = {
            "schema_version": 1,
            "image": {
                "reference": image,
                "id": sbom["image_id"],
                "manifest_digest": sbom["manifest_digest"],
                "platform": image_record["platform"],
            },
            "tools": {
                "grype": {"image": GRYPE_IMAGE, "version": GRYPE_VERSION},
                "syft": {
                    "image": SYFT_IMAGE,
                    "version": SYFT_VERSION,
                    "schema": SYFT_SCHEMA_VERSION,
                },
            },
            "packages": sbom["packages"],
            "chrome": chrome_record,
            "filesystem": filesystem_audit,
            "scans": {
                "image": report,
                "chrome": chrome_report,
                "chrome_coverage_control": chrome_control,
            },
            "artifacts": {
                "filesystem-audit.json": _sha256_file(filesystem_audit_path),
                "sbom.syft.json": _sha256_file(syft_path),
                "sbom.cdx.json": _sha256_file(cyclonedx_path),
                "grype.json": _sha256_file(report_path),
            },
        }
        if chrome_report_path is not None:
            receipt["artifacts"]["grype.chrome.json"] = _sha256_file(chrome_report_path)
        if chrome_control_path is not None:
            receipt["artifacts"]["grype.chrome-control.json"] = _sha256_file(chrome_control_path)
        _write_json_file(report_output / "receipt.json", receipt)
        if output_directory is not None:
            _copy_scan_artifacts(
                report_output,
                output_directory,
                names=(*raw_artifact_names, "receipt.json"),
            )
        return receipt


def _resolve_remote_digest(
    target: ReleaseTarget,
    *,
    runner: CommandRunner,
    expected_image_id: str,
    now: datetime,
) -> tuple[str, datetime]:
    payload = _json_output(
        runner,
        target.aws_command(
            "ecr",
            "describe-images",
            "--registry-id",
            target.account_id,
            "--repository-name",
            target.repository,
            "--image-ids",
            f"imageTag={target.tag}",
            "--output",
            "json",
        ),
        label="ECR digest resolution",
    )
    details = payload.get("imageDetails")
    if not isinstance(details, list) or len(details) != 1 or not isinstance(details[0], dict):
        raise ReleaseIntegrityError("ECR digest resolution did not return one exact image")
    detail = details[0]
    if detail.get("registryId") != target.account_id:
        raise ReleaseIntegrityError("ECR digest resolution returned the wrong registry account")
    if detail.get("repositoryName") != target.repository:
        raise ReleaseIntegrityError("ECR digest resolution returned the wrong repository")
    digest = detail.get("imageDigest")
    tags = detail.get("imageTags")
    if not isinstance(digest, str) or IMAGE_DIGEST_PATTERN.fullmatch(digest) is None:
        raise ReleaseIntegrityError("ECR returned an invalid image digest")
    if not isinstance(tags, list) or target.tag not in tags:
        raise ReleaseIntegrityError("Resolved ECR image no longer carries the requested tag")
    pushed_at = _require_fresh_timestamp(
        detail.get("imagePushedAt"),
        label="ECR image push",
        now=now,
        max_age=REMOTE_SCAN_MAX_AGE,
    )
    _require_remote_config_identity(
        target,
        digest,
        expected_image_id,
        runner=runner,
    )
    return digest, pushed_at


def _require_remote_config_identity(
    target: ReleaseTarget,
    digest: str,
    expected_image_id: str,
    *,
    runner: CommandRunner,
) -> None:
    """Bind the ECR manifest's config digest to the exact locally scanned image ID."""
    payload = _json_output(
        runner,
        target.aws_command(
            "ecr",
            "batch-get-image",
            "--registry-id",
            target.account_id,
            "--repository-name",
            target.repository,
            "--image-ids",
            f"imageDigest={digest}",
            "--accepted-media-types",
            "application/vnd.docker.distribution.manifest.v2+json",
            "application/vnd.oci.image.manifest.v1+json",
            "--output",
            "json",
        ),
        label="ECR manifest identity inspection",
    )
    failures = payload.get("failures")
    images = payload.get("images")
    if failures not in (None, []) or not isinstance(images, list) or len(images) != 1:
        raise ReleaseIntegrityError("ECR manifest identity inspection did not return one image")
    image = images[0]
    if not isinstance(image, dict):
        raise ReleaseIntegrityError("ECR manifest identity inspection returned malformed data")
    if image.get("registryId") != target.account_id:
        raise ReleaseIntegrityError("ECR manifest identity inspection returned the wrong account")
    if image.get("repositoryName") != target.repository:
        raise ReleaseIntegrityError(
            "ECR manifest identity inspection returned the wrong repository"
        )
    image_id = image.get("imageId")
    if not isinstance(image_id, dict) or image_id.get("imageDigest") != digest:
        raise ReleaseIntegrityError("ECR manifest identity inspection returned the wrong digest")
    manifest_text = image.get("imageManifest")
    if not isinstance(manifest_text, str):
        raise ReleaseIntegrityError("ECR manifest identity inspection omitted the manifest")
    observed_manifest_digest = f"sha256:{hashlib.sha256(manifest_text.encode()).hexdigest()}"
    if observed_manifest_digest != digest:
        raise ReleaseIntegrityError("ECR manifest bytes did not match the resolved content digest")
    manifest = _parse_json_object(manifest_text, label="ECR image manifest")
    response_media_type = image.get("imageManifestMediaType")
    if (
        response_media_type not in _IMAGE_MANIFEST_MEDIA_TYPES
        or manifest.get("mediaType") != response_media_type
        or manifest.get("schemaVersion") != 2
    ):
        raise ReleaseIntegrityError("ECR returned an unsupported or inconsistent image manifest")
    config = manifest.get("config")
    config_size = config.get("size") if isinstance(config, dict) else None
    if (
        not isinstance(config, dict)
        or config.get("mediaType") not in _IMAGE_CONFIG_MEDIA_TYPES
        or config.get("digest") != expected_image_id
        or isinstance(config_size, bool)
        or not isinstance(config_size, int)
        or config_size < 1
    ):
        raise ReleaseIntegrityError(
            "Pushed ECR image config did not match the locally scanned image"
        )


def _scan_findings_payload(
    target: ReleaseTarget,
    digest: str,
    *,
    runner: CommandRunner,
) -> dict[str, Any] | None:
    """Read one scan snapshot, tolerating only initial scan-registration lag."""
    command = target.aws_command(
        "ecr",
        "describe-image-scan-findings",
        "--registry-id",
        target.account_id,
        "--repository-name",
        target.repository,
        "--image-id",
        f"imageDigest={digest}",
        "--no-paginate",
        "--output",
        "json",
    )
    result = runner(command)
    if result.returncode != 0:
        stderr = result.stderr if isinstance(result.stderr, str) else ""
        error_match = _AWS_CLI_ERROR_PATTERN.search(stderr)
        if error_match is not None and error_match.group("code") == "ScanNotFoundException":
            return None
        raise ReleaseIntegrityError("ECR image scan findings command failed")
    return _parse_json_object(result.stdout, label="ECR image scan findings")


def _validated_scan_status(
    payload: dict[str, Any],
    target: ReleaseTarget,
    digest: str,
) -> str:
    """Validate scan identity and return its exact service status."""
    response_image_id = payload.get("imageId")
    if payload.get("registryId") != target.account_id:
        raise ReleaseIntegrityError("ECR scan findings returned the wrong registry account")
    if payload.get("repositoryName") != target.repository:
        raise ReleaseIntegrityError("ECR scan findings returned the wrong repository")
    if not isinstance(response_image_id, dict) or response_image_id.get("imageDigest") != digest:
        raise ReleaseIntegrityError("ECR scan findings did not match the pushed image digest")
    status_record = payload.get("imageScanStatus")
    status = status_record.get("status") if isinstance(status_record, dict) else None
    if not isinstance(status, str) or not status:
        raise ReleaseIntegrityError("ECR image scan omitted its status")
    return status


def _require_clean_scan_findings(
    payload: dict[str, Any],
    *,
    now: datetime,
    pushed_at: datetime,
) -> None:
    """Reject stale/malformed findings or any unclassified or severe count."""
    findings = payload.get("imageScanFindings")
    if not isinstance(findings, dict):
        raise ReleaseIntegrityError("ECR image scan omitted its findings")
    completed_at = _require_fresh_timestamp(
        findings.get("imageScanCompletedAt"),
        label="ECR image scan completion",
        now=now,
        max_age=REMOTE_SCAN_MAX_AGE,
    )
    if completed_at + LOCAL_SCAN_CLOCK_SKEW < pushed_at:
        raise ReleaseIntegrityError("ECR image scan completion predated the image push")
    _require_fresh_timestamp(
        findings.get("vulnerabilitySourceUpdatedAt"),
        label="ECR vulnerability-source update",
        now=now,
        max_age=REMOTE_VULNERABILITY_SOURCE_MAX_AGE,
    )
    counts = findings.get("findingSeverityCounts")
    if not isinstance(counts, dict):
        raise ReleaseIntegrityError("ECR image scan omitted valid severity counts")
    for severity, count in counts.items():
        if not isinstance(severity, str) or severity not in _SCAN_SEVERITIES:
            raise ReleaseIntegrityError("ECR image scan returned an unknown severity")
        if isinstance(count, bool) or not isinstance(count, int):
            raise ReleaseIntegrityError("ECR image scan returned an invalid severity count")
        if count < 0:
            raise ReleaseIntegrityError("ECR image scan returned a negative severity count")
    # AWS reports this map as aggregate totals even when detailed findings have
    # a nextToken, so omitted individual High/Critical keys mean zero.
    critical = counts.get("CRITICAL", 0)
    high = counts.get("HIGH", 0)
    undefined = counts.get("UNDEFINED", 0)
    if critical or high or undefined:
        raise ReleaseIntegrityError(
            "ECR scan blocked release: "
            f"{critical} Critical, {high} High, and {undefined} Undefined findings"
        )


def verify_remote_scan(
    target: ReleaseTarget,
    *,
    expected_image_id: str,
    runner: CommandRunner = _default_runner,
    sleeper: Sleeper = time.sleep,
    max_attempts: int = SCAN_MAX_ATTEMPTS,
    poll_interval_seconds: float = SCAN_POLL_INTERVAL_SECONDS,
    clock: Clock = _current_utc_time,
) -> str:
    """Resolve the pushed digest, poll its scan, and reject severe findings."""
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
        raise ValueError("Scan max_attempts must be a positive integer")
    if (
        isinstance(poll_interval_seconds, bool)
        or not isinstance(poll_interval_seconds, (int, float))
        or not math.isfinite(poll_interval_seconds)
        or poll_interval_seconds < 0
    ):
        raise ValueError("Scan poll_interval_seconds must be non-negative")

    if IMAGE_DIGEST_PATTERN.fullmatch(expected_image_id) is None:
        raise ValueError("Expected local image ID must be a lowercase SHA-256")
    started_at = _clock_time(clock)
    digest, pushed_at = _resolve_remote_digest(
        target,
        runner=runner,
        expected_image_id=expected_image_id,
        now=started_at,
    )
    last_status = "SCAN_NOT_FOUND"
    for attempt in range(1, max_attempts + 1):
        payload = _scan_findings_payload(target, digest, runner=runner)
        if payload is not None:
            last_status = _validated_scan_status(payload, target, digest)
            if last_status in _SCAN_SUCCESS_STATUSES:
                _require_clean_scan_findings(
                    payload,
                    now=_clock_time(clock),
                    pushed_at=pushed_at,
                )
                return digest
            if last_status not in _SCAN_PENDING_STATUSES:
                raise ReleaseIntegrityError(f"ECR image scan reached terminal status {last_status}")
        if attempt < max_attempts:
            sleeper(poll_interval_seconds)

    raise ReleaseIntegrityError(
        "ECR image scan did not become ready after "
        f"{max_attempts} checks; last status was {last_status}"
    )


def _require_zero_receipt_counts(scan: object, *, label: str) -> None:
    if not isinstance(scan, dict):
        raise ReleaseIntegrityError(f"Local scan receipt omitted its {label} scan")
    counts = scan.get("severity_counts")
    if not isinstance(counts, dict):
        raise ReleaseIntegrityError(f"Local scan receipt omitted {label} severity counts")
    for severity in ("Critical", "High", "Unknown"):
        count = counts.get(severity)
        if isinstance(count, bool) or not isinstance(count, int) or count != 0:
            raise ReleaseIntegrityError(
                f"Local scan receipt did not prove zero {severity} {label} findings"
            )


def write_verified_release_receipt(
    local_scan_receipt: Path,
    release_receipt: Path,
    *,
    target: ReleaseTarget,
    digest: str,
    expected_image_id: str,
    clock: Clock = _current_utc_time,
) -> None:
    """Bind exact local scanner evidence to a remotely verified ECR digest."""
    if IMAGE_DIGEST_PATTERN.fullmatch(digest) is None:
        raise ValueError("Verified ECR digest must be a lowercase SHA-256")
    if IMAGE_DIGEST_PATTERN.fullmatch(expected_image_id) is None:
        raise ValueError("Expected local image ID must be a lowercase SHA-256")
    if release_receipt.parent != local_scan_receipt.parent:
        raise ReleaseIntegrityError("Release receipt must accompany its local scan receipt")
    if local_scan_receipt.parent.is_symlink() or not local_scan_receipt.parent.is_dir():
        raise ReleaseIntegrityError("Release evidence directory must be a real directory")
    if release_receipt.exists() or release_receipt.is_symlink():
        raise ReleaseIntegrityError("Verified release receipt already exists")
    local_receipt_sha256 = _sha256_file(local_scan_receipt)
    payload = _load_json_file(local_scan_receipt, label="Local scan receipt")
    if payload.get("schema_version") != 1:
        raise ReleaseIntegrityError("Local scan receipt used an unsupported schema")
    image = payload.get("image")
    if not isinstance(image, dict) or image.get("id") != expected_image_id:
        raise ReleaseIntegrityError("Local scan receipt did not match the pushed image ID")
    manifest_digest = image.get("manifest_digest")
    if (
        not isinstance(manifest_digest, str)
        or IMAGE_DIGEST_PATTERN.fullmatch(manifest_digest) is None
        or image.get("platform") != LOCAL_SCAN_PLATFORM
    ):
        raise ReleaseIntegrityError("Local scan receipt contained invalid image identity")
    tools = payload.get("tools")
    grype = tools.get("grype") if isinstance(tools, dict) else None
    syft = tools.get("syft") if isinstance(tools, dict) else None
    if (
        not isinstance(grype, dict)
        or grype.get("image") != GRYPE_IMAGE
        or grype.get("version") != GRYPE_VERSION
        or not isinstance(syft, dict)
        or syft.get("image") != SYFT_IMAGE
        or syft.get("version") != SYFT_VERSION
        or syft.get("schema") != SYFT_SCHEMA_VERSION
    ):
        raise ReleaseIntegrityError("Local scan receipt did not retain pinned scanner identity")
    scans = payload.get("scans")
    if not isinstance(scans, dict):
        raise ReleaseIntegrityError("Local scan receipt omitted vulnerability scans")
    _require_zero_receipt_counts(scans.get("image"), label="image")
    _require_zero_receipt_counts(scans.get("chrome"), label="Chrome")
    control = scans.get("chrome_coverage_control")
    control_counts = control.get("severity_counts") if isinstance(control, dict) else None
    if (
        not isinstance(control_counts, dict)
        or isinstance(control_counts.get("Critical"), bool)
        or not isinstance(control_counts.get("Critical"), int)
        or isinstance(control_counts.get("High"), bool)
        or not isinstance(control_counts.get("High"), int)
        or control_counts["Critical"] < 1
        or control_counts["High"] < 1
    ):
        raise ReleaseIntegrityError("Local scan receipt omitted its Chrome coverage control")
    filesystem = payload.get("filesystem")
    if (
        not isinstance(filesystem, dict)
        or filesystem.get("schema_version") != 1
        or filesystem.get("image_id") != expected_image_id
        or isinstance(filesystem.get("members"), bool)
        or not isinstance(filesystem.get("members"), int)
        or filesystem["members"] < 1
        or isinstance(filesystem.get("regular_files"), bool)
        or not isinstance(filesystem.get("regular_files"), int)
        or filesystem["regular_files"] < 1
        or not isinstance(filesystem.get("archive_sha256"), str)
        or IMAGE_DIGEST_PATTERN.fullmatch(filesystem["archive_sha256"]) is None
    ):
        raise ReleaseIntegrityError("Local scan receipt omitted its final-filesystem audit")
    chrome = payload.get("chrome")
    if not isinstance(chrome, dict):
        raise ReleaseIntegrityError("Local scan receipt omitted its Chrome sandbox policy")
    sandbox_policy = chrome.get("sandbox_policy")
    setid_policy = filesystem.get("setuid_setgid_policy")
    setid_count = filesystem.get("setuid_setgid_files")
    if setid_policy == "forbidden":
        if isinstance(setid_count, bool) or not isinstance(setid_count, int) or setid_count != 0:
            raise ReleaseIntegrityError(
                "Local scan receipt did not prove its forbidden setuid/setgid policy"
            )
    elif setid_policy == "permitted":
        if isinstance(setid_count, bool) or not isinstance(setid_count, int) or setid_count < 0:
            raise ReleaseIntegrityError(
                "Local scan receipt contained an invalid permitted setuid/setgid audit"
            )
    else:
        raise ReleaseIntegrityError("Local scan receipt omitted its setuid/setgid policy")
    if sandbox_policy == "forbidden":
        if (
            chrome.get("sandbox_present") is not False
            or chrome.get("sandbox_sha256") is not None
            or filesystem.get("chrome_sandbox_policy") != "forbidden"
            or filesystem.get("chrome_sandbox_present") is not False
        ):
            raise ReleaseIntegrityError(
                "Local scan receipt did not prove its forbidden privilege-helper policy"
            )
    elif sandbox_policy == "setuid":
        sandbox_sha256 = chrome.get("sandbox_sha256")
        if (
            chrome.get("sandbox_present") is not True
            or not isinstance(sandbox_sha256, str)
            or IMAGE_DIGEST_PATTERN.fullmatch(sandbox_sha256) is None
            or filesystem.get("chrome_sandbox_policy") != "permitted"
            or filesystem.get("setuid_setgid_policy") != "permitted"
            or filesystem.get("chrome_sandbox_present") is not True
            or isinstance(setid_count, bool)
            or not isinstance(setid_count, int)
            or setid_count < 1
        ):
            raise ReleaseIntegrityError(
                "Local scan receipt did not prove its reviewed setuid sandbox policy"
            )
    else:
        raise ReleaseIntegrityError("Local scan receipt omitted its Chrome sandbox policy")
    artifacts = payload.get("artifacts")
    required_artifacts = {
        "filesystem-audit.json",
        "sbom.syft.json",
        "sbom.cdx.json",
        "grype.json",
        "grype.chrome.json",
        "grype.chrome-control.json",
    }
    if not isinstance(artifacts, dict) or set(artifacts) != required_artifacts:
        raise ReleaseIntegrityError("Local scan receipt omitted exact evidence artifacts")
    for name in sorted(required_artifacts):
        expected_artifact_digest = artifacts.get(name)
        artifact_path = local_scan_receipt.parent / name
        if (
            not isinstance(expected_artifact_digest, str)
            or IMAGE_DIGEST_PATTERN.fullmatch(expected_artifact_digest) is None
            or artifact_path.is_symlink()
            or not artifact_path.is_file()
            or _sha256_file(artifact_path) != expected_artifact_digest
        ):
            raise ReleaseIntegrityError(f"Local scan artifact {name} failed receipt validation")
    verified_at = _clock_time(clock)
    if _sha256_file(local_scan_receipt) != local_receipt_sha256:
        raise ReleaseIntegrityError("Local scan receipt changed during release verification")
    _write_new_json_file(
        release_receipt,
        {
            "schema_version": 1,
            "status": "verified",
            "verified_at": verified_at.isoformat(),
            "local_scan_receipt_sha256": local_receipt_sha256,
            "image": {
                "id": expected_image_id,
                "local_manifest_digest": manifest_digest,
                "ecr_digest": digest,
                "ecr_uri": f"{target.repository_uri}@{digest}",
            },
            "ecr": {
                "registry_id": target.account_id,
                "repository": target.repository,
                "region": target.region,
                "tag": target.tag,
            },
        },
    )


def _target_from_args(args: argparse.Namespace) -> ReleaseTarget:
    profile = args.profile.strip() if args.profile else None
    return ReleaseTarget(
        account_id=args.account_id,
        repository=args.repository,
        region=args.region,
        tag=args.tag,
        profile=profile,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_target_arguments(command: argparse.ArgumentParser) -> None:
        command.add_argument("--account-id", required=True)
        command.add_argument("--repository", required=True)
        command.add_argument("--region", required=True)
        command.add_argument("--tag", required=True)
        command.add_argument("--profile")

    preflight = subparsers.add_parser("preflight")
    add_target_arguments(preflight)

    local = subparsers.add_parser("verify-local-image")
    local.add_argument("--image", required=True)
    local.add_argument("--tag", required=True)

    local_scan = subparsers.add_parser("scan-local-image")
    local_scan.add_argument("--image", required=True)
    local_scan.add_argument("--required-packages", required=True)
    local_scan.add_argument("--required-chrome-executable-sha256")
    sandbox_policy = local_scan.add_mutually_exclusive_group()
    sandbox_policy.add_argument("--required-chrome-sandbox-sha256")
    sandbox_policy.add_argument("--forbid-chrome-sandbox", action="store_true")
    local_scan.add_argument("--forbid-setuid-setgid-files", action="store_true")
    local_scan.add_argument("--output-directory", type=Path)
    local_scan.add_argument("--expected-platform", default=LOCAL_SCAN_PLATFORM)
    local_scan.add_argument("--expected-distro-name", required=True)
    local_scan.add_argument("--expected-distro-version", required=True)
    local_scan.add_argument("--print-identity", action="store_true")

    scan = subparsers.add_parser("verify-scan")
    add_target_arguments(scan)
    scan.add_argument("--expected-image-id", required=True)
    scan.add_argument("--local-scan-receipt", required=True, type=Path)
    scan.add_argument("--release-receipt", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one release-integrity command."""
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            preflight_release(_target_from_args(args))
        elif args.command == "verify-local-image":
            verify_local_image(args.image, args.tag)
        elif args.command == "scan-local-image":
            receipt = scan_local_image(
                args.image,
                requirements=parse_package_requirements(args.required_packages),
                expected_distro_name=args.expected_distro_name,
                expected_distro_version=args.expected_distro_version,
                expected_chrome_executable_sha256=args.required_chrome_executable_sha256,
                expected_chrome_sandbox_sha256=args.required_chrome_sandbox_sha256,
                forbid_chrome_sandbox=args.forbid_chrome_sandbox,
                forbid_setuid_setgid_files=args.forbid_setuid_setgid_files,
                output_directory=args.output_directory,
                expected_platform=args.expected_platform,
            )
            counts = receipt["scans"]["image"]["severity_counts"]
            print(
                "Local image gate passed with "
                f"{counts['Critical']} Critical and {counts['High']} High findings",
                file=sys.stderr,
            )
            if args.print_identity:
                print(f"{receipt['image']['id']} {receipt['image']['manifest_digest']}")
        elif args.command == "verify-scan":
            target = _target_from_args(args)
            digest = verify_remote_scan(target, expected_image_id=args.expected_image_id)
            write_verified_release_receipt(
                args.local_scan_receipt,
                args.release_receipt,
                target=target,
                digest=digest,
                expected_image_id=args.expected_image_id,
            )
            print(f"{target.repository_uri}@{digest}")
        else:  # pragma: no cover - argparse constrains this state.
            raise AssertionError(f"Unhandled release command: {args.command}")
    except (ReleaseIntegrityError, ValueError) as exc:
        print(f"Release integrity check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
