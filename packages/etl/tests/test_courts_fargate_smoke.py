"""Tests for the one-shot, fail-closed courts Fargate runtime probe."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from etl.courts import cli
from etl.courts import fargate_smoke as smoke


def _valid_proc_status() -> bytes:
    return b"Seccomp:\t2\nCapEff:\t0000000000000000\nCapPrm:\t0\nCapBnd:\t00000000\n"


def _valid_mountinfo() -> bytes:
    return (
        b"29 1 0:1 / / ro,relatime - overlay overlay ro\n"
        b"30 29 0:2 / /tmp rw,nosuid,nodev - tmpfs tmpfs rw\n"
    )


def _metadata_environment() -> dict[str, str]:
    return {
        "ECS_CONTAINER_METADATA_URI_V4": "http://169.254.170.2/v4/task-id",
        "AWS_ACCOUNT_ID": "123456789012",
        "AWS_REGION": "us-east-1",
        "ECS_CLUSTER_NAME": "ujs-scraper",
        "ECS_TASK_DEFINITION": "ujs-scraper:42",
        "ECS_EXPECTED_IMAGE_URI": (
            "123456789012.dkr.ecr.us-east-1.amazonaws.com/ujs-scraper@sha256:" + "a" * 64
        ),
        "ECS_CONTAINER_NAME": "ujs-scraper",
        "ECS_PLATFORM_VERSION": "1.4.0",
    }


def _task_metadata() -> dict[str, object]:
    environment = _metadata_environment()
    return {
        "Cluster": "arn:aws:ecs:us-east-1:123456789012:cluster/ujs-scraper",
        "TaskARN": (
            "arn:aws:ecs:us-east-1:123456789012:task/ujs-scraper/0123456789abcdef0123456789abcdef"
        ),
        "Family": "ujs-scraper",
        "Revision": "42",
        "DesiredStatus": "RUNNING",
        "KnownStatus": "RUNNING",
        "LaunchType": "FARGATE",
        "Containers": [
            {"Name": "~internal~ecs~pause"},
            {
                "Name": "ujs-scraper",
                "Image": environment["ECS_EXPECTED_IMAGE_URI"],
                "ImageID": "sha256:" + "a" * 64,
                "DesiredStatus": "RUNNING",
                "KnownStatus": "RUNNING",
            },
        ],
    }


def test_app_identity_requires_consistent_nonroot_app_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke.os, "getuid", lambda: 999)
    monkeypatch.setattr(smoke.os, "geteuid", lambda: 999)
    monkeypatch.setattr(smoke.pwd, "getpwuid", lambda _uid: SimpleNamespace(pw_name="app"))

    smoke._assert_app_identity()

    monkeypatch.setattr(smoke.os, "geteuid", lambda: 0)
    with pytest.raises(smoke.FargateSmokeError, match="non-root"):
        smoke._assert_app_identity()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (b"Seccomp:\t0", "seccomp"),
        (b"CapEff:\t0001", "capabilities"),
        (b"CapPrm:\t0001", "capabilities"),
        (b"CapBnd:\t0001", "capabilities"),
    ],
)
def test_process_security_requires_filter_and_zero_capability_sets(
    monkeypatch: pytest.MonkeyPatch,
    mutation: bytes,
    message: str,
) -> None:
    valid = _valid_proc_status()
    field = mutation.split(b":", maxsplit=1)[0]
    payload = b"\n".join(
        mutation if line.startswith(field + b":") else line for line in valid.splitlines()
    )
    monkeypatch.setattr(smoke, "_read_bounded", lambda *_args, **_kwargs: payload)

    with pytest.raises(smoke.FargateSmokeError, match=message):
        smoke._assert_process_security()


def test_process_security_accepts_exact_runtime_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "_read_bounded",
        lambda *_args, **_kwargs: _valid_proc_status(),
    )

    smoke._assert_process_security()


def test_mount_contract_requires_readonly_root_and_separate_sticky_tmp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "_read_bounded",
        lambda *_args, **_kwargs: _valid_mountinfo(),
    )
    monkeypatch.setattr(
        smoke.os,
        "statvfs",
        lambda path: SimpleNamespace(f_flag=os.ST_RDONLY if path == "/" else 0),
    )
    monkeypatch.setattr(
        smoke.os,
        "lstat",
        lambda _path: SimpleNamespace(st_mode=stat.S_IFDIR | 0o1777),
    )

    smoke._assert_mount_contract()

    monkeypatch.setattr(
        smoke.os,
        "lstat",
        lambda _path: SimpleNamespace(st_mode=stat.S_IFDIR | 0o755),
    )
    with pytest.raises(smoke.FargateSmokeError, match="mode 1777"):
        smoke._assert_mount_contract()


def test_mount_contract_rejects_tmp_on_root_mount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = (
        b"29 1 0:1 / / ro,relatime - overlay overlay ro\n29 1 0:1 / /tmp rw - overlay overlay rw\n"
    )
    monkeypatch.setattr(smoke, "_read_bounded", lambda *_args, **_kwargs: payload)

    with pytest.raises(smoke.FargateSmokeError, match="separate"):
        smoke._assert_mount_contract()


def test_setid_find_is_bounded_no_shell_and_fails_on_output_or_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(smoke.subprocess, "run", run)
    smoke._assert_no_visible_setid_files()

    command, kwargs = calls[0]
    assert command[0] == "/usr/bin/find"
    assert "-xdev" in command
    assert "/6000" in command
    assert kwargs["timeout"] == 120
    assert "shell" not in kwargs

    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout=b"/usr/bin/example\n",
            stderr=b"",
        ),
    )
    with pytest.raises(smoke.FargateSmokeError, match="setuid/setgid file"):
        smoke._assert_no_visible_setid_files()

    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            command,
            1,
            stdout=b"",
            stderr=b"find: permission denied\n",
        ),
    )
    with pytest.raises(smoke.FargateSmokeError, match="returned an error"):
        smoke._assert_no_visible_setid_files()


def test_chrome_process_must_expose_exact_no_sandbox_argument(tmp_path: Path) -> None:
    process = tmp_path / "42"
    process.mkdir()
    (process / "cmdline").write_bytes(b"/opt/google/chrome/chrome\0--headless\0--no-sandbox\0")

    smoke._assert_chrome_no_sandbox(tmp_path)

    (process / "cmdline").write_bytes(b"/opt/google/chrome/chrome\0--headless\0")
    with pytest.raises(smoke.FargateSmokeError, match="--no-sandbox"):
        smoke._assert_chrome_no_sandbox(tmp_path)

    (process / "cmdline").write_bytes(b"python\0--no-sandbox\0")
    with pytest.raises(smoke.FargateSmokeError, match="--no-sandbox"):
        smoke._assert_chrome_no_sandbox(tmp_path)


def test_dispatch_secret_must_be_absent_even_when_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_DISPATCH_TOKEN", raising=False)
    smoke._assert_dispatch_secret_absent()

    monkeypatch.setenv("GITHUB_DISPATCH_TOKEN", "")
    with pytest.raises(smoke.FargateSmokeError, match="must not contain"):
        smoke._assert_dispatch_secret_absent()


def test_fargate_metadata_binds_live_task_revision_container_and_digest() -> None:
    environment = _metadata_environment()

    smoke._assert_task_metadata(_task_metadata(), environment)

    wrong_digest = _task_metadata()
    containers = wrong_digest["Containers"]
    assert isinstance(containers, list)
    assert isinstance(containers[1], dict)
    containers[1]["ImageID"] = "sha256:" + "b" * 64
    with pytest.raises(smoke.FargateSmokeError, match="image digest"):
        smoke._assert_task_metadata(wrong_digest, environment)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("LaunchType", "EC2", "FARGATE"),
        ("Revision", "41", "worker revision"),
        ("KnownStatus", "STOPPED", "RUNNING"),
    ],
)
def test_fargate_metadata_rejects_wrong_control_plane_identity(
    field: str,
    value: str,
    message: str,
) -> None:
    metadata = _task_metadata()
    metadata[field] = value

    with pytest.raises(smoke.FargateSmokeError, match=message):
        smoke._assert_task_metadata(metadata, _metadata_environment())


def test_metadata_endpoint_is_exact_link_local_v4_path() -> None:
    environment = _metadata_environment()
    assert smoke._metadata_path(environment) == "/v4/task-id/task"

    environment["ECS_CONTAINER_METADATA_URI_V4"] = "http://example.com/v4/task-id"
    with pytest.raises(smoke.FargateSmokeError, match="link-local"):
        smoke._metadata_path(environment)


def test_fargate_smoke_checks_portal_and_chrome_while_browser_is_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    browser_open = False

    for name in (
        "_assert_app_identity",
        "_assert_process_security",
        "_assert_mount_contract",
        "_assert_no_chrome_sandbox_helper",
        "_assert_no_visible_setid_files",
        "_assert_dispatch_secret_absent",
        "_assert_fargate_metadata",
    ):
        monkeypatch.setattr(smoke, name, lambda name=name: events.append(name))

    page = MagicMock()
    page.wait_for_selector.return_value = object()

    class FakeScraper:
        def __init__(self, *, max_attempts: int, errors: str) -> None:
            assert max_attempts == 1
            assert errors == "raise"
            self.page = page

        def __enter__(self) -> FakeScraper:
            nonlocal browser_open
            browser_open = True
            events.append("browser-enter")
            return self

        def assert_portal_origin(self) -> None:
            assert browser_open
            events.append("origin")

        def __exit__(self, *_args: object) -> None:
            nonlocal browser_open
            browser_open = False
            events.append("browser-exit")

    def assert_chrome() -> None:
        assert browser_open
        events.append("chrome")

    monkeypatch.setattr(smoke, "UJSPortalScraper", FakeScraper)
    monkeypatch.setattr(smoke, "_assert_chrome_no_sandbox", assert_chrome)

    smoke.run_fargate_smoke()

    page.wait_for_selector.assert_called_once_with(
        "#SearchBy-Control select",
        state="visible",
        timeout=5_000,
    )
    assert events[-5:] == ["browser-enter", "origin", "chrome", "origin", "browser-exit"]


def test_fargate_smoke_cli_emits_marker_once_and_only_after_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "run_fargate_smoke", lambda: None)

    result = CliRunner().invoke(cli.app, ["fargate-smoke"])

    assert result.exit_code == 0
    assert result.output.strip() == smoke.FARGATE_SMOKE_SUCCESS_MARKER
    assert result.output.count(smoke.FARGATE_SMOKE_SUCCESS_MARKER) == 1

    def fail() -> None:
        raise smoke.FargateSmokeError("contract failed")

    monkeypatch.setattr(cli, "run_fargate_smoke", fail)
    failed = CliRunner().invoke(cli.app, ["fargate-smoke"])
    assert failed.exit_code != 0
    assert smoke.FARGATE_SMOKE_SUCCESS_MARKER not in failed.output
