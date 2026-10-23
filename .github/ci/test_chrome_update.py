"""Exercise the Chrome updater's real commit/push step against local Git remotes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / "workflows/chrome-update.yml"
UPDATE_BRANCH = "automation/chrome-stable"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
HUMAN_EMAIL = "maintainer@example.com"
LOCK = "packages/etl/chrome-lock.json"
GENERATED_PATHS = (
    "Justfile",
    LOCK,
    "packages/etl/Dockerfile",
    "packages/etl/README.md",
    "packages/aws-batch-scraper/docs/container.md",
    "packages/aws-batch-scraper/tests/test_release_image.py",
)


def _push_script() -> str:
    step = (
        WORKFLOW.read_text()
        .split("      - name: Commit and push the generated update\n", maxsplit=1)[1]
        .split("      - name:", maxsplit=1)[0]
    )
    script = textwrap.dedent(step.split("        run: |\n", maxsplit=1)[1])
    return script.replace("${{ github.event.repository.default_branch }}", "main")


def _merge_script() -> str:
    step = (
        WORKFLOW.read_text()
        .split("      - name: Merge a validated same-milestone update\n", maxsplit=1)[1]
        .split("      - name:", maxsplit=1)[0]
    )
    script = textwrap.dedent(step.split("        run: |\n", maxsplit=1)[1])
    for expression, value in {
        "github.event.repository.default_branch": "main",
        "steps.pull_request.outputs.number": "86",
        "steps.push.outputs.head_sha": "tested-head",
        "steps.update.outputs.base_sha": "tested-base",
    }.items():
        script = script.replace("${{ " + expression + " }}", value)
    return script


def _validation_functions() -> str:
    step = (
        WORKFLOW.read_text()
        .split("      - name: Validate the exact update commit\n", maxsplit=1)[1]
        .split("      - name:", maxsplit=1)[0]
    )
    script = textwrap.dedent(step.split("        run: |\n", maxsplit=1)[1])
    script = script.split('etl_run_id="$(prepare_validation_run', maxsplit=1)[0]
    return (
        script.replace("${{ steps.push.outputs.head_sha }}", "tested-head")
        .replace("${{ steps.push.outputs.reused }}", "true")
        .replace("${{ steps.pull_request.outputs.number }}", "86")
    )


class ChromeUpdateValidationTests(unittest.TestCase):
    def run_validation(
        self, *, status: str, conclusion: str, token: bool = True
    ) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            gh = root / "gh"
            gh.write_text(
                f"#!{sys.executable}\n"
                + textwrap.dedent("""\
                    import json, os, sys
                    from pathlib import Path
                    args = sys.argv[1:]
                    with open(os.environ["TEST_CALLS"], "a") as output:
                        output.write(json.dumps(args) + "\\n")
                    if args[:2] == ["run", "list"]:
                        print(json.dumps([
                            {"databaseId": 999, "headSha": "unrelated-head",
                             "status": "completed", "conclusion": "success"},
                            {"databaseId": 42, "headSha": "tested-head",
                             "status": os.environ["TEST_STATUS"],
                             "conclusion": os.environ["TEST_CONCLUSION"]}
                        ]))
                    elif args[:2] == ["run", "view"]:
                        print(2 if Path(os.environ["TEST_RERUN"]).exists() else 1)
                    elif args[:2] == ["run", "rerun"]:
                        Path(os.environ["TEST_RERUN"]).touch()
                    else:
                        sys.exit(2)
                """)
            )
            gh.chmod(0o755)
            calls = root / "calls"
            env = {
                **os.environ,
                "PATH": str(root) + os.pathsep + os.environ["PATH"],
                "GITHUB_REPOSITORY": "owner/repository",
                "UPDATE_BRANCH": UPDATE_BRANCH,
                "HAS_CHROME_UPDATE_TOKEN": str(token).lower(),
                "TEST_CALLS": str(calls),
                "TEST_RERUN": str(root / "rerun"),
                "TEST_STATUS": status,
                "TEST_CONCLUSION": conclusion,
            }
            result = subprocess.run(
                [
                    "bash",
                    "--noprofile",
                    "--norc",
                    "-c",
                    _validation_functions() + '\nprepare_validation_run "etl-quality.yml"\n',
                ],
                env=env,
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
            return result, [json.loads(line) for line in calls.read_text().splitlines()]

    def test_reuses_exact_head_pr_checks_without_duplicate_dispatch(self) -> None:
        for status, conclusion in (("in_progress", ""), ("completed", "success")):
            with self.subTest(status=status):
                result, calls = self.run_validation(status=status, conclusion=conclusion)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), "42")
                self.assertTrue(all(call[:2] == ["run", "list"] for call in calls))
                self.assertTrue(
                    all(call[call.index("--event") + 1] == "pull_request" for call in calls)
                )

    def test_retries_the_failed_pr_run_and_waits_for_its_new_attempt(self) -> None:
        result, calls = self.run_validation(status="completed", conclusion="failure")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "42")
        reruns = [call for call in calls if call[:2] == ["run", "rerun"]]
        self.assertEqual(len(reruns), 1)
        self.assertEqual(reruns[0][2], "42")
        self.assertIn("--failed", reruns[0])
        self.assertEqual(sum(call[:2] == ["run", "view"] for call in calls), 2)

    def test_required_approval_is_not_bypassed(self) -> None:
        result, calls = self.run_validation(status="completed", conclusion="action_required")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires maintainer workflow approval", result.stderr)
        self.assertTrue(all(call[:2] == ["run", "list"] for call in calls))

    def test_builtin_token_retains_the_explicit_dispatch_path(self) -> None:
        result, calls = self.run_validation(status="completed", conclusion="success", token=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "42")
        self.assertTrue(
            all(call[call.index("--event") + 1] == "workflow_dispatch" for call in calls)
        )


class ChromeDeploymentReconciliationTests(unittest.TestCase):
    def run_reconciliation(
        self, runs: list[dict[str, object]]
    ) -> tuple[subprocess.CompletedProcess[str], list[list[str]], str]:
        step = WORKFLOW.read_text().split(
            "      - name: Reconcile the merged Chrome ECS deployment\n", maxsplit=1
        )[1]
        script = textwrap.dedent(step.split("        run: |\n", maxsplit=1)[1])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            gh = root / "gh"
            gh.write_text(
                f"#!{sys.executable}\n"
                + textwrap.dedent("""\
                    import json, os, sys
                    args = sys.argv[1:]
                    with open(os.environ["TEST_CALLS"], "a") as output:
                        output.write(json.dumps(args) + "\\n")
                    if args[0] == "api":
                        print("current-main")
                    elif args[:2] == ["run", "list"]:
                        print(os.environ["TEST_RUNS"])
                    elif args[:2] != ["workflow", "run"]:
                        sys.exit(2)
                """)
            )
            gh.chmod(0o755)
            calls = root / "calls"
            summary = root / "summary"
            result = subprocess.run(
                ["bash", "--noprofile", "--norc", "-c", script],
                env={
                    **os.environ,
                    "PATH": str(root) + os.pathsep + os.environ["PATH"],
                    "GITHUB_REPOSITORY": "owner/repository",
                    "GITHUB_STEP_SUMMARY": str(summary),
                    "TEST_CALLS": str(calls),
                    "TEST_RUNS": json.dumps(runs),
                },
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
            return (
                result,
                [json.loads(line) for line in calls.read_text().splitlines()],
                summary.read_text() if summary.exists() else "",
            )

    def test_dispatches_missing_main_validation_after_an_unrelated_bot_merge(self) -> None:
        # An API-Docker-only bot merge can advance main without a push run.
        # Neither an older main success nor a current-head PR success qualifies.
        result, calls, summary = self.run_reconciliation(
            [
                {
                    "databaseId": number,
                    "headSha": sha,
                    "event": event,
                    "status": "completed",
                    "conclusion": "success",
                }
                for number, sha, event in (
                    (1, "older-main", "push"),
                    (2, "current-main", "pull_request"),
                )
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        dispatches = [call for call in calls if call[:2] == ["workflow", "run"]]
        self.assertEqual(
            dispatches,
            [["workflow", "run", "etl-quality.yml", "--repo", "owner/repository", "--ref", "main"]],
        )
        self.assertIn("Requested missing ETL quality validation", summary)

    def test_latest_exact_main_run_controls_deployment(self) -> None:
        for status, conclusion, expected in (
            ("queued", "", None),
            ("in_progress", "", None),
            ("completed", "failure", None),
            ("completed", "cancelled", None),
            ("completed", "success", "scraper-deploy.yml"),
        ):
            with self.subTest(status=status, conclusion=conclusion):
                result, calls, _summary = self.run_reconciliation(
                    [
                        {
                            "databaseId": 2,
                            "headSha": "current-main",
                            "event": "workflow_dispatch",
                            "status": status,
                            "conclusion": conclusion,
                        },
                        {
                            "databaseId": 1,
                            "headSha": "current-main",
                            "event": "push",
                            "status": "completed",
                            "conclusion": "success",
                        },
                    ]
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                dispatches = [call[2] for call in calls if call[:2] == ["workflow", "run"]]
                self.assertEqual(dispatches, [expected] if expected else [])


class ChromeUpdateRefreshTests(unittest.TestCase):
    def test_clears_only_the_existing_auto_merge_before_the_branch_push(self) -> None:
        source = WORKFLOW.read_text()
        name = "      - name: Clear prior auto-merge before refreshing the update\n"
        self.assertLess(source.index(name), source.index("      - name: Commit and push"))
        step = source.split(name, maxsplit=1)[1].split("      - name:", maxsplit=1)[0]
        script = textwrap.dedent(step.split("        run: |\n", maxsplit=1)[1])
        script = script.replace("${{ github.event.repository.default_branch }}", "main")
        for pulls, expected in (
            ([], None),
            ([{"number": 86, "auto_merge": None}], None),
            ([{"number": 86, "auto_merge": {"merge_method": "squash"}}], "86"),
        ):
            with self.subTest(pulls=pulls), tempfile.TemporaryDirectory() as temporary:
                calls = Path(temporary) / "calls"
                mock = """gh() {
                    if [[ "$1" == api ]]; then
                      printf '%s\\n' "$TEST_PULLS"
                    else
                      printf '%s\\n' "$*" >> "$TEST_CALLS"
                    fi
                }
                """
                result = subprocess.run(
                    ["bash", "--noprofile", "--norc", "-c", mock + script],
                    env={
                        **os.environ,
                        "TEST_PULLS": json.dumps(pulls),
                        "TEST_CALLS": str(calls),
                        "GITHUB_REPOSITORY": "owner/repo",
                        "GITHUB_REPOSITORY_OWNER": "owner",
                        "UPDATE_BRANCH": UPDATE_BRANCH,
                    },
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls.exists(), expected is not None)
                if expected is not None:
                    self.assertEqual(
                        calls.read_text().strip(), "pr merge 86 --repo owner/repo --disable-auto"
                    )


class ChromeUpdateMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.summary = self.root / "summary"
        self.calls = self.root / "calls"
        gh = self.root / "gh"
        gh.write_text(
            f"#!{sys.executable}\n"
            + textwrap.dedent("""\
                import json, os, sys
                args = sys.argv[1:]
                with open(os.environ["TEST_CALLS"], "a") as output:
                    output.write(json.dumps(args) + "\\n")
                if args[:2] == ["pr", "view"]:
                    if "headRefOid,baseRefOid" in args:
                        print(json.dumps({"headRefOid": os.environ["TEST_HEAD"],
                                          "baseRefOid": os.environ["TEST_BASE"]}))
                    else:
                        print(os.environ["TEST_PR_STATE"])
                elif args[0] == "api":
                    print(os.environ["TEST_CURRENT_BASE"])
                elif args[:2] != ["pr", "merge"]:
                    sys.exit(2)
            """)
        )
        gh.chmod(0o755)
        self.environment = {
            **os.environ,
            "PATH": str(self.root) + os.pathsep + os.environ["PATH"],
            "GITHUB_REPOSITORY": "owner/repository",
            "GITHUB_STEP_SUMMARY": str(self.summary),
            "HAS_CHROME_UPDATE_TOKEN": "true",
            "TEST_CALLS": str(self.calls),
            "TEST_HEAD": "tested-head",
            "TEST_BASE": "tested-base",
            "TEST_CURRENT_BASE": "tested-base",
            "TEST_PR_STATE": "OPEN",
        }

    def run_merge(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "--noprofile", "--norc", "-c", _merge_script()],
            env=self.environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )

    def test_queues_native_merge_for_the_validated_head(self) -> None:
        result = self.run_merge()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        merge = next(call for call in calls if call[:2] == ["pr", "merge"])
        self.assertIn("--auto", merge)
        self.assertNotIn("--admin", merge)
        self.assertEqual(merge[merge.index("--match-head-commit") + 1], "tested-head")
        self.assertIn("waiting for the required pull-request checks", self.summary.read_text())
        self.assertNotIn("was merged", self.summary.read_text())

    def test_builtin_token_explains_required_workflow_approval(self) -> None:
        self.environment["HAS_CHROME_UPDATE_TOKEN"] = "false"
        result = self.run_merge()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("::warning::Approve", result.stdout)
        self.assertIn("CHROME_UPDATE_TOKEN", result.stdout)

    def test_reports_an_already_completed_merge(self) -> None:
        self.environment["TEST_PR_STATE"] = "MERGED"
        result = self.run_merge()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("was merged", self.summary.read_text())

    def test_head_or_base_changes_never_request_a_merge(self) -> None:
        for variable in ("TEST_HEAD", "TEST_BASE", "TEST_CURRENT_BASE"):
            with self.subTest(variable=variable):
                original = self.environment[variable]
                self.environment[variable] = "changed"
                self.calls.unlink(missing_ok=True)
                result = self.run_merge()
                self.assertNotEqual(result.returncode, 0)
                calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
                self.assertFalse(any(call[:2] == ["pr", "merge"] for call in calls))
                self.environment[variable] = original


class ChromeUpdateBranchTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repository = self.root / "checkout"
        self.repository.mkdir()
        self.remote = self.root / "origin.git"
        self.output = self.root / "output"
        self.environment = {
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_AUTHOR_NAME": "github-actions[bot]",
            "GIT_AUTHOR_EMAIL": BOT_EMAIL,
            "GIT_COMMITTER_NAME": "github-actions[bot]",
            "GIT_COMMITTER_EMAIL": BOT_EMAIL,
            "UPDATE_BRANCH": UPDATE_BRANCH,
            "GITHUB_OUTPUT": str(self.output),
        }
        self.git("init", "--bare", str(self.remote))
        self.git("init", "--initial-branch=main")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.hooksPath", os.devnull)
        self.git("remote", "add", "origin", str(self.remote))
        for path in GENERATED_PATHS:
            self.write(path, "initial\n")
        self.commit("Initial main")
        self.git("push", "origin", "main")
        self.git("switch", "-c", UPDATE_BRANCH)

    def git(self, *arguments: str) -> str:
        result = subprocess.run(
            ["git", *arguments],
            cwd=self.repository,
            env=self.environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.stdout.strip()

    def write(self, path: str, content: str) -> None:
        target = self.repository / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def commit(self, message: str) -> None:
        self.git("add", ".")
        self.git("commit", "-m", message)

    def prepare_update(self, *, merged: bool = False, identical: bool = False) -> str:
        self.git("push", "origin", UPDATE_BRANCH)
        remote_sha = self.git("rev-parse", "HEAD")
        self.git("switch", "main")
        if merged:
            self.git("merge", "--ff-only", UPDATE_BRANCH)
        if not identical:
            self.write("unrelated.txt", "new work on main\n")
            self.commit("Advance main")
        self.git("push", "origin", "main")
        self.git("switch", "--force-create", UPDATE_BRANCH, "origin/main")
        self.write(LOCK, "candidate\n")
        return remote_sha

    def run_updater(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "--noprofile", "--norc", "-c", _push_script()],
            cwd=self.repository,
            env=self.environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )

    def assert_refreshed(self, previous_sha: str) -> None:
        result = self.run_updater()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        remote_sha = self.git("ls-remote", "origin", f"refs/heads/{UPDATE_BRANCH}").split()[0]
        self.assertNotEqual(remote_sha, previous_sha)
        self.assertEqual(remote_sha, self.git("rev-parse", "HEAD"))
        self.assertEqual(self.output.read_text(), f"head_sha={remote_sha}\nreused=false\n")
        self.assertEqual(self.git("show", "HEAD:unrelated.txt"), "new work on main")
        self.assertEqual(self.git("diff", "--name-only", "origin/main..HEAD"), LOCK)

    def assert_protected(self, previous_sha: str) -> None:
        result = self.run_updater()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Refusing to overwrite a Chrome update branch", result.stderr)
        remote_sha = self.git("ls-remote", "origin", f"refs/heads/{UPDATE_BRANCH}").split()[0]
        self.assertEqual(remote_sha, previous_sha)
        self.assertFalse(self.output.exists())

    def test_refreshes_a_fully_merged_branch(self) -> None:
        self.write(LOCK, "previous release\n")
        self.commit("Previous Chrome update")
        previous_sha = self.prepare_update(merged=True)
        self.assertEqual(self.git("rev-list", "--count", f"origin/main..{previous_sha}"), "0")
        self.assert_refreshed(previous_sha)

    def test_refreshes_an_unmerged_bot_update(self) -> None:
        self.write(LOCK, "previous release\n")
        self.commit("Previous Chrome update")
        self.assert_refreshed(self.prepare_update())

    def test_reuses_an_identical_bot_update(self) -> None:
        self.write(LOCK, "candidate\n")
        self.commit("Current Chrome update")
        previous_sha = self.prepare_update(identical=True)
        result = self.run_updater()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.output.read_text(), f"head_sha={previous_sha}\nreused=true\n")
        self.assertEqual(
            self.git("ls-remote", "origin", f"refs/heads/{UPDATE_BRANCH}").split()[0], previous_sha
        )

    def test_protects_an_unmerged_human_author(self) -> None:
        self.environment["GIT_AUTHOR_EMAIL"] = HUMAN_EMAIL
        self.write(LOCK, "human edit\n")
        self.commit("Human Chrome edit")
        self.assert_protected(self.prepare_update())

    def test_protects_an_unmerged_human_committer(self) -> None:
        self.environment["GIT_COMMITTER_EMAIL"] = HUMAN_EMAIL
        self.write(LOCK, "human edit\n")
        self.commit("Human Chrome edit")
        self.assert_protected(self.prepare_update())

    def test_protects_out_of_scope_bot_changes(self) -> None:
        self.write("unrelated.txt", "unmerged bot edit\n")
        self.commit("Out of scope bot edit")
        self.assert_protected(self.prepare_update())
