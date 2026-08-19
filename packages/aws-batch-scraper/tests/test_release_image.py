"""Tests for fail-closed scraper image release integrity checks."""

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest
from aws_batch_scraper import release_image
from aws_batch_scraper.release_image import (
    REVISION_LABEL,
    ReleaseIntegrityError,
    ReleaseTarget,
    preflight_release,
    verify_local_image,
    verify_remote_scan,
)

COMMIT = "a" * 40
DIGEST = "sha256:" + "b" * 64
ACCOUNT_ID = "123456789012"
SCAN_COMPLETED_AT = "2026-08-19T14:10:00+00:00"
VULNERABILITY_SOURCE_UPDATED_AT = "2026-08-19T13:45:00+00:00"


class StubRunner:
    """Return ordered subprocess results and retain exact argument arrays."""

    def __init__(self, *outputs: tuple[int, str] | tuple[int, str, str]) -> None:
        self.outputs = list(outputs)
        self.calls: list[list[str]] = []

    def __call__(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(command))
        output = self.outputs.pop(0)
        returncode, stdout = output[:2]
        stderr = output[2] if len(output) == 3 else ""
        return subprocess.CompletedProcess(command, returncode, stdout, stderr)


def _target() -> ReleaseTarget:
    return ReleaseTarget(
        account_id=ACCOUNT_ID,
        repository="ujs-scraper",
        region="us-east-1",
        tag=COMMIT,
    )


def _immutable_repository_payload() -> str:
    return json.dumps(
        {
            "repositories": [
                {
                    "registryId": ACCOUNT_ID,
                    "repositoryName": "ujs-scraper",
                    "repositoryUri": (f"{ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/ujs-scraper"),
                    "imageTagMutability": "IMMUTABLE",
                    "imageScanningConfiguration": {"scanOnPush": True},
                }
            ]
        }
    )


def _scan_payload(
    *,
    status: str = "COMPLETE",
    high: int = 0,
    critical: int = 0,
) -> str:
    findings_key = "enhancedFindings" if status == "ACTIVE" else "findings"
    return json.dumps(
        {
            "registryId": ACCOUNT_ID,
            "repositoryName": "ujs-scraper",
            "imageId": {"imageDigest": DIGEST},
            "imageScanStatus": {"status": status},
            "imageScanFindings": {
                "imageScanCompletedAt": SCAN_COMPLETED_AT,
                "vulnerabilitySourceUpdatedAt": VULNERABILITY_SOURCE_UPDATED_AT,
                "findingSeverityCounts": {
                    "HIGH": high,
                    "CRITICAL": critical,
                },
                findings_key: [],
            },
        }
    )


def _digest_payload() -> str:
    return json.dumps(
        {
            "imageDetails": [
                {
                    "registryId": ACCOUNT_ID,
                    "repositoryName": "ujs-scraper",
                    "imageDigest": DIGEST,
                    "imageTags": [COMMIT],
                }
            ]
        }
    )


def test_preflight_requires_clean_exact_head_and_absent_remote_tag() -> None:
    runner = StubRunner(
        (0, f"{COMMIT}\n"),
        (0, ""),
        (0, _immutable_repository_payload()),
        (0, json.dumps({"imageIds": [{"imageTag": "older"}]})),
    )

    preflight_release(_target(), runner=runner)

    assert runner.calls[1] == [
        "git",
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    ]
    assert "describe-repositories" in runner.calls[2]
    assert "list-images" in runner.calls[3]
    assert all(
        call[index : index + 2] == ["--registry-id", ACCOUNT_ID]
        for call in runner.calls[2:]
        for index in [call.index("--registry-id")]
    )


@pytest.mark.parametrize(
    ("tag", "status", "message"),
    [
        ("c" * 40, "", "exactly equal"),
        (COMMIT, " M packages/etl/Dockerfile\n", "clean checkout"),
        (COMMIT, "?? untracked.txt\n", "clean checkout"),
    ],
)
def test_preflight_rejects_wrong_commit_or_dirty_source(
    tag: str,
    status: str,
    message: str,
) -> None:
    runner = StubRunner((0, f"{COMMIT}\n"), (0, status))

    with pytest.raises(ReleaseIntegrityError, match=message):
        preflight_release(
            ReleaseTarget(
                account_id=ACCOUNT_ID,
                repository="ujs-scraper",
                region="us-east-1",
                tag=tag,
            ),
            runner=runner,
        )


def test_preflight_rejects_existing_remote_tag() -> None:
    runner = StubRunner(
        (0, f"{COMMIT}\n"),
        (0, ""),
        (0, _immutable_repository_payload()),
        (0, json.dumps({"imageIds": [{"imageTag": COMMIT}]})),
    )

    with pytest.raises(ReleaseIntegrityError, match="already exists"):
        preflight_release(_target(), runner=runner)


def test_preflight_requires_ecr_to_enforce_tag_immutability() -> None:
    mutable_repository = json.dumps(
        {
            "repositories": [
                {
                    "registryId": ACCOUNT_ID,
                    "repositoryName": "ujs-scraper",
                    "repositoryUri": (f"{ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/ujs-scraper"),
                    "imageTagMutability": "MUTABLE",
                    "imageScanningConfiguration": {"scanOnPush": True},
                }
            ]
        }
    )
    runner = StubRunner((0, f"{COMMIT}\n"), (0, ""), (0, mutable_repository))

    with pytest.raises(ReleaseIntegrityError, match="IMMUTABLE"):
        preflight_release(_target(), runner=runner)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("registryId", "999999999999", "registry account"),
        (
            "repositoryUri",
            "999999999999.dkr.ecr.us-east-1.amazonaws.com/ujs-scraper",
            "repository URI",
        ),
        ("imageScanningConfiguration", {"scanOnPush": False}, "scan-on-push"),
    ],
)
def test_preflight_binds_policy_to_exact_scanned_registry(
    field: str,
    value: object,
    message: str,
) -> None:
    repository = json.loads(_immutable_repository_payload())["repositories"][0]
    repository[field] = value
    runner = StubRunner(
        (0, f"{COMMIT}\n"),
        (0, ""),
        (0, json.dumps({"repositories": [repository]})),
    )

    with pytest.raises(ReleaseIntegrityError, match=message):
        preflight_release(_target(), runner=runner)


def test_local_image_must_carry_exact_commit_label() -> None:
    runner = StubRunner((0, json.dumps({REVISION_LABEL: "c" * 40})))

    with pytest.raises(ReleaseIntegrityError, match=REVISION_LABEL):
        verify_local_image("ujs-scraper:commit", COMMIT, runner=runner)


def test_scan_gate_returns_digest_only_after_complete_clean_scan() -> None:
    runner = StubRunner(
        (0, _digest_payload()),
        (0, _scan_payload()),
    )

    assert verify_remote_scan(_target(), runner=runner) == DIGEST
    assert "describe-image-scan-findings" in runner.calls[1]
    assert "image-scan-complete" not in runner.calls[1]
    assert f"imageDigest={DIGEST}" in runner.calls[1]
    assert all(
        call[index : index + 2] == ["--registry-id", ACCOUNT_ID]
        for call in runner.calls
        for index in [call.index("--registry-id")]
    )


@pytest.mark.parametrize(("high", "critical"), [(1, 0), (0, 1), (4, 2)])
def test_scan_gate_rejects_any_high_or_critical_finding(high: int, critical: int) -> None:
    runner = StubRunner(
        (0, _digest_payload()),
        (0, _scan_payload(high=high, critical=critical)),
    )

    with pytest.raises(ReleaseIntegrityError, match="blocked release"):
        verify_remote_scan(_target(), runner=runner)


def test_scan_gate_polls_pending_scan_until_complete() -> None:
    delays: list[float] = []
    runner = StubRunner(
        (0, _digest_payload()),
        (0, _scan_payload(status="IN_PROGRESS")),
        (0, _scan_payload(status="PENDING")),
        (0, _scan_payload()),
    )

    digest = verify_remote_scan(
        _target(),
        runner=runner,
        sleeper=delays.append,
        max_attempts=3,
        poll_interval_seconds=0.25,
    )

    assert digest == DIGEST
    assert delays == [0.25, 0.25]
    assert sum("describe-image-scan-findings" in call for call in runner.calls) == 3


def test_scan_gate_retries_initial_scan_not_found() -> None:
    delays: list[float] = []
    runner = StubRunner(
        (0, _digest_payload()),
        (
            255,
            "",
            "An error occurred (ScanNotFoundException) when calling the "
            "DescribeImageScanFindings operation: scan is not registered",
        ),
        (0, _scan_payload()),
    )

    assert (
        verify_remote_scan(
            _target(),
            runner=runner,
            sleeper=delays.append,
            max_attempts=2,
            poll_interval_seconds=1,
        )
        == DIGEST
    )
    assert delays == [1]


def test_scan_gate_does_not_accept_scan_not_found_as_an_unstructured_substring() -> None:
    delays: list[float] = []
    runner = StubRunner(
        (0, _digest_payload()),
        (255, "", "wrapper failed; text happened to mention ScanNotFoundException"),
    )

    with pytest.raises(ReleaseIntegrityError, match="findings command failed"):
        verify_remote_scan(
            _target(),
            runner=runner,
            sleeper=delays.append,
            max_attempts=2,
        )
    assert delays == []


def test_scan_gate_does_not_retry_authorization_failure() -> None:
    delays: list[float] = []
    runner = StubRunner(
        (0, _digest_payload()),
        (255, "", "An error occurred (AccessDeniedException) when calling the operation"),
    )

    with pytest.raises(ReleaseIntegrityError, match="findings command failed"):
        verify_remote_scan(
            _target(),
            runner=runner,
            sleeper=delays.append,
            max_attempts=2,
        )
    assert delays == []


@pytest.mark.parametrize(
    "status",
    [
        "FAILED",
        "UNSUPPORTED_IMAGE",
        "SCAN_ELIGIBILITY_EXPIRED",
        "FINDINGS_UNAVAILABLE",
        "LIMIT_EXCEEDED",
        "IMAGE_ARCHIVED",
    ],
)
def test_scan_gate_rejects_terminal_scan_status(status: str) -> None:
    runner = StubRunner(
        (0, _digest_payload()),
        (0, _scan_payload(status=status)),
    )

    with pytest.raises(ReleaseIntegrityError, match=f"terminal status {status}"):
        verify_remote_scan(_target(), runner=runner, sleeper=lambda _: None)


def test_scan_gate_has_bounded_pending_timeout() -> None:
    delays: list[float] = []
    runner = StubRunner(
        (0, _digest_payload()),
        (0, _scan_payload(status="IN_PROGRESS")),
        (0, _scan_payload(status="IN_PROGRESS")),
    )

    with pytest.raises(ReleaseIntegrityError, match="after 2 checks.*IN_PROGRESS"):
        verify_remote_scan(
            _target(),
            runner=runner,
            sleeper=delays.append,
            max_attempts=2,
            poll_interval_seconds=0.5,
        )
    assert delays == [0.5]


@pytest.mark.parametrize("max_attempts", [True, 0, -1])
def test_scan_gate_rejects_invalid_attempt_limit(max_attempts: int) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        verify_remote_scan(_target(), runner=StubRunner(), max_attempts=max_attempts)


@pytest.mark.parametrize("poll_interval", [True, -1, float("nan"), float("inf")])
def test_scan_gate_rejects_invalid_poll_interval(poll_interval: float) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        verify_remote_scan(
            _target(),
            runner=StubRunner(),
            poll_interval_seconds=poll_interval,
        )


def test_scan_gate_accepts_active_enhanced_scan() -> None:
    runner = StubRunner(
        (0, _digest_payload()),
        (0, _scan_payload(status="ACTIVE")),
    )

    assert verify_remote_scan(_target(), runner=runner) == DIGEST


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("imageScanCompletedAt", "completion timestamp"),
        ("vulnerabilitySourceUpdatedAt", "vulnerability-source update timestamp"),
        ("findingSeverityCounts", "severity counts"),
    ],
)
def test_scan_gate_rejects_missing_completed_scan_metadata(field: str, message: str) -> None:
    payload = json.loads(_scan_payload())
    payload["imageScanFindings"].pop(field)
    runner = StubRunner((0, _digest_payload()), (0, json.dumps(payload)))

    with pytest.raises(ReleaseIntegrityError, match=message):
        verify_remote_scan(_target(), runner=runner)


@pytest.mark.parametrize(
    "value",
    [None, "", "not-a-timestamp", "2026-08-19T14:10:00"],
)
@pytest.mark.parametrize(
    "field",
    ["imageScanCompletedAt", "vulnerabilitySourceUpdatedAt"],
)
def test_scan_gate_rejects_invalid_completed_scan_timestamps(
    field: str,
    value: object,
) -> None:
    payload = json.loads(_scan_payload())
    payload["imageScanFindings"][field] = value
    runner = StubRunner((0, _digest_payload()), (0, json.dumps(payload)))

    with pytest.raises(ReleaseIntegrityError, match="timestamp"):
        verify_remote_scan(_target(), runner=runner)


def test_scan_gate_allows_omitted_individual_high_and_critical_keys() -> None:
    payload = json.loads(_scan_payload())
    payload["imageScanFindings"]["findingSeverityCounts"] = {"MEDIUM": 3, "LOW": 2}
    runner = StubRunner((0, _digest_payload()), (0, json.dumps(payload)))

    assert verify_remote_scan(_target(), runner=runner) == DIGEST


@pytest.mark.parametrize("count", [0, 1])
def test_scan_gate_rejects_unknown_severity_even_when_zero(count: int) -> None:
    payload = json.loads(_scan_payload())
    payload["imageScanFindings"]["findingSeverityCounts"]["FUTURE"] = count
    runner = StubRunner((0, _digest_payload()), (0, json.dumps(payload)))

    with pytest.raises(ReleaseIntegrityError, match="unknown severity"):
        verify_remote_scan(_target(), runner=runner)


def test_scan_gate_uses_aggregate_counts_when_detailed_findings_have_next_token() -> None:
    payload = json.loads(_scan_payload(high=1))
    payload["nextToken"] = "more-detailed-findings"
    runner = StubRunner((0, _digest_payload()), (0, json.dumps(payload)))

    with pytest.raises(ReleaseIntegrityError, match="blocked release"):
        verify_remote_scan(_target(), runner=runner)


def _verify_scan_args() -> list[str]:
    return [
        "verify-scan",
        "--account-id",
        ACCOUNT_ID,
        "--repository",
        "ujs-scraper",
        "--region",
        "us-east-1",
        "--tag",
        COMMIT,
    ]


def test_verify_scan_cli_prints_only_full_verified_uri(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(release_image, "verify_remote_scan", lambda _: DIGEST)

    assert release_image.main(_verify_scan_args()) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == (f"{ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/ujs-scraper@{DIGEST}\n")


def test_verify_scan_cli_failure_is_nonzero_and_prints_no_uri(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_scan(_target: ReleaseTarget) -> str:
        raise ReleaseIntegrityError("scan still pending")

    monkeypatch.setattr(release_image, "verify_remote_scan", fail_scan)

    assert release_image.main(_verify_scan_args()) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "scan still pending" in captured.err


def test_push_recipe_cannot_mask_scan_cli_failure_with_a_later_echo() -> None:
    recipe = (Path(__file__).resolve().parents[1] / "just" / "aws-batch-scraper.just").read_text()
    verify_lines = [line.strip() for line in recipe.splitlines() if "verify-scan" in line]

    assert len(verify_lines) == 1
    assert verify_lines[0].startswith("@cd packages/aws-batch-scraper && uv run ")
    assert "digest=$(" not in recipe
    assert "@$digest" not in recipe
