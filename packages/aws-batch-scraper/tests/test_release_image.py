"""Tests for fail-closed scraper image release integrity checks."""

import json
import subprocess
from collections.abc import Sequence

import pytest
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


class StubRunner:
    """Return ordered subprocess results and retain exact argument arrays."""

    def __init__(self, *outputs: tuple[int, str]) -> None:
        self.outputs = list(outputs)
        self.calls: list[list[str]] = []

    def __call__(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(command))
        returncode, stdout = self.outputs.pop(0)
        return subprocess.CompletedProcess(command, returncode, stdout, "")


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


def _scan_payload(*, high: int = 0, critical: int = 0) -> str:
    return json.dumps(
        {
            "registryId": ACCOUNT_ID,
            "repositoryName": "ujs-scraper",
            "imageId": {"imageDigest": DIGEST},
            "imageScanStatus": {"status": "COMPLETE"},
            "imageScanFindings": {
                "findingSeverityCounts": {
                    "HIGH": high,
                    "CRITICAL": critical,
                }
            },
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
        (
            0,
            json.dumps(
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
            ),
        ),
        (0, ""),
        (0, _scan_payload()),
    )

    assert verify_remote_scan(_target(), runner=runner) == DIGEST
    assert "image-scan-complete" in runner.calls[1]
    assert f"imageDigest={DIGEST}" in runner.calls[2]
    assert all(
        call[index : index + 2] == ["--registry-id", ACCOUNT_ID]
        for call in runner.calls
        for index in [call.index("--registry-id")]
    )


@pytest.mark.parametrize(("high", "critical"), [(1, 0), (0, 1), (4, 2)])
def test_scan_gate_rejects_any_high_or_critical_finding(high: int, critical: int) -> None:
    runner = StubRunner(
        (
            0,
            json.dumps(
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
            ),
        ),
        (0, ""),
        (0, _scan_payload(high=high, critical=critical)),
    )

    with pytest.raises(ReleaseIntegrityError, match="blocked release"):
        verify_remote_scan(_target(), runner=runner)
