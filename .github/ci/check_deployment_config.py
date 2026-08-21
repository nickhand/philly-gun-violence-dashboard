#!/usr/bin/env python3
"""Validate the small set of deployment configuration invariants."""

from __future__ import annotations

import json
import shlex
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import tomllib

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class ConfigurationError(ValueError):
    """A checked-in deployment configuration violates its runtime contract."""


def _load(name: str) -> dict[str, object]:
    with (REPOSITORY_ROOT / name).open("rb") as stream:
        return tomllib.load(stream)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ConfigurationError(message)


def _table(value: object, message: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ConfigurationError(message)
    return cast(dict[str, object], value)


def _tables(value: object, message: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ConfigurationError(message)
    return [cast(dict[str, object], item) for item in value]


def _docker_instructions(source: str) -> Iterator[str]:
    """Yield logical Dockerfile instructions with continuations joined."""
    pending = ""
    for raw_line in source.splitlines():
        if raw_line.lstrip().lower().startswith("# escape="):
            directive = raw_line.split("=", maxsplit=1)[1].strip()
            if directive != "\\":
                raise ConfigurationError("non-default Dockerfile escape directives are forbidden")
        line = raw_line.rstrip()
        if line.endswith("\\"):
            pending += f"{line[:-1]} "
            continue
        logical = f"{pending}{line}".strip()
        pending = ""
        if logical and not logical.startswith("#"):
            yield logical
    if pending:
        raise ConfigurationError("Dockerfile ends with an incomplete continuation")


def _local_docker_mappings(source: str) -> tuple[tuple[str, str], ...]:
    """Return local COPY/ADD source-destination pairs and reject hidden inputs."""
    local_mappings: list[tuple[str, str]] = []
    for line in _docker_instructions(source):
        instruction, separator, arguments = line.partition(" ")
        if instruction.upper() == "RUN":
            try:
                run_tokens = shlex.split(arguments)
            except ValueError as exc:
                raise ConfigurationError("invalid RUN instruction") from exc
            for token in run_tokens:
                if not token.startswith("--mount="):
                    continue
                settings = {
                    key: value
                    for item in token.removeprefix("--mount=").split(",")
                    for key, separator, value in (item.partition("="),)
                    if separator
                }
                if settings.get("type", "bind") != "cache":
                    raise ConfigurationError(
                        "only literal cache RUN mounts are allowed; other mounts can hide inputs"
                    )
            continue
        if instruction.upper() not in {"ADD", "COPY"}:
            continue
        if not separator or not arguments.strip():
            raise ConfigurationError(f"malformed {instruction.upper()} instruction")

        arguments = arguments.strip()
        flags: list[str] = []
        while arguments.startswith("--"):
            flag, separator, remainder = arguments.partition(" ")
            if not separator or "=" not in flag:
                raise ConfigurationError(f"unsupported {instruction.upper()} flag: {flag}")
            flags.append(flag)
            arguments = remainder.lstrip()
        if arguments.startswith("["):
            try:
                values = json.loads(arguments)
            except json.JSONDecodeError as exc:
                raise ConfigurationError(f"invalid JSON-form {instruction.upper()}") from exc
            if (
                not isinstance(values, list)
                or len(values) < 2
                or not all(isinstance(value, str) for value in values)
            ):
                raise ConfigurationError(f"invalid JSON-form {instruction.upper()}")
            tokens = cast(list[str], values)
        else:
            try:
                tokens = shlex.split(arguments)
            except ValueError as exc:
                raise ConfigurationError(f"invalid shell-form {instruction.upper()}") from exc
            if len(tokens) < 2:
                raise ConfigurationError(f"malformed {instruction.upper()} instruction")
        if any(flag.startswith("--from=") for flag in flags):
            continue

        destination = tokens[-1]
        for item in tokens[:-1]:
            if instruction.upper() == "ADD" and item.startswith(("https://", "http://")):
                continue
            local_mappings.append((item, destination))
    return tuple(local_mappings)


def _local_docker_sources(source: str) -> tuple[str, ...]:
    """Return every local COPY/ADD source and fail on unsupported syntax."""
    return tuple(item for item, _destination in _local_docker_mappings(source))


def check_fly_api() -> None:
    config = _load("fly.toml")
    _require(config.get("app") == "philly-gun-violence-dashboard-api", "unexpected Fly API app")
    _require(
        config.get("build") == {"dockerfile": "packages/api/Dockerfile"}, "unexpected API build"
    )
    processes = _table(config.get("processes"), "API processes must be a table")
    _require(set(processes) == {"app"}, "API must have only app process")
    _require("uvicorn app.main:app" in str(processes["app"]), "API process must launch app.main")
    machines = _tables(config.get("vm"), "API VM configuration must be a table list")
    _require(len(machines) == 1, "API must declare one VM contract")
    _require(machines[0].get("memory") == "1gb", "API rollover requires 1 GB memory")
    service = _table(config.get("http_service"), "API HTTP service must be a table")
    _require(
        service.get("processes") == ["app"],
        "HTTP service must use app",
    )
    checks = _tables(service.get("checks"), "API health checks must be a table list")
    _require(len(checks) == 1, "API must have one health check")
    _require(checks[0].get("path") == "/health", "API health check must use /health")


def check_fly_scheduler() -> None:
    config = _load("fly.scheduler.toml")
    _require(
        config.get("app") == "philly-gun-violence-dashboard-scheduler",
        "unexpected Fly scheduler app",
    )
    _require(
        config.get("build") == {"dockerfile": "packages/api/Dockerfile"},
        "unexpected scheduler build",
    )
    _require(
        config.get("deploy") == {"strategy": "immediate"}, "scheduler deploy must be immediate"
    )
    processes = _table(config.get("processes"), "scheduler processes must be a table")
    _require(
        processes == {"cron": "supercronic /app/api/crontab"},
        "scheduler must have only the reviewed cron process",
    )
    machines = _tables(config.get("vm"), "scheduler VM configuration must be a table list")
    _require(len(machines) == 1, "scheduler must declare one VM contract")
    _require(machines[0].get("processes") == ["cron"], "scheduler VM must run cron only")
    _require(machines[0].get("memory") == "256mb", "scheduler VM must remain 256 MB")
    _require("http_service" not in config, "scheduler must not expose an HTTP service")


def check_runtime_docker_inputs() -> None:
    api = (REPOSITORY_ROOT / "packages/api/Dockerfile").read_text()
    scraper = (REPOSITORY_ROOT / "packages/etl/Dockerfile").read_text()

    allowed_api_sources = {
        "packages/api/app/",
        "packages/api/crontab",
        "packages/api/pyproject.toml",
        "packages/api/scripts/",
        "packages/api/uv.lock",
        "packages/dashboard-utils/pyproject.toml",
        "packages/dashboard-utils/src/",
        "packages/dashboard-utils/uv.lock",
    }
    allowed_scraper_sources = {
        "packages/aws-batch-scraper/pyproject.toml",
        "packages/aws-batch-scraper/src/",
        "packages/aws-batch-scraper/uv.lock",
        "packages/dashboard-utils/pyproject.toml",
        "packages/dashboard-utils/src/",
        "packages/dashboard-utils/uv.lock",
        "packages/etl/pyproject.toml",
        "packages/etl/src/",
        "packages/etl/uv.lock",
    }
    for name, source, allowed in (
        ("API", api, allowed_api_sources),
        ("scraper", scraper, allowed_scraper_sources),
    ):
        unexpected = sorted(set(_local_docker_sources(source)) - allowed)
        _require(not unexpected, f"{name} image has untracked local inputs: {unexpected}")

    for name, source, required in (
        (
            "API",
            api,
            {
                ("packages/api/app/", "/app/api/app/"),
                ("packages/api/scripts/", "/app/api/scripts/"),
                ("packages/api/crontab", "/app/api/crontab"),
            },
        ),
        (
            "scraper",
            scraper,
            {
                ("packages/etl/src/", "/app/etl/src/"),
                ("packages/dashboard-utils/src/", "/app/dashboard-utils/src/"),
                (
                    "packages/aws-batch-scraper/src/",
                    "/app/aws-batch-scraper/src/",
                ),
            },
        ),
    ):
        missing = sorted(required - set(_local_docker_mappings(source)))
        _require(not missing, f"{name} image is missing runtime inputs: {missing}")


def check_package_metadata_inputs() -> None:
    for relative_path in (
        "packages/api/README.md",
        "packages/aws-batch-scraper/README.md",
        "packages/dashboard-utils/README.md",
        "packages/etl/README.md",
    ):
        path = REPOSITORY_ROOT / relative_path
        _require(path.is_file(), f"package metadata input is missing: {relative_path}")
        _require(
            bool(path.read_text().strip()), f"package metadata input is empty: {relative_path}"
        )


def main() -> int:
    try:
        check_fly_api()
        check_fly_scheduler()
        check_runtime_docker_inputs()
        check_package_metadata_inputs()
    except (ConfigurationError, OSError, tomllib.TOMLDecodeError, TypeError) as exc:
        print(f"Deployment configuration check failed: {exc}", file=sys.stderr)
        return 1
    print("Deployment configuration contracts are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
