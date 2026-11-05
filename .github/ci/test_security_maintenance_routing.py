"""Exercise the actual scheduled-audit routing and trusted observation handoff."""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[1] / "workflows"


def run_cadence(event, ref, *, created="2026-11-05T07:17:02Z", full=False):
    workflow = (WORKFLOWS / "security-quality.yml").read_text()
    step = workflow.split("        id: cadence\n", 1)[1].split("      - name:", 1)[0]
    script = textwrap.dedent(step.split("        run: |\n", 1)[1])
    # A rerun must use its original GitHub creation timestamp. Substitute only
    # the API response; execute the real routing body and its weekday check.
    setup = (
        'gh() { [[ "$*" == *"actions/runs/$GITHUB_RUN_ID"* ]] || return 1; '
        'printf "%s\\n" "$CREATED"; }\n'
    )
    if sys.platform == "darwin":
        setup += """date() { /bin/date -ju -f '%Y-%m-%dT%H:%M:%SZ' "$3" "$4"; }\n"""
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory, "outputs")
        result = subprocess.run(
            ["bash", "--noprofile", "--norc", "-c", setup + script],
            env={
                "PATH": os.defpath,
                "GITHUB_EVENT_NAME": event,
                "GITHUB_REF": ref,
                "GITHUB_RUN_ID": "42",
                "GITHUB_REPOSITORY": "owner/repo",
                "GITHUB_OUTPUT": str(output),
                "CREATED": created,
                "FULL_AUDIT": str(full).lower(),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        values = (
            dict(s.split("=", 1) for s in output.read_text().splitlines())
            if output.exists()
            else {}
        )
        return result, values


class SecurityMaintenanceRoutingTests(unittest.TestCase):
    def test_dispatch_calendar_and_manual_override(self):
        main = "refs/heads/main"
        dispatch = "workflow_dispatch"
        wednesday = "2026-11-04T07:17:02Z"
        thursday = "2026-11-05T07:17:02Z"
        for event, ref, created, full, expected in [
            (dispatch, main, wednesday, False, ("true", "true")),
            (dispatch, main, thursday, False, ("true", "false")),
            (dispatch, main, thursday, True, ("true", "true")),
            (dispatch, "refs/heads/fix", "", False, ("false", "true")),
            ("pull_request", "refs/pull/123/merge", "", False, ("false", "false")),
            ("push", main, "", False, ("false", "false")),
        ]:
            with self.subTest(event=event, ref=ref, created=created, full=full):
                result, values = run_cadence(event, ref, created=created, full=full)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((values["deployed"], values["image"]), expected)

    def test_missing_creation_time_cannot_silently_skip_the_weekly_audit(self):
        result, values = run_cadence("workflow_dispatch", "refs/heads/main", created="")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("image", values)

    def test_data_collection_and_issue_writes_are_isolated(self):
        source = (WORKFLOWS / "deployed-scraper-audit.yml").read_text()
        scan, report = source.split("\n  scan:\n", 1)[1].split("\n  reconcile:\n", 1)
        self.assertIn("github.event_name == 'workflow_dispatch'", scan)
        self.assertIn("github.ref == 'refs/heads/main'", scan)
        self.assertNotIn("issues: write", scan)
        self.assertNotIn("id-token: write", report)
        self.assertIn("issues: write", report)
        # A monitor using the deployment role must narrow its STS session to
        # reading the active pointer and downloading the single ECR repository.
        policy = json.JSONDecoder().raw_decode(
            scan.split("inline-session-policy: >-", 1)[1].lstrip()
        )[0]
        trusted_actions = {
            "s3:GetObject",
            "ecr:GetAuthorizationToken",
            "ecr:BatchGetImage",
            "ecr:DescribeImages",
            "ecr:DescribeRepositories",
            "ecr:BatchCheckLayerAvailability",
            "ecr:GetDownloadUrlForLayer",
        }
        for statement in policy["Statement"]:
            actions = statement["Action"]
            actions = {actions} if isinstance(actions, str) else set(actions)
            self.assertEqual(statement["Effect"], "Allow")
            self.assertLessEqual(actions, trusted_actions)
            if statement["Resource"] == "*":
                self.assertEqual(actions, {"ecr:GetAuthorizationToken"})
            elif "s3:GetObject" in actions:
                self.assertTrue(statement["Resource"].endswith("/deployment/active.json"))
            else:
                self.assertTrue(statement["Resource"].endswith(":repository/ujs-scraper"))

    def test_only_successfully_reconciled_observations_count_toward_coverage(self):
        source = (WORKFLOWS / "deployed-scraper-audit.yml").read_text()
        scan, report = source.split("\n  scan:\n", 1)[1].split("\n  reconcile:\n", 1)
        self.assertIn("observation_id: ${{ steps.observation.outputs.artifact-id }}", scan)
        self.assertIn("observed: ${{ steps.scan.outcome == 'success' }}", scan)
        self.assertIn("if: needs.scan.outputs.observed == 'true'", report)
        self.assertIn("artifact-ids: ${{ needs.scan.outputs.observation_id }}", report)
        self.assertNotIn("name: verified-deployed-scraper-", scan)
        reconciliation, upload = report.split("run: python3 .github/ci/security_issues.py deployed")
        self.assertNotIn("name: verified-deployed-scraper-", reconciliation)
        self.assertIn("name: verified-deployed-scraper-", upload)
        self.assertNotIn("if: always()", upload)
        watchdog = (WORKFLOWS / "security-coverage.yml").read_text()
        self.assertIn("  schedule:", watchdog)
        self.assertNotIn("workflow_run:", watchdog)
        self.assertIn("if: github.ref == 'refs/heads/main'", watchdog)
