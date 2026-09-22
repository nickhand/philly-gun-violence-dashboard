"""Bind native Dependabot auto-merge eligibility to a verified, exact PR head.

Executed only from the trusted base checkout by the privileged policy workflow.
Never fetches, imports, installs, or runs pull-request code.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONTEXT = "Dependency merge policy"
REQUIRED_CHECKS = (
    "API quality gate",
    "ETL quality gate",
    "Frontend quality gate",
    "Dependency security gate",
    "CI routing and deployment contracts",
    CONTEXT,
)
PACKAGES = ("api", "etl", "dashboard-utils", "aws-batch-scraper")
ALLOWED_FILES = {
    "uv": {
        f"packages/{name}/{file}" for name in PACKAGES for file in ("pyproject.toml", "uv.lock")
    },
    "npm_and_yarn": {"frontend/package.json", "frontend/package-lock.json"},
    "docker": {"packages/api/Dockerfile", "packages/etl/Dockerfile"},
}
UPDATE_TYPES = frozenset({"version-update:semver-minor", "version-update:semver-patch"})


@dataclass(frozen=True)
class Decision:
    eligible: bool
    reason: str


def validate_identity(pr: Mapping[str, Any], repository: str, head: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ValueError("Expected head must be an exact commit SHA")
    if pr["head"]["sha"] != head:
        raise ValueError("PR head changed; a new policy run must evaluate it")
    if pr["base"]["repo"]["full_name"] != repository or pr["base"]["ref"] != "main":
        raise ValueError("Policy applies only to this repository's main branch")


def is_dependabot(pr: Mapping[str, Any]) -> bool:
    return pr["user"]["login"] == "dependabot[bot]" and pr["user"]["type"] == "Bot"


def evaluate(
    pr: Mapping[str, Any],
    files: Sequence[Mapping[str, Any]],
    dependencies: object,
    repository: str,
    head: str,
) -> Decision:
    validate_identity(pr, repository, head)
    if not is_dependabot(pr):
        return Decision(False, "Owner-managed PR; no automatic merge is requested")
    if pr["state"] != "open" or pr["draft"] is not False:
        return Decision(False, "Closed or draft PR")
    if pr["head"]["repo"] is None or pr["head"]["repo"]["full_name"] != repository:
        return Decision(False, "Dependabot head must belong to this repository")
    if not isinstance(dependencies, list) or not dependencies:
        return Decision(False, "Verified Dependabot metadata is unavailable")
    ecosystems = set()
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            return Decision(False, "Malformed dependency metadata")
        if (
            not isinstance(dependency.get("updateType"), str)
            or dependency["updateType"] not in UPDATE_TYPES
        ):
            return Decision(False, "Major or unclassified update requires a deliberate upgrade")
        if dependency.get("maintainerChanges") is not False:
            return Decision(False, "Maintainer changes require inspection")
        if (
            not isinstance(dependency.get("dependencyName"), str)
            or not dependency["dependencyName"]
        ):
            return Decision(False, "Dependency name is missing")
        ecosystem = dependency.get("packageEcosystem")
        if not isinstance(ecosystem, str):
            return Decision(False, "Dependency ecosystem is missing")
        ecosystems.add(ecosystem)
    if len(ecosystems) != 1:
        return Decision(False, "Mixed ecosystems require inspection")
    ecosystem = ecosystems.pop()
    paths = [file.get("filename") for file in files]
    if (
        type(pr.get("changed_files")) is not int
        or pr["changed_files"] != len(files)
        or not paths
        or any(not isinstance(path, str) for path in paths)
        or len(set(paths)) != len(paths)
    ):
        return Decision(False, "Complete changed-file inventory is required")
    for file in files:
        path = file["filename"]
        allowed = path in ALLOWED_FILES.get(ecosystem, set())
        if ecosystem == "github_actions":
            allowed = re.fullmatch(r"\.github/workflows/[a-z][a-z0-9-]*\.yml", path) is not None
        if not allowed or file.get("status") != "modified":
            return Decision(False, "Change includes files outside dependency maintenance")
    return Decision(True, "Verified minor/patch update; protected checks must pass")


def api(path: str, payload: Mapping[str, Any] | None = None) -> Any:
    command = ["gh", "api", path]
    if payload is not None:
        command += ["--method", "POST", "--input", "-"]
    result = subprocess.run(
        command,
        input=json.dumps(payload) if payload is not None else None,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout) if result.stdout.strip() else None


def status(repository: str, head: str, state: str, description: str) -> None:
    api(
        f"repos/{repository}/statuses/{head}",
        {"state": state, "context": CONTEXT, "description": description[:140]},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("begin", "finish"))
    args = parser.parse_args()
    repository = os.environ["GITHUB_REPOSITORY"]
    number = int(os.environ["PR_NUMBER"])
    if number <= 0 or re.fullmatch(r"[\w.-]+/[\w.-]+", repository) is None:
        raise ValueError("Invalid repository or PR number")
    snapshot = Path(os.environ["RUNNER_TEMP"]) / "dependency-policy-pr.json"
    pr = api(f"repos/{repository}/pulls/{number}")
    if args.phase == "begin":
        head = os.environ.get("EXPECTED_HEAD_SHA") or pr["head"]["sha"]
        validate_identity(pr, repository, head)
        if os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch" and is_dependabot(pr):
            raise ValueError("Dependabot requires its signed pull_request_target metadata event")
        snapshot.write_text(json.dumps(pr))
        status(repository, head, "pending", "Evaluating automatic merge policy for this commit")
        with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
            stream.write(f"dependabot={str(is_dependabot(pr)).lower()}\n")
        return

    previous = json.loads(snapshot.read_text())
    head = previous["head"]["sha"]
    validate_identity(pr, repository, head)
    # A queued request must never survive an ineligible replacement commit.
    if is_dependabot(pr) and pr.get("auto_merge") is not None:
        subprocess.run(
            ["gh", "pr", "merge", str(number), "--repo", repository, "--disable-auto"], check=True
        )
    files: list[Mapping[str, Any]] = []
    if is_dependabot(pr):
        for page in range(1, 32):
            batch = api(f"repos/{repository}/pulls/{number}/files?per_page=100&page={page}")
            if not isinstance(batch, list):
                raise ValueError("Malformed changed-file response")
            files.extend(batch)
            if len(batch) < 100:
                break
    dependencies = json.loads(os.environ.get("DEPENDENCIES_JSON") or "[]")
    decision = evaluate(pr, files, dependencies, repository, head)
    # The required status means policy was enforced. Ineligible updates remain
    # manually mergeable after tests, with any old auto-merge request removed.
    status(repository, head, "success", decision.reason)
    if decision.eligible:
        subprocess.run(
            [
                "gh",
                "pr",
                "merge",
                str(number),
                "--repo",
                repository,
                "--auto",
                "--squash",
                "--match-head-commit",
                head,
            ],
            check=True,
        )
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as stream:
        stream.write(f"PR #{number}: {decision.reason}.\n")


if __name__ == "__main__":
    main()
