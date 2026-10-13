"""Exercise bounded scraper build retries without weakening build failures."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

MODULE_PATH = Path(__file__).with_name("build_scraper_image.py")
spec = importlib.util.spec_from_file_location("build_scraper_image", MODULE_PATH)
assert spec is not None and spec.loader is not None
BUILD = importlib.util.module_from_spec(spec)
spec.loader.exec_module(BUILD)

TRANSIENT_DIGEST = (
    "#11 ERROR: digest mismatch sha256:"
    f"{BUILD.CANONICAL_503_SHA256}: sha256:{'a' * 64}\n"
    "ERROR: failed to build: failed to solve: digest mismatch sha256:"
    f"{BUILD.CANONICAL_503_SHA256}: sha256:{'a' * 64}\n"
)


class ScraperBuildRetryTests(unittest.TestCase):
    def run_attempts(self, *results: tuple[int, str]) -> tuple[int, Mock, Mock]:
        runner = Mock(
            side_effect=[subprocess.CompletedProcess([], code, output) for code, output in results]
        )
        sleeper = Mock()
        with contextlib.redirect_stderr(io.StringIO()):
            code = BUILD.build_with_retry(runner=runner, sleeper=sleeper)
        return code, runner, sleeper

    def test_success_needs_only_one_attempt(self) -> None:
        code, runner, sleeper = self.run_attempts((0, "done"))
        self.assertEqual(code, 0)
        self.assertEqual(runner.call_count, 1)
        sleeper.assert_not_called()

    def test_known_canonical_503_body_is_retried_then_must_build_successfully(self) -> None:
        code, runner, sleeper = self.run_attempts((1, TRANSIENT_DIGEST), (0, "done"))
        self.assertEqual(code, 0)
        self.assertEqual(runner.call_count, 2)
        sleeper.assert_called_once_with(20)

    def test_signal_termination_is_not_retried_even_after_transient_output(self) -> None:
        for status in (-15, 130, 137, 143):
            with self.subTest(status=status):
                code, runner, sleeper = self.run_attempts((status, TRANSIENT_DIGEST))
                self.assertEqual(code, status)
                self.assertEqual(runner.call_count, 1)
                sleeper.assert_not_called()

    def test_exhaustion_preserves_docker_failure_status(self) -> None:
        code, runner, sleeper = self.run_attempts(*[(17, TRANSIENT_DIGEST)] * 3)
        self.assertEqual(code, 17)
        self.assertEqual(runner.call_count, 3)
        self.assertEqual([call.args[0] for call in sleeper.call_args_list], [20, 40])

    def test_other_digest_mismatches_and_assertions_are_not_retried(self) -> None:
        for output in (
            TRANSIENT_DIGEST.replace(BUILD.CANONICAL_503_SHA256, "b" * 64),
            "AssertionError\nERROR: process python assertion "
            "did not complete successfully: exit code: 1",
            "ERROR: failed to fetch https://example.test/package: 404 Not Found",
            "ERROR: failed to fetch https://example.test/package: 401 Unauthorized",
            "ERROR: failed to build: context canceled",
            "ERROR: process apt-get failed with exit code 100",
            "ERROR: process test 'https://example.test HTTP 503' "
            "did not complete successfully: exit code: 1",
            TRANSIENT_DIGEST + "ERROR: process python assertion failed\n",
            TRANSIENT_DIGEST + f"ERROR: digest mismatch sha256:{'b' * 64}: sha256:{'a' * 64}\n",
        ):
            with self.subTest(output=output):
                code, runner, sleeper = self.run_attempts((7, output))
                self.assertEqual(code, 7)
                self.assertEqual(runner.call_count, 1)
                sleeper.assert_not_called()

    def test_nontransient_failure_after_a_retry_stops_immediately(self) -> None:
        code, runner, sleeper = self.run_attempts(
            (1, TRANSIENT_DIGEST), (9, "ERROR: image assertion failed")
        )
        self.assertEqual(code, 9)
        self.assertEqual(runner.call_count, 2)
        sleeper.assert_called_once_with(20)

    def test_explicit_upstream_http_errors_are_retryable(self) -> None:
        for status in ("502 Bad Gateway", "503 Service Unavailable", "504 Gateway Timeout"):
            with self.subTest(status=status):
                output = (
                    "ERROR: failed to solve: unexpected status code "
                    f"https://snapshot.ubuntu.com/a: {status}"
                )
                self.assertTrue(BUILD.transient_download_failure(output))
                apt_output = (
                    f"#16 1.0 E: Failed to fetch https://snapshot.ubuntu.com/a {status}\n"
                    "#16 1.0 E: Some index files failed to download.\n"
                    '#16 ERROR: process "/bin/sh -c apt-get update" '
                    "did not complete successfully: exit code: 100\n"
                )
                self.assertTrue(BUILD.transient_download_failure(apt_output))

    def test_real_apt_503_spacing_retries_the_failed_download(self) -> None:
        # Captured from the failed Ubuntu image update's APT/BuildKit output.
        output = (
            "#16 482.8 E: Failed to fetch "
            "https://snapshot.ubuntu.com/ubuntu/20261001T180000Z/"
            "dists/resolute-security/InRelease  503  Service Unavailable "
            "[IP: 185.125.189.37 443]\n"
            "#16 482.8 E: Some index files failed to download. "
            "They have been ignored, or old ones used instead.\n"
            '#16 ERROR: process "/bin/sh -c apt-get --error-on=any update" '
            "did not complete successfully: exit code: 100\n"
            "ERROR: failed to build: failed to solve: process "
            '"/bin/sh -c apt-get --error-on=any update" '
            "did not complete successfully: exit code: 100\n"
        )
        code, runner, sleeper = self.run_attempts((1, output), (0, "done"))
        self.assertEqual(code, 0)
        self.assertEqual(runner.call_count, 2)
        sleeper.assert_called_once_with(20)
        self.assertFalse(
            BUILD.transient_download_failure(
                output + "E: Failed to fetch https://snapshot.ubuntu.com/other 404 Not Found\n"
            )
        )

    def test_an_http_status_in_ordinary_build_output_does_not_trigger_retry(self) -> None:
        self.assertFalse(BUILD.transient_download_failure("test fixture HTTP 503"))
        self.assertFalse(
            BUILD.transient_download_failure("HTTP 503\nERROR: image assertion failed")
        )

    def test_run_build_streams_output_and_preserves_process_status(self) -> None:
        output = io.StringIO()
        command = [sys.executable, "-c", "import sys; print('build output'); sys.exit(23)"]
        with patch.object(BUILD, "BUILD_COMMAND", command), contextlib.redirect_stdout(output):
            result = BUILD.run_build()
        self.assertEqual(result.returncode, 23)
        self.assertEqual(result.stdout, "build output\n")
        self.assertEqual(output.getvalue(), "build output\n")


if __name__ == "__main__":
    unittest.main()
