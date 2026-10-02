"""Exercise the real Cloudflare upload step with deterministic CLI responses."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / "workflows/frontend-quality.yml"
VERSION = "015bb91a-100f-4cf7-8530-2af9e5ca75c1"
SHA = "a" * 40
TAG = "github-123-1"
EVIDENCE = {
    "id": VERSION,
    "annotations": {"workers/tag": TAG, "workers/message": f"commit={SHA} run=test"},
}


def _upload_script() -> str:
    step = (
        WORKFLOW.read_text()
        .split("      - name: Upload the exact validated Worker version\n", maxsplit=1)[1]
        .split("      - name:", maxsplit=1)[0]
    )
    return textwrap.dedent(step.split("        run: |\n", maxsplit=1)[1])


FAKE_CLI = r"""
import json
import os
import sys
from pathlib import Path

root = Path(os.environ["FAKE_CLI_ROOT"])
state_path = root / "state.json"
state = json.loads(state_path.read_text())
arguments = sys.argv[1:]
if Path(sys.argv[0]).name == "sleep":
    assert arguments == ["3"], arguments
    state["sleeps"] += 1
    state_path.write_text(json.dumps(state))
    sys.exit(0)
assert arguments[:3] == ["--no-install", "wrangler", "versions"], arguments
operation = arguments[3]
assert operation in {"upload", "list", "view"}, arguments
if operation == "view":
    assert arguments[4:] == [os.environ["EXPECTED_VERSION"], "--env", "production", "--json"]
elif operation == "list":
    assert arguments[4:] == ["--env", "production", "--json"]
else:
    assert arguments[4:9] == ["--env", "production", "--strict", "--tag", "github-123-1"]
    assert arguments[9] == "--message"
    assert arguments[10].startswith("commit=" + os.environ["GITHUB_SHA"] + " ")
attempt = state[operation]
state[operation] += 1
state_path.write_text(json.dumps(state))
responses = json.loads((root / "responses.json").read_text())[operation]
response = responses[min(attempt, len(responses) - 1)]
if response.get("unavailable"):
    print("Worker version could not be found [code: 100146]", file=sys.stderr)
    sys.exit(1)
if "raw" in response:
    print(response["raw"])
elif "body" in response:
    print(json.dumps(response["body"]))
sys.exit(response.get("exit_code", 0))
"""


class FrontendUploadTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "output"
        self.state_path = self.root / "state.json"
        self.state_path.write_text(
            json.dumps(dict.fromkeys(("upload", "list", "view", "sleeps"), 0))
        )
        for name in ("npx", "sleep"):
            executable = self.root / name
            executable.write_text(f"#!{sys.executable}\n" + FAKE_CLI)
            executable.chmod(0o755)
        self.responses = {
            "upload": [{}],
            "list": [{"body": [EVIDENCE]}],
            "view": [{"body": EVIDENCE}],
        }

    def run_upload(self) -> subprocess.CompletedProcess[str]:
        (self.root / "responses.json").write_text(json.dumps(self.responses))
        return subprocess.run(
            ["bash", "--noprofile", "--norc", "-c", _upload_script()],
            env={
                **os.environ,
                "PATH": f"{self.root}{os.pathsep}{os.environ['PATH']}",
                "FAKE_CLI_ROOT": str(self.root),
                "EXPECTED_VERSION": VERSION,
                "RUNNER_TEMP": str(self.root),
                "GITHUB_OUTPUT": str(self.output),
                "GITHUB_RUN_ID": "123",
                "GITHUB_RUN_ATTEMPT": "1",
                "GITHUB_SHA": SHA,
                "GITHUB_SERVER_URL": "https://github.com",
                "GITHUB_REPOSITORY": "example/repository",
            },
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )

    def state(self) -> dict[str, int]:
        return json.loads(self.state_path.read_text())

    def assert_verified(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.output.read_text(), f"version={VERSION}\n")
        self.assertEqual(self.state()["upload"], 1)

    def assert_refused(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.state()["upload"], 1)

    def test_visible_version_is_verified_without_waiting(self) -> None:
        self.assert_verified(self.run_upload())
        self.assertEqual(self.state(), {"upload": 1, "list": 1, "view": 1, "sleeps": 0})

    def test_listed_version_becomes_readable_without_another_upload(self) -> None:
        self.responses["view"] = [{"unavailable": True}] * 2 + [{"body": EVIDENCE}]
        self.assert_verified(self.run_upload())
        self.assertEqual(self.state(), {"upload": 1, "list": 1, "view": 3, "sleeps": 2})

    def test_unreadable_version_stops_after_ten_reads_without_activation_output(self) -> None:
        self.responses["view"] = [{"unavailable": True}]
        result = self.run_upload()
        self.assert_refused(result)
        self.assertIn("refusing activation", result.stderr)
        self.assertEqual(self.state(), {"upload": 1, "list": 1, "view": 10, "sleeps": 9})

    def test_wrong_version_id_fails_without_retrying(self) -> None:
        self.responses["view"] = [{"body": {**EVIDENCE, "id": "another-version"}}]
        self.assert_refused(self.run_upload())
        self.assertEqual(self.state()["view"], 1)
        self.assertEqual(self.state()["sleeps"], 0)

    def test_wrong_run_tag_fails_without_retrying(self) -> None:
        evidence = {
            **EVIDENCE,
            "annotations": {**EVIDENCE["annotations"], "workers/tag": "another-run"},
        }
        self.responses["view"] = [{"body": evidence}]
        self.assert_refused(self.run_upload())
        self.assertEqual(self.state()["view"], 1)

    def test_wrong_commit_fails_without_retrying(self) -> None:
        evidence = {
            **EVIDENCE,
            "annotations": {**EVIDENCE["annotations"], "workers/message": "commit=other"},
        }
        self.responses["view"] = [{"body": evidence}]
        self.assert_refused(self.run_upload())
        self.assertEqual(self.state()["view"], 1)

    def test_malformed_version_json_fails_without_retrying(self) -> None:
        self.responses["view"] = [{"raw": "not-json"}]
        self.assert_refused(self.run_upload())
        self.assertEqual(self.state()["view"], 1)

    def test_ambiguous_upload_exit_is_reconciled_without_repeating_upload(self) -> None:
        self.responses["upload"] = [{"exit_code": 1}]
        self.responses["view"] = [{"unavailable": True}, {"body": EVIDENCE}]
        self.assert_verified(self.run_upload())

    def test_duplicate_run_tags_do_not_select_an_arbitrary_version(self) -> None:
        self.responses["list"] = [{"body": [EVIDENCE, {**EVIDENCE, "id": "duplicate"}]}]
        self.assert_refused(self.run_upload())
        self.assertEqual(self.state()["list"], 10)
        self.assertEqual(self.state()["view"], 0)


if __name__ == "__main__":
    unittest.main()
