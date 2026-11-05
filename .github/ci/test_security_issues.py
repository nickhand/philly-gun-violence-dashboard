"""Test issue reconciliation and the provenance of deployed scan coverage."""

import copy
import importlib.util
import json
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "security_issues", Path(__file__).with_name("security_issues.py")
)
assert SPEC and SPEC.loader
MONITOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MONITOR)
NOW = datetime(2026, 11, 5, 16, tzinfo=UTC)


def observation():
    finding = {
        "component": "image",
        "package": "patched-package",
        "version": "1.2",
        "advisory": "CVE-2026-0001",
        "severity": "High",
        "fixed_versions": ["1.3"],
    }
    return {
        "schema_version": 1,
        "source_sha": "1" * 40,
        "image": "registry/repo@sha256:" + "2" * 64,
        "image_id": "sha256:" + "3" * 64,
        "observed_at": NOW.isoformat(),
        "findings": [
            finding,
            finding | {"component": "chrome", "advisory": "CVE-2026-0002"},
            finding,
        ],
    }


class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.issues = []
        self.writes = []
        self.enterContext(patch.dict(os.environ, SECURITY_MAINTAINER="maintainer"))
        self.enterContext(patch.object(MONITOR, "github", self.github))
        self.enterContext(
            patch.object(MONITOR, "run_url", return_value="https://example.com/run/1")
        )

    def github(self, path, *, method="GET", body=None, pages=False):
        if path.startswith("issues?"):
            self.assertTrue(pages)
            return [[], copy.deepcopy(self.issues)]
        self.writes.append((method, path))
        if "assignees" in body:
            body = body | {"assignees": [{"login": name} for name in body["assignees"]]}
        if method == "POST":
            self.issues.append(
                dict(
                    body,
                    number=len(self.issues) + 1,
                    state="open",
                    user={"login": MONITOR.BOT, "id": MONITOR.BOT_ID},
                )
            )
            return self.issues[-1]
        else:
            self.assertEqual(method, "PATCH")
            number = int(path.split("/")[1])
            self.issues[number - 1].update(body)

    def test_one_issue_per_package_stays_quiet_updates_closes_and_reopens(self):
        data = observation()
        reports = MONITOR.deployed_reports(data, NOW)
        self.assertEqual(len(reports), 1)
        MONITOR.reconcile("deployed", reports, close_missing=True)
        issue = self.issues[0]
        self.assertEqual(issue["body"].count("CVE-2026-0001"), 1)
        self.assertIn("CVE-2026-0002", issue["body"])
        self.assertEqual(issue["assignees"], [{"login": "maintainer"}])
        data["findings"].reverse()
        with patch.object(MONITOR, "run_url", return_value="https://example.com/run/2"):
            MONITOR.reconcile("deployed", MONITOR.deployed_reports(data, NOW), close_missing=True)
        self.assertEqual(self.writes, [("POST", "issues")])
        data["findings"][1]["fixed_versions"] = ["1.4"]
        MONITOR.reconcile("deployed", MONITOR.deployed_reports(data, NOW), close_missing=True)
        self.assertIn("1.4", issue["body"])
        MONITOR.reconcile("deployed", {}, close_missing=True)
        self.assertEqual(issue["state"], "closed")
        issue["assignees"] = [{"login": "another-reviewer"}]
        MONITOR.reconcile("deployed", reports, close_missing=True)
        self.assertEqual(
            issue["assignees"], [{"login": "another-reviewer"}, {"login": "maintainer"}]
        )
        self.assertEqual(issue["state"], "open")
        self.assertEqual(len(self.issues), 1)

    def test_registry_findings_share_package_issue_and_show_scan_date(self):
        data = observation()
        data["ecr"] = {"scan_completed_at": (NOW - timedelta(days=2)).isoformat()}
        data["findings"].append(data["findings"][0] | {"component": "ecr"})
        reports = MONITOR.deployed_reports(data, NOW)
        self.assertEqual(len(reports), 1)
        self.assertIn("ECR scan of 2026-11-03", next(iter(reports.values()))[1])
        data["ecr"]["scan_completed_at"] = (NOW + timedelta(days=1)).isoformat()
        with self.assertRaisesRegex(ValueError, "ECR scan time"):
            MONITOR.deployed_reports(data, NOW)

    def test_ignores_human_authors_forged_bot_names_and_prs(self):
        reports = MONITOR.weekly_reports({"api": "failure"})
        MONITOR.reconcile("weekly", reports)
        base = self.issues[0]
        self.assertNotIn("assignees", base)
        for number, changes in enumerate(
            [
                {"user": {"login": "maintainer", "id": 1}},
                {"user": {"login": MONITOR.BOT, "id": 1234}},
                {"pull_request": {}},
            ],
            2,
        ):
            self.issues.append(base | changes | {"number": number})
        # Skips, missing results and other report namespaces cannot close active tickets.
        MONITOR.reconcile("weekly", MONITOR.weekly_reports({"api": "cancelled", "etl": "skipped"}))
        MONITOR.reconcile("deployed", {}, close_missing=True)
        self.assertEqual([issue["state"] for issue in self.issues], ["open"] * 4)
        MONITOR.reconcile("weekly", MONITOR.weekly_reports({"api": "success"}))
        self.assertEqual(
            [issue["state"] for issue in self.issues], ["closed", "open", "open", "open"]
        )

    def test_incomplete_and_stale_observations_cannot_touch_issues(self):
        for changes in (
            {"findings": None},
            {"image": "a:latest"},
            {"schema_version": True},
            {"observed_at": (NOW - timedelta(hours=2, seconds=1)).isoformat()},
            {"observed_at": (NOW + timedelta(seconds=1)).isoformat()},
            {"findings": [{"component": "image"}]},
        ):
            with (
                self.subTest(changes=changes),
                self.assertRaises((ValueError, KeyError, TypeError)),
            ):
                MONITOR.deployed_reports(observation() | changes, NOW)
        self.assertFalse(self.writes)

    def test_cli_validates_observation_before_listing_or_writing_issues(self):
        env = {
            "GH_TOKEN": "test",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
        }
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, env):
            path = Path(directory) / "observation.json"
            path.write_text(json.dumps(observation() | {"findings": None}))
            with (
                patch("sys.argv", ["monitor", "deployed", str(path)]),
                patch.object(MONITOR, "github") as api,
            ):
                with self.assertRaises(ValueError):
                    MONITOR.main()
                api.assert_not_called()


class Coverage(unittest.TestCase):
    def setUp(self):
        self.origin = {
            "id": 10,
            "repository_id": 1,
            "head_repository_id": 1,
            "head_branch": "main",
            "head_sha": "a" * 40,
        }
        self.artifact = {
            "name": "verified-deployed-scraper-10-2",
            "expired": False,
            "expires_at": (NOW + timedelta(days=7)).isoformat(),
            "size_in_bytes": 100,
            "created_at": (NOW - timedelta(hours=1)).isoformat(),
            "workflow_run": self.origin,
        }
        self.run = {
            "id": 10,
            "run_attempt": 2,
            "workflow_id": 20,
            "event": "workflow_dispatch",
            "repository": {"id": 1},
            "head_repository": {"id": 1},
            "head_branch": "main",
            "head_sha": "a" * 40,
            "created_at": (NOW - timedelta(days=10)).isoformat(),
            "run_started_at": (NOW - timedelta(hours=2)).isoformat(),
            "conclusion": "failure",
        }
        self.artifacts = [self.artifact]
        self.responses = {
            "": {"default_branch": "main", "id": 1},
            "actions/workflows/security-quality.yml": {"id": 20},
            "actions/artifacts?per_page=100&page=1": {"artifacts": [{"name": "other"}] * 100},
            "actions/artifacts?per_page=100&page=2": {"artifacts": self.artifacts},
            "actions/runs/10": self.run,
        }
        self.enterContext(
            patch.object(MONITOR, "github", side_effect=lambda path, **kwargs: self.responses[path])
        )

    def test_new_observation_on_old_rerun_counts_despite_sibling_failure(self):
        self.assertEqual(MONITOR.coverage_reports(NOW), {"active": None})
        self.responses["actions/runs/10/attempts/2"] = self.run | {
            "updated_at": (NOW - timedelta(minutes=45)).isoformat()
        }
        self.run.update(run_attempt=3, run_started_at=NOW.isoformat())
        self.assertEqual(MONITOR.coverage_reports(NOW), {"active": None})

    def test_untrusted_run_empty_expired_stale_or_missing_artifacts_are_overdue(self):
        for target, changes in (
            (self.artifact, {"created_at": (NOW - timedelta(hours=49)).isoformat()}),
            (self.artifact, {"created_at": (NOW + timedelta(minutes=1)).isoformat()}),
            (self.artifact, {"expired": True}),
            (self.artifact, {"expires_at": (NOW - timedelta(minutes=1)).isoformat()}),
            (self.artifact, {"size_in_bytes": 0}),
            (self.artifact, {"name": "deployed-scraper-evidence-10-2"}),
            (self.artifact, {"name": "verified-deployed-scraper-10-3"}),
            (self.artifact, {"workflow_run": None}),
            (self.origin, {"repository_id": 2}),
            (self.origin, {"head_repository_id": 2}),
            (self.origin, {"head_sha": "b" * 40}),
            (self.origin, {"id": 11}),
            (self.run, {"event": "pull_request"}),
            (self.run, {"workflow_id": 21}),
            (self.run, {"head_branch": "my-pr"}),
            (self.run, {"head_repository": {"id": 2}}),
            (self.run, {"run_started_at": NOW.isoformat()}),
        ):
            with self.subTest(changes=changes), patch.dict(target, changes):
                self.assertIsNotNone(MONITOR.coverage_reports(NOW)["active"])
        self.artifacts.clear()
        self.assertIsNotNone(MONITOR.coverage_reports(NOW)["active"])


if __name__ == "__main__":
    unittest.main()
