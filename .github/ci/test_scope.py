"""Contracts for repository-owned CI path routing."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCOPE_PATH = Path(__file__).with_name("scope.py")


def _load_scope() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ci_scope", SCOPE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load CI scope module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCOPE = _load_scope()


def _workflow_paths(name: str, event: str) -> tuple[str, ...]:
    source = (REPOSITORY_ROOT / ".github" / "workflows" / f"{name}-quality.yml").read_text()
    lines = source.splitlines()
    event_line = f"  {event}:"
    try:
        start = lines.index(event_line)
    except ValueError as exc:
        raise AssertionError(f"{name} workflow has no {event} trigger") from exc

    paths: list[str] = []
    in_paths = False
    for line in lines[start + 1 :]:
        if line.startswith("  ") and not line.startswith("    "):
            break
        if line == "    paths:":
            in_paths = True
            continue
        if in_paths:
            if not line.startswith("      - "):
                break
            paths.append(line.removeprefix("      - ").strip().strip('"'))
    return tuple(paths)


class TriggerContracts(unittest.TestCase):
    def test_pull_request_and_push_paths_match_the_declared_policy(self) -> None:
        for workflow, expected in SCOPE.TRIGGERS.items():
            with self.subTest(workflow=workflow):
                self.assertEqual(_workflow_paths(workflow, "pull_request"), expected)
                self.assertEqual(_workflow_paths(workflow, "push"), expected)
        self.assertEqual(_workflow_paths("config", "pull_request"), SCOPE.CONFIG_TRIGGERS)
        self.assertEqual(_workflow_paths("config", "push"), SCOPE.CONFIG_TRIGGERS)

    def test_every_trigger_path_selects_at_least_one_job(self) -> None:
        for workflow, patterns in SCOPE.TRIGGERS.items():
            for pattern in patterns:
                candidate = (
                    pattern.removesuffix("/**") + "/probe" if pattern.endswith("/**") else pattern
                )
                with self.subTest(workflow=workflow, pattern=pattern):
                    self.assertTrue(any(SCOPE.classify(workflow, [candidate]).values()))

    def test_representative_changes_route_only_to_required_jobs(self) -> None:
        cases = {
            ("api", "packages/api/app/main.py"): {"checks", "image"},
            ("api", "packages/api/tests/test_startup.py"): {"checks"},
            ("api", "packages/api/.python-version"): {"checks"},
            ("api", "packages/api/Dockerfile"): {"image"},
            ("api", "README.md"): set(),
            ("etl", "packages/etl/src/etl/cli.py"): {"etl", "image"},
            ("etl", "packages/etl/tests/test_query.py"): {"etl"},
            ("etl", "packages/etl/chrome-lock.json"): {
                "etl",
                "dashboard",
                "scraper",
                "image",
            },
            ("etl", ".github/workflows/chrome-update.yml"): {"etl"},
            ("etl", "packages/etl/.python-version"): {"etl"},
            ("etl", "packages/dashboard-utils/.python-version"): {"dashboard"},
            ("etl", "packages/dashboard-utils/src/dashboard_utils/aws.py"): {
                "etl",
                "dashboard",
                "image",
            },
            ("etl", "packages/aws-batch-scraper/tests/test_cli.py"): {"scraper"},
            ("etl", "Justfile"): {"etl"},
            ("frontend", "frontend/tests/unit/app/map-print.spec.ts"): {"unit"},
            ("frontend", "frontend/tests/e2e/mobile.spec.ts"): {"unit", "browser"},
            ("frontend", "frontend/tests/lighthouse-policy.test.mjs"): {"unit"},
            ("frontend", "frontend/tests/setup.ts"): {"unit"},
            ("frontend", "frontend/tests/vue-shim.d.ts"): {"unit"},
            ("frontend", "frontend/scripts/check-bundle-size.mjs"): {"unit"},
            ("frontend", "frontend/scripts/run-lighthouse.mjs"): {"lighthouse"},
            ("frontend", "frontend/scripts/lighthouse-policy.mjs"): {
                "unit",
                "lighthouse",
            },
            ("frontend", "frontend/wrangler.jsonc"): {"release", "unit"},
            ("frontend", "frontend/app/app.vue"): {"release", "unit", "browser"},
            ("frontend", "frontend/src/main.ts"): {
                "release",
                "unit",
                "browser",
                "lighthouse",
            },
            ("security", "packages/api/uv.lock"): {"api"},
            ("security", "packages/etl/uv.lock"): {"etl"},
            ("security", "packages/dashboard-utils/uv.lock"): {"dashboard"},
            ("security", "packages/aws-batch-scraper/uv.lock"): {"scraper"},
            ("security", "frontend/package-lock.json"): {"frontend"},
        }
        for (workflow, path), expected in cases.items():
            with self.subTest(workflow=workflow, path=path):
                actual = {
                    name for name, enabled in SCOPE.classify(workflow, [path]).items() if enabled
                }
                self.assertEqual(actual, expected)

    def test_shared_python_policy_reaches_every_python_job_but_not_images(self) -> None:
        self.assertEqual(
            {name for name, enabled in SCOPE.classify("api", ["ruff.toml"]).items() if enabled},
            {"checks"},
        )
        self.assertEqual(
            {name for name, enabled in SCOPE.classify("etl", ["ruff.toml"]).items() if enabled},
            {"etl", "dashboard", "scraper"},
        )

    def test_documentation_and_unrelated_root_files_launch_no_expensive_job(self) -> None:
        for workflow, path in (
            ("frontend", "frontend/README.md"),
            ("frontend", "frontend/layers/civic-ui/README.md"),
            ("frontend", "frontend/.env.example"),
            ("frontend", "frontend/just/frontend.just"),
            ("api", "Justfile"),
            ("api", "packages/api/README.md"),
            ("api", "packages/dashboard-utils/README.md"),
            ("etl", "just/python.just"),
            ("etl", "packages/aws-batch-scraper/README.md"),
            ("etl", "packages/dashboard-utils/README.md"),
            ("etl", "packages/etl/README.md"),
            ("api", "package-lock.json"),
        ):
            with self.subTest(workflow=workflow, path=path):
                self.assertFalse(any(SCOPE.classify(workflow, [path]).values()))

    def test_every_declared_no_job_path_remains_cheap(self) -> None:
        for workflow, patterns in SCOPE.NO_JOB_PATTERNS.items():
            for pattern in patterns:
                candidate = (
                    pattern.removesuffix("/**") + "/probe" if pattern.endswith("/**") else pattern
                )
                with self.subTest(workflow=workflow, pattern=pattern):
                    self.assertTrue(
                        any(
                            SCOPE.path_matches(candidate, trigger)
                            for trigger in SCOPE.TRIGGERS[workflow]
                        )
                    )
                    self.assertFalse(any(SCOPE.classify(workflow, [candidate]).values()))

    def test_unknown_product_paths_fail_safe_to_every_job(self) -> None:
        for workflow, path in (
            ("api", "packages/api/new-runtime/entry.py"),
            ("etl", "packages/etl/new-runtime/entry.py"),
            ("frontend", "frontend/modules/new-module.ts"),
        ):
            with self.subTest(workflow=workflow, path=path):
                self.assertEqual(
                    SCOPE.classify(workflow, [path]),
                    dict.fromkeys(SCOPE.GROUPS[workflow], True),
                )

    def test_router_or_workflow_changes_fail_safe_to_every_job(self) -> None:
        for workflow, groups in SCOPE.GROUPS.items():
            with self.subTest(workflow=workflow):
                self.assertEqual(
                    SCOPE.classify(workflow, [".github/ci/scope.py"]),
                    dict.fromkeys(groups, True),
                )
                self.assertEqual(
                    SCOPE.classify(workflow, [f".github/workflows/{workflow}-quality.yml"]),
                    dict.fromkeys(groups, True),
                )

    def test_unknown_watched_path_fails_safe_even_with_a_known_path(self) -> None:
        expected = dict.fromkeys(SCOPE.GROUPS["frontend"], True)
        self.assertEqual(SCOPE.classify("frontend", ["frontend/tests/new-kind.test.ts"]), expected)
        self.assertEqual(
            SCOPE.classify(
                "frontend",
                ["frontend/tests/unit/app/map-print.spec.ts", "frontend/tests/new-kind.test.ts"],
            ),
            expected,
        )

    def test_ci_test_and_checker_changes_do_not_launch_product_suites(self) -> None:
        for path in (".github/ci/test_scope.py", ".github/ci/check_deployment_config.py"):
            for workflow in SCOPE.GROUPS:
                with self.subTest(path=path, workflow=workflow):
                    self.assertFalse(any(SCOPE.classify(workflow, [path]).values()))

    def test_lighthouse_scripts_do_not_launch_the_browser_matrix(self) -> None:
        for path in (
            "frontend/scripts/lighthouse-policy.mjs",
            "frontend/scripts/run-lighthouse.mjs",
            "frontend/scripts/serve-lighthouse.mjs",
        ):
            with self.subTest(path=path):
                decisions = SCOPE.classify("frontend", [path])
                self.assertTrue(decisions["lighthouse"])
                self.assertFalse(decisions["browser"])

    def test_only_runtime_inputs_select_a_frontend_release(self) -> None:
        for path in (
            "frontend/app/app.vue",
            "frontend/public/robots.txt",
            "frontend/server/api/public-download-manifest.get.ts",
            "frontend/src/data/style.json",
            "frontend/wrangler.jsonc",
        ):
            with self.subTest(path=path):
                self.assertTrue(SCOPE.classify("frontend", [path])["release"])

        for path in (
            "frontend/README.md",
            "frontend/tests/unit/app/dashboard-explorer.spec.ts",
            "frontend/tests/e2e/nuxt/dashboard.spec.ts",
            "frontend/scripts/run-lighthouse.mjs",
        ):
            with self.subTest(path=path):
                self.assertFalse(SCOPE.classify("frontend", [path])["release"])

    def test_main_pushes_are_not_cancelled_by_narrower_follow_up_diffs(self) -> None:
        workflows = ("api", "etl", "security", "config")
        expected = "cancel-in-progress: ${{ github.event_name == 'pull_request' }}"
        for workflow in workflows:
            expected_group = (
                f"group: {workflow}-quality-"
                "${{ github.event_name == 'pull_request' && github.ref || github.run_id }}"
            )
            source = (
                REPOSITORY_ROOT / ".github" / "workflows" / f"{workflow}-quality.yml"
            ).read_text()
            with self.subTest(workflow=workflow):
                self.assertIn(expected, source)
                self.assertIn(expected_group, source)

        frontend = (
            REPOSITORY_ROOT / ".github" / "workflows" / "frontend-quality.yml"
        ).read_text()
        self.assertIn("'main-release'", frontend)
        self.assertIn("queue: max", frontend)
        self.assertIn("cancel-in-progress: false", frontend)

    def test_manual_and_scheduled_runs_force_all_jobs(self) -> None:
        for workflow, groups in SCOPE.GROUPS.items():
            with self.subTest(workflow=workflow):
                self.assertEqual(
                    SCOPE.classify(workflow, [], force_all=True),
                    dict.fromkeys(groups, True),
                )

    def test_git_diffs_disable_rename_detection(self) -> None:
        with patch.object(SCOPE, "_git_paths", return_value=("packages/api/app/main.py",)) as git:
            self.assertEqual(
                SCOPE.changed_paths(event="pull_request", before="", base="base", head="head"),
                ("packages/api/app/main.py",),
            )
            git.assert_called_once_with(
                ("diff", "--no-renames", "--name-only", "-z", "base...head")
            )

        with patch.object(
            SCOPE, "_git_paths", return_value=("packages/etl/src/etl/cli.py",)
        ) as git:
            self.assertEqual(
                SCOPE.changed_paths(event="push", before="before", base="", head="head"),
                ("packages/etl/src/etl/cli.py",),
            )
            git.assert_called_once_with(
                ("diff", "--no-renames", "--name-only", "-z", "before", "head")
            )

    def test_security_audits_have_only_the_external_schedule_owner(self) -> None:
        workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "security-quality.yml").read_text()
        self.assertNotIn("  schedule:", workflow)
        self.assertIn("  workflow_dispatch:", workflow)

    def test_unsafe_paths_are_rejected(self) -> None:
        for path in ("", "../ruff.toml", "/etc/passwd"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                SCOPE.classify("api", [path])


if __name__ == "__main__":
    unittest.main()
