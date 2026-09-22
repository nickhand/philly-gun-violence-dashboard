"""Regression coverage for unattended merging and stale auto-merge requests."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import dependabot_policy as policy

REPOSITORY = "nickhand/philly-gun-violence-dashboard"
HEAD = "a" * 40


def pull_request() -> dict[str, Any]:
    return {
        "user": {"login": "dependabot[bot]", "type": "Bot"},
        "head": {"sha": HEAD, "repo": {"full_name": REPOSITORY}},
        "base": {"ref": "main", "repo": {"full_name": REPOSITORY}},
        "state": "open",
        "draft": False,
        "changed_files": 2,
        "auto_merge": None,
    }


def dependency() -> dict[str, Any]:
    return {
        "dependencyName": "pytest",
        "updateType": "version-update:semver-minor",
        "packageEcosystem": "uv",
        "maintainerChanges": False,
    }


FILES = [
    {"filename": "packages/api/pyproject.toml", "status": "modified"},
    {"filename": "packages/api/uv.lock", "status": "modified"},
]


class DependabotPolicyTests(unittest.TestCase):
    def decide(self, pr=None, files=None, dependencies=None):
        return policy.evaluate(
            pull_request() if pr is None else pr,
            FILES if files is None else files,
            [dependency()] if dependencies is None else dependencies,
            REPOSITORY,
            HEAD,
        )

    def test_supported_dependency_files_and_minor_patch_updates(self) -> None:
        for ecosystem, paths in (
            ("uv", ["packages/api/uv.lock", "packages/etl/uv.lock"]),
            ("npm_and_yarn", ["frontend/package.json", "frontend/package-lock.json"]),
            ("docker", ["packages/api/Dockerfile", "packages/etl/Dockerfile"]),
            (
                "github_actions",
                [".github/workflows/api-quality.yml", ".github/workflows/etl-quality.yml"],
            ),
        ):
            for update_type in policy.UPDATE_TYPES:
                with self.subTest(ecosystem=ecosystem, update_type=update_type):
                    metadata = dependency() | {
                        "packageEcosystem": ecosystem,
                        "updateType": update_type,
                    }
                    files = [{"filename": path, "status": "modified"} for path in paths]
                    self.assertTrue(self.decide(files=files, dependencies=[metadata]).eligible)

    def test_one_major_or_unknown_update_blocks_the_entire_group(self) -> None:
        for value in ("version-update:semver-major", "", None, [], "unexpected"):
            with self.subTest(value=value):
                group = [dependency(), dependency() | {"updateType": value}]
                self.assertFalse(self.decide(dependencies=group).eligible)

    def test_unverified_or_malformed_metadata_never_enables_auto_merge(self) -> None:
        for metadata in (
            [],
            {},
            [None],
            [dependency() | {"maintainerChanges": True}],
            [dependency() | {"maintainerChanges": None}],
            [dependency() | {"dependencyName": ""}],
            [dependency(), dependency() | {"packageEcosystem": "npm_and_yarn"}],
        ):
            with self.subTest(metadata=metadata):
                self.assertFalse(self.decide(dependencies=metadata).eligible)

    def test_draft_fork_human_and_closed_prs_are_not_automated(self) -> None:
        for change in (
            {"draft": True},
            {"state": "closed"},
            {"user": {"login": "maintainer", "type": "User"}},
            {"head": {"sha": HEAD, "repo": {"full_name": "other/fork"}}},
        ):
            with self.subTest(change=change):
                self.assertFalse(self.decide(pr=pull_request() | change).eligible)

    def test_incomplete_duplicate_renamed_and_unexpected_files_are_held(self) -> None:
        for files in (
            FILES[:1],
            [FILES[0], FILES[0]],
            [FILES[0], FILES[1] | {"status": "renamed"}],
            [FILES[0], {"filename": "packages/api/app/main.py", "status": "modified"}],
            [FILES[0], {"filename": "../frontend/package.json", "status": "modified"}],
        ):
            with self.subTest(files=files):
                self.assertFalse(self.decide(files=files).eligible)

    def test_changed_head_or_wrong_base_is_rejected(self) -> None:
        for change in (
            {"head": {"sha": "b" * 40, "repo": {"full_name": REPOSITORY}}},
            {"base": {"ref": "other", "repo": {"full_name": REPOSITORY}}},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.decide(pr=pull_request() | change)

    def run_finish(self, current, metadata):
        effects = []
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "dependency-policy-pr.json").write_text(json.dumps(pull_request()))
            environment = {
                "GITHUB_REPOSITORY": REPOSITORY,
                "PR_NUMBER": "38",
                "RUNNER_TEMP": temp,
                "GITHUB_STEP_SUMMARY": str(root / "summary"),
                "DEPENDENCIES_JSON": json.dumps(metadata),
            }
            with (
                patch.dict(os.environ, environment),
                patch("sys.argv", ["policy", "finish"]),
                patch.object(policy, "api", side_effect=[current, FILES]),
                patch.object(
                    policy, "status", side_effect=lambda *args: effects.append(("status", args))
                ),
                patch.object(
                    policy.subprocess,
                    "run",
                    side_effect=lambda command, **kwargs: effects.append(("command", command)),
                ),
            ):
                policy.main()
        return effects

    def test_ineligible_replacement_disables_queued_merge_before_success_status(self) -> None:
        current = pull_request() | {"auto_merge": {"merge_method": "squash"}}
        effects = self.run_finish(
            current, [dependency() | {"updateType": "version-update:semver-major"}]
        )
        self.assertEqual([kind for kind, _ in effects], ["command", "status"])
        self.assertIn("--disable-auto", effects[0][1])
        self.assertEqual(effects[1][1][2], "success")

    def test_eligible_merge_is_bound_to_the_verified_head_and_uses_no_bypass(self) -> None:
        effects = self.run_finish(pull_request(), [dependency()])
        self.assertEqual([kind for kind, _ in effects], ["status", "command"])
        command = effects[-1][1]
        self.assertIn("--auto", command)
        self.assertEqual(command[-2:], ["--match-head-commit", HEAD])
        self.assertNotIn("--admin", command)

    def test_head_change_prevents_all_merge_and_status_mutations(self) -> None:
        current = copy.deepcopy(pull_request())
        current["head"]["sha"] = "b" * 40
        with self.assertRaises(ValueError):
            self.run_finish(current, [dependency()])

    def test_privileged_workflow_executes_only_base_code_with_no_pr_artifacts(self) -> None:
        source = (Path(__file__).parents[1] / "workflows/dependabot-auto-merge.yml").read_text()
        self.assertIn("pull_request_target:", source)
        self.assertIn(
            "ref: ${{ github.event.pull_request.base.sha || "
            "github.event.repository.default_branch }}",
            source,
        )
        self.assertIn("persist-credentials: false", source)
        self.assertIn("skip-verification: false", source)
        self.assertIn("skip-commit-verification: false", source)
        for unsafe in (
            "ref: ${{ github.event.pull_request.head",
            "actions/cache",
            "download-artifact",
            "npm install",
            "pip install",
        ):
            self.assertNotIn(unsafe, source)


if __name__ == "__main__":
    unittest.main()
