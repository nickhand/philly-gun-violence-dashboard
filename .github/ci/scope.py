#!/usr/bin/env python3
"""Classify changed repository paths into the CI jobs that must run."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import PurePosixPath

ROUTER_PATH = ".github/ci/scope.py"

CONFIG_TRIGGERS = (
    ".github/ci/**",
    ".github/workflows/**",
    "README.md",
    "packages/api/Dockerfile",
    "packages/api/README.md",
    "packages/api/crontab",
    "packages/api/just/api.just",
    "packages/api/scripts/dispatch_workflow.py",
    "packages/aws-batch-scraper/README.md",
    "packages/dashboard-utils/README.md",
    "packages/etl/Dockerfile",
    "packages/etl/README.md",
    "fly.toml",
    "fly.scheduler.toml",
    "netlify.toml",
)

TRIGGERS: dict[str, tuple[str, ...]] = {
    "api": (
        "packages/api/**",
        "packages/dashboard-utils/**",
        ".dockerignore",
        "ruff.toml",
        "ty.toml",
        "uv.toml",
        ".github/workflows/api-quality.yml",
        ROUTER_PATH,
    ),
    "etl": (
        "packages/etl/**",
        "packages/dashboard-utils/**",
        "packages/aws-batch-scraper/**",
        ".dockerignore",
        "Justfile",
        "ruff.toml",
        "ty.toml",
        "uv.toml",
        ".github/workflows/daily-homicide-sync.yml",
        ".github/workflows/etl-quality.yml",
        ".github/workflows/production-smoke.yml",
        ROUTER_PATH,
    ),
    "frontend": (
        "frontend/**",
        ".github/workflows/frontend-quality.yml",
        ROUTER_PATH,
    ),
    "security": (
        "packages/api/pyproject.toml",
        "packages/api/uv.lock",
        "packages/etl/pyproject.toml",
        "packages/etl/uv.lock",
        "packages/dashboard-utils/pyproject.toml",
        "packages/dashboard-utils/uv.lock",
        "packages/aws-batch-scraper/pyproject.toml",
        "packages/aws-batch-scraper/uv.lock",
        "frontend/package-lock.json",
        "frontend/package.json",
        "uv.toml",
        ".github/workflows/security-quality.yml",
        ROUTER_PATH,
    ),
}

NO_JOB_PATTERNS: dict[str, tuple[str, ...]] = {
    "api": (
        "packages/api/README.md",
        "packages/api/just/**",
        "packages/dashboard-utils/.python-version",
        "packages/dashboard-utils/README.md",
        "packages/dashboard-utils/ruff.toml",
        "packages/dashboard-utils/tests/**",
    ),
    "etl": (
        "packages/etl/README.md",
        "packages/etl/just/**",
        "packages/dashboard-utils/README.md",
        "packages/aws-batch-scraper/README.md",
        "packages/aws-batch-scraper/docs/**",
    ),
    "frontend": (
        "frontend/.env.example",
        "frontend/ACCESSIBILITY.md",
        "frontend/NUXT_LEARNING.md",
        "frontend/README.md",
        "frontend/just/**",
        "frontend/layers/civic-ui/README.md",
    ),
    "security": (),
}

GROUPS: dict[str, dict[str, tuple[str, ...]]] = {
    "api": {
        "checks": (
            "packages/api/app/**",
            "packages/api/scripts/**",
            "packages/api/tests/**",
            "packages/api/.python-version",
            "packages/api/pyproject.toml",
            "packages/api/ruff.toml",
            "packages/api/uv.lock",
            "packages/dashboard-utils/src/**",
            "packages/dashboard-utils/pyproject.toml",
            "packages/dashboard-utils/uv.lock",
            "ruff.toml",
            "ty.toml",
            "uv.toml",
        ),
        "image": (
            "packages/api/app/**",
            "packages/api/scripts/**",
            "packages/api/Dockerfile",
            "packages/api/crontab",
            "packages/api/pyproject.toml",
            "packages/api/uv.lock",
            "packages/dashboard-utils/src/**",
            "packages/dashboard-utils/pyproject.toml",
            "packages/dashboard-utils/uv.lock",
            ".dockerignore",
        ),
    },
    "etl": {
        "etl": (
            "packages/etl/src/**",
            "packages/etl/tests/**",
            "packages/etl/Dockerfile",
            "packages/etl/.python-version",
            "packages/etl/pyproject.toml",
            "packages/etl/ruff.toml",
            "packages/etl/uv.lock",
            "packages/dashboard-utils/src/**",
            "packages/dashboard-utils/pyproject.toml",
            "packages/dashboard-utils/uv.lock",
            "packages/aws-batch-scraper/src/**",
            "packages/aws-batch-scraper/examples/simple_scraper/**",
            "packages/aws-batch-scraper/just/aws-batch-scraper.just",
            "packages/aws-batch-scraper/pyproject.toml",
            "packages/aws-batch-scraper/uv.lock",
            "Justfile",
            "ruff.toml",
            "ty.toml",
            "uv.toml",
            ".github/workflows/daily-homicide-sync.yml",
            ".github/workflows/production-smoke.yml",
        ),
        "dashboard": (
            "packages/dashboard-utils/.python-version",
            "packages/dashboard-utils/src/**",
            "packages/dashboard-utils/tests/**",
            "packages/dashboard-utils/pyproject.toml",
            "packages/dashboard-utils/ruff.toml",
            "packages/dashboard-utils/uv.lock",
            "ruff.toml",
            "ty.toml",
            "uv.toml",
        ),
        "scraper": (
            "packages/aws-batch-scraper/src/**",
            "packages/aws-batch-scraper/tests/**",
            "packages/aws-batch-scraper/examples/docker/**",
            "packages/aws-batch-scraper/just/aws-batch-scraper.just",
            "packages/aws-batch-scraper/pyproject.toml",
            "packages/aws-batch-scraper/uv.lock",
            "ruff.toml",
            "ty.toml",
            "uv.toml",
        ),
        "image": (
            "packages/etl/src/**",
            "packages/etl/Dockerfile",
            "packages/etl/pyproject.toml",
            "packages/etl/uv.lock",
            "packages/dashboard-utils/src/**",
            "packages/dashboard-utils/pyproject.toml",
            "packages/dashboard-utils/uv.lock",
            "packages/aws-batch-scraper/src/**",
            "packages/aws-batch-scraper/pyproject.toml",
            "packages/aws-batch-scraper/uv.lock",
            ".dockerignore",
        ),
    },
    "frontend": {
        "release": (
            "frontend/app/**",
            "frontend/config/**",
            "frontend/layers/civic-ui/app/**",
            "frontend/layers/civic-ui/nuxt.config.ts",
            "frontend/public/**",
            "frontend/server/**",
            "frontend/shared/**",
            "frontend/src/**",
            "frontend/scripts/check-cloudflare-output.mjs",
            "frontend/scripts/prepare-cloudflare-output.mjs",
            "frontend/nuxt.config.ts",
            "frontend/package-lock.json",
            "frontend/package.json",
            "frontend/tsconfig.json",
            "frontend/tsconfig.node.json",
            "frontend/wrangler.jsonc",
        ),
        "unit": (
            "frontend/app/**",
            "frontend/config/**",
            "frontend/layers/civic-ui/app/**",
            "frontend/public/**",
            "frontend/scripts/check-bundle-size.mjs",
            "frontend/scripts/check-cloudflare-output.mjs",
            "frontend/scripts/generate-seo-content.mjs",
            "frontend/scripts/lighthouse-policy.mjs",
            "frontend/scripts/prepare-cloudflare-output.mjs",
            "frontend/server/**",
            "frontend/shared/**",
            "frontend/src/**",
            "frontend/tests/fixtures/**",
            "frontend/tests/e2e/**",
            "frontend/tests/lighthouse-policy.test.mjs",
            "frontend/tests/seo/**",
            "frontend/tests/setup.ts",
            "frontend/tests/unit/**",
            "frontend/tests/vue-shim.d.ts",
            "frontend/index.html",
            "frontend/layers/civic-ui/nuxt.config.ts",
            "frontend/nuxt.config.ts",
            "frontend/package-lock.json",
            "frontend/package.json",
            "frontend/playwright.config.ts",
            "frontend/tsconfig.json",
            "frontend/tsconfig.node.json",
            "frontend/tsconfig.tests.json",
            "frontend/vite.legacy.config.ts",
            "frontend/vitest.config.ts",
            "frontend/wrangler.jsonc",
        ),
        "browser": (
            "frontend/app/**",
            "frontend/config/**",
            "frontend/layers/civic-ui/app/**",
            "frontend/public/**",
            "frontend/server/**",
            "frontend/shared/**",
            "frontend/src/**",
            "frontend/tests/e2e/**",
            "frontend/tests/fixtures/**",
            "frontend/index.html",
            "frontend/layers/civic-ui/nuxt.config.ts",
            "frontend/nuxt.config.ts",
            "frontend/package-lock.json",
            "frontend/package.json",
            "frontend/playwright.config.ts",
            "frontend/playwright.nuxt.config.ts",
            "frontend/vite.legacy.config.ts",
        ),
        "lighthouse": (
            "frontend/public/**",
            "frontend/scripts/lighthouse-policy.mjs",
            "frontend/scripts/run-lighthouse.mjs",
            "frontend/scripts/serve-lighthouse.mjs",
            "frontend/src/**",
            "frontend/index.html",
            "frontend/package-lock.json",
            "frontend/package.json",
            "frontend/vite.legacy.config.ts",
        ),
    },
    "security": {
        "api": (
            "packages/api/pyproject.toml",
            "packages/api/uv.lock",
            "uv.toml",
        ),
        "etl": (
            "packages/etl/pyproject.toml",
            "packages/etl/uv.lock",
            "uv.toml",
        ),
        "dashboard": (
            "packages/dashboard-utils/pyproject.toml",
            "packages/dashboard-utils/uv.lock",
            "uv.toml",
        ),
        "scraper": (
            "packages/aws-batch-scraper/pyproject.toml",
            "packages/aws-batch-scraper/uv.lock",
            "uv.toml",
        ),
        "frontend": (
            "frontend/package-lock.json",
            "frontend/package.json",
        ),
    },
}


def _normalize_path(value: str) -> str:
    path = PurePosixPath(value.strip())
    if not value.strip() or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe or empty repository path: {value!r}")
    return path.as_posix().removeprefix("./")


def path_matches(path: str, pattern: str) -> bool:
    """Match the deliberately small exact-or-directory CI pattern language."""
    normalized = _normalize_path(path)
    if pattern.endswith("/**"):
        prefix = pattern.removesuffix("/**")
        return normalized.startswith(f"{prefix}/")
    return normalized == pattern


def classify(workflow: str, paths: Iterable[str], *, force_all: bool = False) -> dict[str, bool]:
    """Return the jobs needed for one workflow and a collection of changed paths."""
    try:
        groups = GROUPS[workflow]
    except KeyError as exc:
        raise ValueError(f"unknown workflow scope: {workflow}") from exc

    if force_all:
        return dict.fromkeys(groups, True)

    normalized_paths = tuple(_normalize_path(path) for path in paths)
    router_changed = ROUTER_PATH in normalized_paths
    workflow_changed = f".github/workflows/{workflow}-quality.yml" in normalized_paths
    if router_changed or workflow_changed:
        return dict.fromkeys(groups, True)

    decisions = {
        name: any(path_matches(path, pattern) for path in normalized_paths for pattern in patterns)
        for name, patterns in groups.items()
    }
    unrouted_trigger = any(
        any(path_matches(path, pattern) for pattern in TRIGGERS[workflow])
        and not any(path_matches(path, pattern) for pattern in NO_JOB_PATTERNS[workflow])
        and not any(
            path_matches(path, pattern) for patterns in groups.values() for pattern in patterns
        )
        for path in normalized_paths
    )
    if unrouted_trigger:
        return dict.fromkeys(groups, True)
    return decisions


def _git_paths(arguments: Sequence[str]) -> tuple[str, ...]:
    process = subprocess.run(
        ["git", *arguments],
        check=True,
        capture_output=True,
    )
    return tuple(
        entry.decode("utf-8", errors="strict") for entry in process.stdout.split(b"\0") if entry
    )


def changed_paths(*, event: str, before: str, base: str, head: str) -> tuple[str, ...]:
    """Read the exact changed paths for a supported GitHub event."""
    if event in {"schedule", "workflow_dispatch"}:
        return ()
    if event == "pull_request":
        if not base or not head:
            raise ValueError("pull_request routing requires base and head SHAs")
        return _git_paths(("diff", "--no-renames", "--name-only", "-z", f"{base}...{head}"))
    if event == "push":
        if not head:
            raise ValueError("push routing requires the head SHA")
        if before and set(before) != {"0"}:
            return _git_paths(("diff", "--no-renames", "--name-only", "-z", before, head))
        return _git_paths(
            (
                "diff-tree",
                "--no-renames",
                "--root",
                "--no-commit-id",
                "--name-only",
                "-z",
                "-r",
                head,
            )
        )
    raise ValueError(f"unsupported GitHub event: {event}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", choices=sorted(GROUPS), required=True)
    parser.add_argument("--event", required=True)
    parser.add_argument("--before", default="")
    parser.add_argument("--base", default="")
    parser.add_argument("--head", default="")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    force_all = args.event in {"schedule", "workflow_dispatch"}
    try:
        paths = changed_paths(
            event=args.event,
            before=args.before,
            base=args.base,
            head=args.head,
        )
        decisions = classify(args.workflow, paths, force_all=force_all)
    except (OSError, subprocess.CalledProcessError, UnicodeError, ValueError) as exc:
        print(f"CI routing failed closed: {exc}", file=sys.stderr)
        return 2

    for name, enabled in decisions.items():
        print(f"{name}={'true' if enabled else 'false'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
