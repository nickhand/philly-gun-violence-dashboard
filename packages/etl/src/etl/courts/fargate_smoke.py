"""Fail-closed, read-only runtime checks for a one-shot courts Fargate task."""

from __future__ import annotations

import http.client
import json
import os
import pwd
import re
import stat
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from etl.courts.scraper.core import SEARCH_BY_DROPDOWN, UJSPortalScraper

FARGATE_SMOKE_SUCCESS_MARKER = "COURTS_FARGATE_SMOKE_OK_V1"

_CHROME_SANDBOX = "/opt/google/chrome/chrome-sandbox"
_DISPATCH_TOKEN = "GITHUB_DISPATCH_TOKEN"
_PROC_STATUS = Path("/proc/self/status")
_PROC_ROOT = Path("/proc")
_MOUNTINFO = Path("/proc/self/mountinfo")
_MAX_PROC_FILE_BYTES = 128 * 1024
_FIND_TIMEOUT_SECONDS = 120
_METADATA_TIMEOUT_SECONDS = 5
_MAX_METADATA_BYTES = 1024 * 1024
_METADATA_HOST = "169.254.170.2"
_MOUNT_ESCAPE = re.compile(r"\\([0-7]{3})")
_CHROME_EXECUTABLE_NAMES = frozenset({"chrome", "google-chrome", "google-chrome-stable"})
_TASK_DEFINITION = re.compile(
    r"^(?:arn:[^:]+:ecs:[^:]+:[0-9]{12}:task-definition/)?"
    r"(?P<family>[A-Za-z0-9_-]{1,255}):(?P<revision>[1-9][0-9]*)$"
)
_EXPECTED_IMAGE = re.compile(
    r"^(?P<account>[0-9]{12})\.dkr\.ecr\."
    r"(?P<region>[a-z]{2}(?:-[a-z0-9]+)+-[0-9]+)"
    r"\.amazonaws\.com(?:\.cn)?/[a-z0-9]+(?:[._/-][a-z0-9]+)*"
    r"@(?P<digest>sha256:[0-9a-f]{64})$"
)
_CONTAINER_NAME = re.compile(r"^[A-Za-z0-9_-]{1,255}$")
_ACCOUNT_ID = re.compile(r"^[0-9]{12}$")
_REGION = re.compile(r"^[a-z]{2}(?:-[a-z0-9]+)+-[0-9]+$")
_CLUSTER_NAME = re.compile(r"^[A-Za-z0-9_-]{1,255}$")


class FargateSmokeError(RuntimeError):
    """The live task does not satisfy the reviewed Fargate runtime contract."""


@dataclass(frozen=True)
class _Mount:
    mount_id: int
    mount_point: str
    options: frozenset[str]


def _read_bounded(path: Path, *, label: str) -> bytes:
    try:
        with path.open("rb") as stream:
            payload = stream.read(_MAX_PROC_FILE_BYTES + 1)
    except OSError as exc:
        raise FargateSmokeError(f"Could not read {label}") from exc
    if len(payload) > _MAX_PROC_FILE_BYTES:
        raise FargateSmokeError(f"{label} exceeded the runtime inspection limit")
    return payload


def _assert_app_identity() -> None:
    real_uid = os.getuid()
    effective_uid = os.geteuid()
    if real_uid == 0 or effective_uid == 0 or real_uid != effective_uid:
        raise FargateSmokeError("Fargate smoke must run as one consistent non-root user")
    try:
        username = pwd.getpwuid(effective_uid).pw_name
    except KeyError as exc:
        raise FargateSmokeError("Fargate smoke user is absent from the passwd database") from exc
    if username != "app":
        raise FargateSmokeError("Fargate smoke must run as the image's app user")


def _parse_proc_status(payload: str) -> dict[str, str]:
    required = {"Seccomp", "CapEff", "CapPrm", "CapBnd"}
    observed: dict[str, str] = {}
    for line in payload.splitlines():
        name, separator, value = line.partition(":")
        if separator and name in required:
            if name in observed:
                raise FargateSmokeError(f"Process status repeated {name}")
            observed[name] = value.strip()
    missing = required.difference(observed)
    if missing:
        raise FargateSmokeError(
            f"Process status omitted required fields: {', '.join(sorted(missing))}"
        )
    return observed


def _assert_process_security() -> None:
    try:
        payload = _read_bounded(_PROC_STATUS, label="process status").decode("ascii")
    except UnicodeDecodeError as exc:
        raise FargateSmokeError("Process status was not ASCII") from exc
    fields = _parse_proc_status(payload)
    try:
        seccomp_mode = int(fields["Seccomp"], 10)
        capabilities = {name: int(fields[name], 16) for name in ("CapEff", "CapPrm", "CapBnd")}
    except ValueError as exc:
        raise FargateSmokeError("Process security fields were malformed") from exc
    if seccomp_mode != 2:
        raise FargateSmokeError("Fargate smoke requires seccomp filter mode 2")
    nonzero = [name for name, value in capabilities.items() if value != 0]
    if nonzero:
        raise FargateSmokeError(f"Fargate smoke retained Linux capabilities: {', '.join(nonzero)}")


def _decode_mount_field(value: str) -> str:
    return _MOUNT_ESCAPE.sub(lambda match: chr(int(match.group(1), 8)), value)


def _parse_mountinfo(payload: str) -> list[_Mount]:
    mounts: list[_Mount] = []
    for line in payload.splitlines():
        before_separator, separator, after_separator = line.partition(" - ")
        fields = before_separator.split()
        filesystem_fields = after_separator.split()
        if not separator or len(fields) < 6 or len(filesystem_fields) < 3:
            raise FargateSmokeError("Kernel mount information was malformed")
        try:
            mount_id = int(fields[0], 10)
        except ValueError as exc:
            raise FargateSmokeError("Kernel mount ID was malformed") from exc
        options = frozenset(option for option in fields[5].split(",") if option)
        mounts.append(
            _Mount(
                mount_id=mount_id,
                mount_point=_decode_mount_field(fields[4]),
                options=options,
            )
        )
    if not mounts:
        raise FargateSmokeError("Kernel mount information was empty")
    return mounts


def _one_mount(mounts: list[_Mount], mount_point: str) -> _Mount:
    matches = [mount for mount in mounts if mount.mount_point == mount_point]
    if len(matches) != 1:
        raise FargateSmokeError(f"Expected exactly one {mount_point} mount")
    return matches[0]


def _assert_mount_contract() -> None:
    try:
        payload = _read_bounded(_MOUNTINFO, label="mount information").decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FargateSmokeError("Kernel mount information was not UTF-8") from exc
    mounts = _parse_mountinfo(payload)
    root_mount = _one_mount(mounts, "/")
    temporary_mount = _one_mount(mounts, "/tmp")
    if root_mount.mount_id == temporary_mount.mount_id:
        raise FargateSmokeError("/tmp must be a mount separate from the read-only root")
    if "ro" not in root_mount.options or "rw" in root_mount.options:
        raise FargateSmokeError("Container root mount is not read-only")
    if "rw" not in temporary_mount.options or "ro" in temporary_mount.options:
        raise FargateSmokeError("/tmp mount is not writable")
    try:
        root_flags = os.statvfs("/").f_flag
        temporary_flags = os.statvfs("/tmp").f_flag
        temporary_status = os.lstat("/tmp")
    except OSError as exc:
        raise FargateSmokeError("Could not inspect runtime mount properties") from exc
    if root_flags & os.ST_RDONLY == 0:
        raise FargateSmokeError("Root filesystem does not report read-only status")
    if temporary_flags & os.ST_RDONLY:
        raise FargateSmokeError("/tmp filesystem reports read-only status")
    if not stat.S_ISDIR(temporary_status.st_mode):
        raise FargateSmokeError("/tmp is not a directory")
    if stat.S_IMODE(temporary_status.st_mode) != 0o1777:
        raise FargateSmokeError("/tmp must have mode 1777")


def _assert_no_chrome_sandbox_helper() -> None:
    if os.path.lexists(_CHROME_SANDBOX):
        raise FargateSmokeError("Image retained the forbidden Chrome sandbox helper")


def _find_command() -> list[str]:
    # Prune directories the app user cannot enumerate. Such files cannot be
    # executed by the worker; the release scanner separately audits them as root.
    return [
        "/usr/bin/find",
        "/",
        "-xdev",
        "-ignore_readdir_race",
        "(",
        "-type",
        "d",
        "(",
        "!",
        "-readable",
        "-o",
        "!",
        "-executable",
        ")",
        "-prune",
        ")",
        "-o",
        "(",
        "-type",
        "f",
        "-perm",
        "/6000",
        "-print",
        "-quit",
        ")",
    ]


def _assert_no_visible_setid_files() -> None:
    try:
        result = subprocess.run(
            _find_command(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=_FIND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FargateSmokeError("Setuid/setgid filesystem inspection failed") from exc
    if result.returncode != 0 or result.stderr.strip():
        raise FargateSmokeError("Setuid/setgid filesystem inspection returned an error")
    privileged_path = result.stdout.splitlines()[:1]
    if privileged_path:
        try:
            rendered = os.fsdecode(privileged_path[0])
        except UnicodeDecodeError:
            rendered = "<non-UTF-8 path>"
        raise FargateSmokeError(f"Runtime root contains a setuid/setgid file: {rendered}")


def _assert_dispatch_secret_absent() -> None:
    if _DISPATCH_TOKEN in os.environ:
        raise FargateSmokeError("Worker environment must not contain GITHUB_DISPATCH_TOKEN")


def _required_environment(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name)
    if not isinstance(value, str) or not value.strip():
        raise FargateSmokeError(f"Fargate smoke requires the {name} override")
    return value.strip()


def _metadata_path(environ: Mapping[str, str]) -> str:
    endpoint = _required_environment(environ, "ECS_CONTAINER_METADATA_URI_V4")
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError as exc:
        raise FargateSmokeError("ECS metadata endpoint was malformed") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname != _METADATA_HOST
        or port not in (None, 80)
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.path.startswith("/v4/")
        or len(parsed.path) > 2048
        or parsed.query
        or parsed.fragment
    ):
        raise FargateSmokeError("ECS metadata endpoint was not the Fargate link-local endpoint")
    return f"{parsed.path.rstrip('/')}/task"


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_task_metadata(environ: Mapping[str, str] = os.environ) -> dict[str, Any]:
    path = _metadata_path(environ)
    connection = http.client.HTTPConnection(
        _METADATA_HOST,
        80,
        timeout=_METADATA_TIMEOUT_SECONDS,
    )
    try:
        connection.request("GET", path, headers={"Accept": "application/json"})
        response = connection.getresponse()
        payload = response.read(_MAX_METADATA_BYTES + 1)
    except (OSError, http.client.HTTPException) as exc:
        raise FargateSmokeError("Could not read ECS task metadata") from exc
    finally:
        connection.close()
    if response.status != 200:
        raise FargateSmokeError("ECS task metadata endpoint returned a non-200 status")
    if len(payload) > _MAX_METADATA_BYTES:
        raise FargateSmokeError("ECS task metadata exceeded the inspection limit")
    try:
        metadata = json.loads(payload, object_pairs_hook=_unique_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise FargateSmokeError("ECS task metadata was not unique-key JSON") from exc
    if not isinstance(metadata, dict):
        raise FargateSmokeError("ECS task metadata did not contain an object")
    return metadata


def _assert_task_metadata(
    metadata: Mapping[str, Any],
    environ: Mapping[str, str] = os.environ,
) -> None:
    expected_task_definition = _required_environment(environ, "ECS_TASK_DEFINITION")
    task_match = _TASK_DEFINITION.fullmatch(expected_task_definition)
    if task_match is None:
        raise FargateSmokeError("ECS_TASK_DEFINITION must be one exact revision")
    expected_image = _required_environment(environ, "ECS_EXPECTED_IMAGE_URI")
    image_match = _EXPECTED_IMAGE.fullmatch(expected_image)
    if image_match is None:
        raise FargateSmokeError("ECS_EXPECTED_IMAGE_URI must be one exact ECR digest URI")
    expected_container = _required_environment(environ, "ECS_CONTAINER_NAME")
    if _CONTAINER_NAME.fullmatch(expected_container) is None:
        raise FargateSmokeError("ECS_CONTAINER_NAME was invalid")
    expected_cluster = _required_environment(environ, "ECS_CLUSTER_NAME")
    if _CLUSTER_NAME.fullmatch(expected_cluster) is None:
        raise FargateSmokeError("ECS_CLUSTER_NAME was invalid")
    expected_account = _required_environment(environ, "AWS_ACCOUNT_ID")
    expected_region = _required_environment(environ, "AWS_REGION")
    if (
        _ACCOUNT_ID.fullmatch(expected_account) is None
        or _REGION.fullmatch(expected_region) is None
    ):
        raise FargateSmokeError("AWS account or region override was invalid")
    if (
        image_match.group("account") != expected_account
        or image_match.group("region") != expected_region
    ):
        raise FargateSmokeError("Expected image did not match the AWS account and region")
    if expected_task_definition.startswith("arn:"):
        expected_task_definition_arn = (
            f"arn:aws:ecs:{expected_region}:{expected_account}:task-definition/"
            f"{task_match.group('family')}:{task_match.group('revision')}"
        )
        if expected_task_definition != expected_task_definition_arn:
            raise FargateSmokeError("Worker task-definition ARN did not match AWS identity")
    if _required_environment(environ, "ECS_PLATFORM_VERSION") != "1.4.0":
        raise FargateSmokeError("ECS_PLATFORM_VERSION must be pinned to 1.4.0")

    cluster = metadata.get("Cluster")
    expected_cluster_arn = (
        f"arn:aws:ecs:{expected_region}:{expected_account}:cluster/{expected_cluster}"
    )
    if cluster not in {expected_cluster, expected_cluster_arn}:
        raise FargateSmokeError("Live task metadata did not match ECS_CLUSTER_NAME")
    task_arn = metadata.get("TaskARN")
    task_arn_prefix = f"arn:aws:ecs:{expected_region}:{expected_account}:task/{expected_cluster}/"
    task_id = task_arn.removeprefix(task_arn_prefix) if isinstance(task_arn, str) else ""
    if (
        not isinstance(task_arn, str)
        or not task_arn.startswith(task_arn_prefix)
        or re.fullmatch(r"[0-9a-f]{32}", task_id) is None
    ):
        raise FargateSmokeError("Live task metadata omitted a valid task ARN")
    if metadata.get("LaunchType") != "FARGATE":
        raise FargateSmokeError("Live task metadata did not report FARGATE launch type")
    if metadata.get("DesiredStatus") != "RUNNING" or metadata.get("KnownStatus") != "RUNNING":
        raise FargateSmokeError("Live task was not in RUNNING state during the probe")
    if metadata.get("Family") != task_match.group("family") or str(
        metadata.get("Revision")
    ) != task_match.group("revision"):
        raise FargateSmokeError("Live task metadata did not match the exact worker revision")

    containers = metadata.get("Containers")
    if not isinstance(containers, list):
        raise FargateSmokeError("Live task metadata omitted its containers")
    if any(
        not isinstance(container, dict) or not isinstance(container.get("Name"), str)
        for container in containers
    ):
        raise FargateSmokeError("Live task metadata contained a malformed container")
    application_containers = [
        container for container in containers if not container["Name"].startswith("~internal~")
    ]
    if len(application_containers) != 1:
        raise FargateSmokeError("Live task must contain exactly one application container")
    container = application_containers[0]
    if container.get("Name") != expected_container:
        raise FargateSmokeError("Live task metadata did not match ECS_CONTAINER_NAME")
    if container.get("Image") != expected_image:
        raise FargateSmokeError("Live task metadata did not match ECS_EXPECTED_IMAGE_URI")
    if container.get("ImageID") != image_match.group("digest"):
        raise FargateSmokeError("Live task image digest did not match the promoted digest")
    if container.get("DesiredStatus") != "RUNNING" or container.get("KnownStatus") != "RUNNING":
        raise FargateSmokeError("Live application container was not RUNNING during the probe")


def _assert_fargate_metadata() -> None:
    _assert_task_metadata(_read_task_metadata())


def _assert_chrome_no_sandbox(proc_root: Path = _PROC_ROOT) -> None:
    try:
        processes = sorted(
            (entry for entry in proc_root.iterdir() if entry.name.isdecimal()),
            key=lambda entry: int(entry.name),
        )
    except OSError as exc:
        raise FargateSmokeError("Could not enumerate runtime processes") from exc
    for process in processes:
        try:
            command_line = _read_bounded(
                process / "cmdline",
                label=f"process {process.name} command line",
            )
        except FargateSmokeError as exc:
            if isinstance(exc.__cause__, (FileNotFoundError, ProcessLookupError, PermissionError)):
                continue
            raise
        arguments = [part for part in command_line.split(b"\0") if part]
        if not arguments:
            continue
        executable_name = PurePosixPath(os.fsdecode(arguments[0])).name
        if executable_name not in _CHROME_EXECUTABLE_NAMES:
            continue
        if b"--no-sandbox" in arguments:
            return
    raise FargateSmokeError("No live Chrome process exposed the required --no-sandbox argument")


def run_fargate_smoke() -> None:
    """Prove the live task boundary and courts browser launch without AWS writes."""
    _assert_app_identity()
    _assert_process_security()
    _assert_mount_contract()
    _assert_no_chrome_sandbox_helper()
    _assert_no_visible_setid_files()
    _assert_dispatch_secret_absent()
    _assert_fargate_metadata()

    with UJSPortalScraper(max_attempts=1, errors="raise") as scraper:
        page = scraper.page
        if page is None:
            raise FargateSmokeError("UJS portal browser did not create a page")
        landing_selector = page.wait_for_selector(
            SEARCH_BY_DROPDOWN,
            state="visible",
            timeout=5_000,
        )
        if landing_selector is None:
            raise FargateSmokeError("UJS landing selector was not visible")
        scraper.assert_portal_origin()
        _assert_chrome_no_sandbox()
        scraper.assert_portal_origin()
