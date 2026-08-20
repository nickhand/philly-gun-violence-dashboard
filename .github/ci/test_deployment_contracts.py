"""Repository-level deployment and scheduler contracts."""

from __future__ import annotations

import importlib.util
import re
import unittest
from collections import Counter
from pathlib import Path
from types import ModuleType

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPOSITORY_ROOT / ".github/workflows"

EXTERNAL_SCHEDULE_COUNTS = {
    "courts-scrape.yml": 1,
    "daily-homicide-sync.yml": 1,
    "daily-shootings-sync.yml": 3,
    "production-smoke.yml": 1,
    "security-quality.yml": 1,
}
DISPATCH_ONLY_WORKFLOWS = frozenset({*EXTERNAL_SCHEDULE_COUNTS, "courts-process.yml"})
EXPECTED_CRONTAB_LINES = (
    "30 11 * * * python scripts/dispatch_workflow.py daily-shootings-sync.yml",
    "30 15 * * * python scripts/dispatch_workflow.py daily-shootings-sync.yml",
    "30 17 * * * python scripts/dispatch_workflow.py daily-shootings-sync.yml",
    "15 15 * * * python scripts/dispatch_workflow.py daily-homicide-sync.yml",
    "15 2 * * 5 python scripts/dispatch_workflow.py courts-scrape.yml",
    "0 19 * * * python scripts/dispatch_workflow.py production-smoke.yml",
    "15 10 * * 2 python scripts/dispatch_workflow.py security-quality.yml",
)


def _workflow_files() -> tuple[Path, ...]:
    return tuple(sorted((*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml"))))


def _action_references(source: str) -> tuple[str, ...]:
    uncommented = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    pattern = re.compile(
        r"(?<![\w-])(?:['\"]uses['\"]|uses)[ \t]*:[ \t]*"
        r"['\"]?([^'\"\s,#}\]]+)"
    )
    return tuple(pattern.findall(uncommented))


def _load_dispatcher() -> ModuleType:
    path = REPOSITORY_ROOT / "packages/api/scripts/dispatch_workflow.py"
    spec = importlib.util.spec_from_file_location("dispatch_workflow_contract", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load workflow dispatcher")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DeploymentContracts(unittest.TestCase):
    def test_frontend_weekly_schedule_stays_native_during_phase_one(self) -> None:
        workflow = (REPOSITORY_ROOT / ".github/workflows/frontend-quality.yml").read_text()
        crontab = (REPOSITORY_ROOT / "packages/api/crontab").read_text()

        self.assertIn('cron: "30 9 * * 1"', workflow)
        self.assertNotIn("dispatch_workflow.py frontend-quality.yml", crontab)

    def test_security_audit_uses_the_external_scheduler(self) -> None:
        workflow = (REPOSITORY_ROOT / ".github/workflows/security-quality.yml").read_text()
        crontab = (REPOSITORY_ROOT / "packages/api/crontab").read_text()

        self.assertNotIn("  schedule:", workflow)
        self.assertIn("  workflow_dispatch:", workflow)
        self.assertIn(
            "15 10 * * 2 python scripts/dispatch_workflow.py security-quality.yml",
            crontab,
        )

    def test_courts_schedule_defaults_to_full_run_deduplication(self) -> None:
        source = (WORKFLOWS / "courts-scrape.yml").read_text()

        self.assertIn("allow_recent_full_run:", source)
        override_input = source.split("allow_recent_full_run:", maxsplit=1)[1].split(
            "permissions:", maxsplit=1
        )[0]
        self.assertIn("type: boolean", override_input)
        self.assertIn("default: false", override_input)
        self.assertIn("submit_args=(--force --monitor-in-ecs)", source)
        self.assertIn("submit_args+=(--allow-recent-full-run)", source)
        self.assertIn(
            "allow_recent_full_run is valid only when sample=0 selects a full run",
            source,
        )

    def test_external_schedule_targets_are_exact_and_dispatch_only(self) -> None:
        crontab = (REPOSITORY_ROOT / "packages/api/crontab").read_text()
        active_lines = tuple(
            line.strip()
            for line in crontab.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
        self.assertEqual(Counter(active_lines), Counter(EXPECTED_CRONTAB_LINES))
        targets = tuple(line.rsplit(maxsplit=1)[-1] for line in active_lines)
        self.assertEqual(Counter(targets), Counter(EXTERNAL_SCHEDULE_COUNTS))

        allowed = _load_dispatcher().ALLOWED_WORKFLOWS
        self.assertEqual(set(allowed), {*EXTERNAL_SCHEDULE_COUNTS, "frontend-quality.yml"})
        for workflow_name in DISPATCH_ONLY_WORKFLOWS:
            with self.subTest(workflow=workflow_name):
                source = (WORKFLOWS / workflow_name).read_text()
                self.assertIn("  workflow_dispatch:", source)
                self.assertNotIn("  schedule:", source)

    def test_production_smoke_runs_the_bounded_crawler_discovery_audit(self) -> None:
        source = (WORKFLOWS / "production-smoke.yml").read_text()
        checker = (REPOSITORY_ROOT / ".github/ci/check_crawler_discovery.py").read_text()

        self.assertIn("Check crawler discovery contracts", source)
        self.assertIn("python3 .github/ci/check_crawler_discovery.py", source)
        self.assertIn('--site-origin "${SITE_ORIGIN_URL}"', source)
        self.assertIn('--app-base-url "${APP_BASE_URL}"', source)
        self.assertIn('method="GET"', checker)
        self.assertIn("REQUEST_TIMEOUT_SECONDS = 15", checker)
        self.assertIn("MAX_RESPONSE_BYTES = 5 * 1024 * 1024", checker)
        for crawler in ("OAI-SearchBot", "Claude-SearchBot", "PerplexityBot"):
            with self.subTest(crawler=crawler):
                self.assertIn(crawler, checker)

    def test_workflows_pin_actions_and_declare_permissions(self) -> None:
        for workflow in _workflow_files():
            source = workflow.read_text()
            with self.subTest(workflow=workflow.name):
                self.assertIn("\npermissions:\n", source)
                for action in _action_references(source):
                    self.assertFalse(
                        action.startswith("./"),
                        "local actions require recursive pinning and trigger validation",
                    )
                    self.assertRegex(action, r"@[0-9a-f]{40}$")

    def test_action_reference_parser_covers_step_and_reusable_workflow_forms(self) -> None:
        source = """
        jobs:
          first:
            steps:
              - name: Named step
                uses: owner/action@1111111111111111111111111111111111111111
          second:
            uses: o/r/.github/workflows/c.yml@2222222222222222222222222222222222222222
          third:
            "uses": owner/quoted@3333333333333333333333333333333333333333
          fourth:
            uses : owner/spaced@4444444444444444444444444444444444444444
          fifth:
            steps:
              - { uses: owner/flow@5555555555555555555555555555555555555555 }
        """
        self.assertEqual(
            _action_references(source),
            (
                "owner/action@1111111111111111111111111111111111111111",
                "o/r/.github/workflows/c.yml@2222222222222222222222222222222222222222",
                "owner/quoted@3333333333333333333333333333333333333333",
                "owner/spaced@4444444444444444444444444444444444444444",
                "owner/flow@5555555555555555555555555555555555555555",
            ),
        )

    def test_config_quality_uses_the_pinned_offline_actionlint_image(self) -> None:
        source = (WORKFLOWS / "config-quality.yml").read_text()
        self.assertIn(
            "docker.io/rhysd/actionlint:1.7.12@sha256:"
            "b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667",
            source,
        )
        self.assertIn("--network none", source)
        self.assertIn("--read-only", source)

    def test_scheduler_deploy_prevents_overlapping_cron_machines(self) -> None:
        scheduler_config = (REPOSITORY_ROOT / "fly.scheduler.toml").read_text()
        recipes = (REPOSITORY_ROOT / "packages/api/just/api.just").read_text()

        self.assertIn('strategy = "immediate"', scheduler_config)
        self.assertIn("fly-deploy-scheduler: fly-assert-legacy-scheduler-stopped", recipes)
        self.assertIn("--strategy immediate --ha=false", recipes)
        self.assertIn("fly-assert-single-scheduler", recipes)
        scheduler_guard = recipes.split("fly-assert-single-scheduler:", maxsplit=1)[1].split(
            "# Deploy the scheduler", maxsplit=1
        )[0]
        self.assertIn("scheduler_start_timeout_seconds=120", scheduler_guard)
        self.assertIn("scheduler_start_poll_seconds=5", scheduler_guard)
        self.assertIn('if type == "array" then length', scheduler_guard)
        self.assertNotIn("cron_machines=", scheduler_guard)
        total_guard = scheduler_guard.index('if [ "$total" -gt 1 ]')
        process_group_guard = scheduler_guard.index('if [ "$process_group" != "cron" ]')
        self.assertLess(total_guard, process_group_guard)
        self.assertIn("created|creating|starting|restarting|updating|replacing", scheduler_guard)
        self.assertIn(
            "stopping|stopped|suspending|suspended|failed|destroying|destroyed",
            scheduler_guard,
        )
        started_case = scheduler_guard.index("started) \\")
        success_exit = scheduler_guard.index("exit 0", started_case)
        self.assertEqual(scheduler_guard.count("exit 0"), 1)
        self.assertLess(started_case, success_exit)
        self.assertIn("Machine entered unexpected state", scheduler_guard)
        self.assertEqual(scheduler_guard.count('="$(jq -er'), 3)
        self.assertEqual(scheduler_guard.count('<<< "$machine_list")" || {'), 3)
        self.assertIn(
            'if [ "$elapsed_seconds" -ge "$scheduler_start_timeout_seconds" ]',
            scheduler_guard,
        )
        self.assertIn('flyctl secrets unset GITHUB_PAT --app "{{ fly_api_app }}"', recipes)

    def test_deployment_docs_put_reader_before_scheduler_and_token_removal(self) -> None:
        for relative_path in ("README.md", "packages/api/README.md"):
            with self.subTest(path=relative_path):
                source = (REPOSITORY_ROOT / relative_path).read_text()
                deployment = source.split("## Deployment (Fly.io)", maxsplit=1)[1]
                api_deploy = deployment.index("just fly-deploy-api")
                scheduler_deploy = deployment.index("just fly-deploy-scheduler")
                token_removal = deployment.index("just fly-remove-legacy-api-token")

                self.assertLess(deployment.index("EXPECT_ATOMIC_RELEASE=false"), api_deploy)
                self.assertLess(deployment.index("public/downloads/manifest.json"), api_deploy)
                self.assertLess(api_deploy, scheduler_deploy)
                self.assertLess(scheduler_deploy, token_removal)
                self.assertIn("legacy-backed", deployment)
                self.assertIn("1 GB", deployment)


if __name__ == "__main__":
    unittest.main()
