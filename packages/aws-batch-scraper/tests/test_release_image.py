"""Tests for fail-closed scraper image release integrity checks."""

import hashlib
import io
import json
import subprocess
import tarfile
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

import pytest
from aws_batch_scraper import release_image
from aws_batch_scraper.release_image import (
    REVISION_LABEL,
    PackageRequirement,
    ReleaseIntegrityError,
    ReleaseTarget,
    parse_package_requirements,
    preflight_release,
    validate_chrome_control_report,
    validate_chrome_grype_report,
    validate_final_filesystem_archive,
    validate_grype_report,
    validate_syft_sbom,
    verify_local_image,
    verify_remote_scan,
)

COMMIT = "a" * 40
ACCOUNT_ID = "123456789012"
SCAN_COMPLETED_AT = "2026-08-19T14:10:00+00:00"
VULNERABILITY_SOURCE_UPDATED_AT = "2026-08-19T13:45:00+00:00"
IMAGE_PUSHED_AT = "2026-08-19T14:00:00+00:00"
IMAGE_ID = "sha256:" + "c" * 64
MANIFEST_DIGEST = "sha256:" + "d" * 64
# BEGIN GENERATED: chrome-lock-test-constants
CHROME_PACKAGE_VERSION = "152.0.7977.75-1"
CHROME_VERSION = "152.0.7977.75"
CHROME_SHA256 = "sha256:3757a071aca19c20b45669f834691d9b698bfee8a8cdf1784f5454e52022d35c"
# END GENERATED: chrome-lock-test-constants
CHROME_SANDBOX_SHA256 = "sha256:18391bf9d217ddbde9956347cbb1346d2808a73ade4baa3f88a610447cf946b4"
NOW = datetime(2026, 8, 19, 14, 30, tzinfo=timezone.utc)


def _manifest_text(*, config_digest: str = IMAGE_ID) -> str:
    return json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
            "config": {
                "mediaType": "application/vnd.docker.container.image.v1+json",
                "size": 123,
                "digest": config_digest,
            },
        },
        separators=(",", ":"),
    )


def _manifest_digest(*, config_digest: str = IMAGE_ID) -> str:
    return (
        f"sha256:{hashlib.sha256(_manifest_text(config_digest=config_digest).encode()).hexdigest()}"
    )


DIGEST = _manifest_digest()


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
    undefined: int = 0,
    digest: str = DIGEST,
    completed_at: str = SCAN_COMPLETED_AT,
    source_updated_at: str = VULNERABILITY_SOURCE_UPDATED_AT,
) -> str:
    findings_key = "enhancedFindings" if status == "ACTIVE" else "findings"
    return json.dumps(
        {
            "registryId": ACCOUNT_ID,
            "repositoryName": "ujs-scraper",
            "imageId": {"imageDigest": digest},
            "imageScanStatus": {"status": status},
            "imageScanFindings": {
                "imageScanCompletedAt": completed_at,
                "vulnerabilitySourceUpdatedAt": source_updated_at,
                "findingSeverityCounts": {
                    "HIGH": high,
                    "CRITICAL": critical,
                    "UNDEFINED": undefined,
                },
                findings_key: [],
            },
        }
    )


def _digest_payload(*, digest: str = DIGEST, pushed_at: str = IMAGE_PUSHED_AT) -> str:
    return json.dumps(
        {
            "imageDetails": [
                {
                    "registryId": ACCOUNT_ID,
                    "repositoryName": "ujs-scraper",
                    "imageDigest": digest,
                    "imageTags": [COMMIT],
                    "imagePushedAt": pushed_at,
                }
            ]
        }
    )


def _manifest_payload(*, config_digest: str = IMAGE_ID) -> str:
    manifest_text = _manifest_text(config_digest=config_digest)
    digest = _manifest_digest(config_digest=config_digest)
    media_type = "application/vnd.docker.distribution.manifest.v2+json"
    return json.dumps(
        {
            "images": [
                {
                    "registryId": ACCOUNT_ID,
                    "repositoryName": "ujs-scraper",
                    "imageId": {"imageDigest": digest},
                    "imageManifestMediaType": media_type,
                    "imageManifest": manifest_text,
                }
            ],
            "failures": [],
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
        (0, _manifest_payload()),
        (0, _scan_payload()),
    )

    assert (
        verify_remote_scan(_target(), runner=runner, expected_image_id=IMAGE_ID, clock=lambda: NOW)
        == DIGEST
    )
    assert "describe-image-scan-findings" in runner.calls[2]
    assert "image-scan-complete" not in runner.calls[2]
    assert f"imageDigest={DIGEST}" in runner.calls[2]
    assert all(
        call[index : index + 2] == ["--registry-id", ACCOUNT_ID]
        for call in runner.calls
        for index in [call.index("--registry-id")]
    )


def test_remote_gate_binds_ecr_manifest_config_to_scanned_local_image_id() -> None:
    runner = StubRunner(
        (0, _digest_payload()),
        (0, _manifest_payload()),
        (0, _scan_payload()),
    )

    assert (
        verify_remote_scan(_target(), runner=runner, expected_image_id=IMAGE_ID, clock=lambda: NOW)
        == DIGEST
    )
    assert "batch-get-image" in runner.calls[1]
    assert "describe-image-scan-findings" in runner.calls[2]

    wrong_config = "sha256:" + "f" * 64
    mismatch = StubRunner(
        (0, _digest_payload(digest=_manifest_digest(config_digest=wrong_config))),
        (0, _manifest_payload(config_digest=wrong_config)),
    )
    with pytest.raises(ReleaseIntegrityError, match="locally scanned image"):
        verify_remote_scan(
            _target(), runner=mismatch, expected_image_id=IMAGE_ID, clock=lambda: NOW
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("repository", "wrong repository"),
        ("response-media-type", "unsupported or inconsistent"),
        ("manifest-media-type", "unsupported or inconsistent"),
        ("schema-version", "unsupported or inconsistent"),
        ("config-size", "locally scanned image"),
        ("manifest-digest", "manifest bytes"),
    ],
)
def test_remote_manifest_contract_rejects_inconsistent_identity(
    mutation: str,
    message: str,
) -> None:
    payload = json.loads(_manifest_payload())
    image = payload["images"][0]
    if mutation == "repository":
        image["repositoryName"] = "other"
    elif mutation == "response-media-type":
        image["imageManifestMediaType"] = "application/json"
    elif mutation == "manifest-digest":
        image["imageId"]["imageDigest"] = "sha256:" + "f" * 64
    else:
        manifest = json.loads(image["imageManifest"])
        if mutation == "manifest-media-type":
            manifest["mediaType"] = "application/json"
        elif mutation == "schema-version":
            manifest["schemaVersion"] = 1
        else:
            manifest["config"]["size"] = 0
        image["imageManifest"] = json.dumps(manifest, separators=(",", ":"))
        image["imageId"]["imageDigest"] = (
            f"sha256:{hashlib.sha256(image['imageManifest'].encode()).hexdigest()}"
        )
    digest = image["imageId"]["imageDigest"]
    runner = StubRunner((0, _digest_payload(digest=digest)), (0, json.dumps(payload)))

    with pytest.raises(ReleaseIntegrityError, match=message):
        verify_remote_scan(_target(), runner=runner, expected_image_id=IMAGE_ID, clock=lambda: NOW)


@pytest.mark.parametrize(("high", "critical"), [(1, 0), (0, 1), (4, 2)])
def test_scan_gate_rejects_any_high_or_critical_finding(high: int, critical: int) -> None:
    runner = StubRunner(
        (0, _digest_payload()),
        (0, _manifest_payload()),
        (0, _scan_payload(high=high, critical=critical)),
    )

    with pytest.raises(ReleaseIntegrityError, match="blocked release"):
        verify_remote_scan(_target(), runner=runner, expected_image_id=IMAGE_ID, clock=lambda: NOW)


def test_scan_gate_polls_pending_scan_until_complete() -> None:
    delays: list[float] = []
    runner = StubRunner(
        (0, _digest_payload()),
        (0, _manifest_payload()),
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
        expected_image_id=IMAGE_ID,
        clock=lambda: NOW,
    )

    assert digest == DIGEST
    assert delays == [0.25, 0.25]
    assert sum("describe-image-scan-findings" in call for call in runner.calls) == 3


def test_scan_gate_retries_initial_scan_not_found() -> None:
    delays: list[float] = []
    runner = StubRunner(
        (0, _digest_payload()),
        (0, _manifest_payload()),
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
            expected_image_id=IMAGE_ID,
            clock=lambda: NOW,
        )
        == DIGEST
    )
    assert delays == [1]


def test_scan_gate_does_not_accept_scan_not_found_as_an_unstructured_substring() -> None:
    delays: list[float] = []
    runner = StubRunner(
        (0, _digest_payload()),
        (0, _manifest_payload()),
        (255, "", "wrapper failed; text happened to mention ScanNotFoundException"),
    )

    with pytest.raises(ReleaseIntegrityError, match="findings command failed"):
        verify_remote_scan(
            _target(),
            runner=runner,
            sleeper=delays.append,
            max_attempts=2,
            expected_image_id=IMAGE_ID,
            clock=lambda: NOW,
        )
    assert delays == []


def test_scan_gate_does_not_retry_authorization_failure() -> None:
    delays: list[float] = []
    runner = StubRunner(
        (0, _digest_payload()),
        (0, _manifest_payload()),
        (255, "", "An error occurred (AccessDeniedException) when calling the operation"),
    )

    with pytest.raises(ReleaseIntegrityError, match="findings command failed"):
        verify_remote_scan(
            _target(),
            runner=runner,
            sleeper=delays.append,
            max_attempts=2,
            expected_image_id=IMAGE_ID,
            clock=lambda: NOW,
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
        (0, _manifest_payload()),
        (0, _scan_payload(status=status)),
    )

    with pytest.raises(ReleaseIntegrityError, match=f"terminal status {status}"):
        verify_remote_scan(
            _target(),
            runner=runner,
            sleeper=lambda _: None,
            expected_image_id=IMAGE_ID,
            clock=lambda: NOW,
        )


def test_scan_gate_has_bounded_pending_timeout() -> None:
    delays: list[float] = []
    runner = StubRunner(
        (0, _digest_payload()),
        (0, _manifest_payload()),
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
            expected_image_id=IMAGE_ID,
            clock=lambda: NOW,
        )
    assert delays == [0.5]


@pytest.mark.parametrize("max_attempts", [True, 0, -1])
def test_scan_gate_rejects_invalid_attempt_limit(max_attempts: int) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        verify_remote_scan(
            _target(),
            runner=StubRunner(),
            max_attempts=max_attempts,
            expected_image_id=IMAGE_ID,
        )


@pytest.mark.parametrize("poll_interval", [True, -1, float("nan"), float("inf")])
def test_scan_gate_rejects_invalid_poll_interval(poll_interval: float) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        verify_remote_scan(
            _target(),
            runner=StubRunner(),
            poll_interval_seconds=poll_interval,
            expected_image_id=IMAGE_ID,
        )


def test_scan_gate_rejects_nonterminal_active_enhanced_scan() -> None:
    runner = StubRunner(
        (0, _digest_payload()),
        (0, _manifest_payload()),
        (0, _scan_payload(status="ACTIVE")),
    )

    with pytest.raises(ReleaseIntegrityError, match="terminal status ACTIVE"):
        verify_remote_scan(_target(), runner=runner, expected_image_id=IMAGE_ID, clock=lambda: NOW)


@pytest.mark.parametrize(
    ("pushed_at", "completed_at", "message"),
    [
        ("2026-08-19T13:29:59Z", SCAN_COMPLETED_AT, "image push.*stale"),
        ("2026-08-19T14:20:00Z", "2026-08-19T14:10:00Z", "predated the image push"),
    ],
)
def test_scan_gate_requires_fresh_push_bound_scan(
    pushed_at: str,
    completed_at: str,
    message: str,
) -> None:
    runner = StubRunner(
        (0, _digest_payload(pushed_at=pushed_at)),
        (0, _manifest_payload()),
        (0, _scan_payload(completed_at=completed_at)),
    )

    with pytest.raises(ReleaseIntegrityError, match=message):
        verify_remote_scan(_target(), runner=runner, expected_image_id=IMAGE_ID, clock=lambda: NOW)


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
    runner = StubRunner(
        (0, _digest_payload()),
        (0, _manifest_payload()),
        (0, json.dumps(payload)),
    )

    with pytest.raises(ReleaseIntegrityError, match=message):
        verify_remote_scan(_target(), runner=runner, expected_image_id=IMAGE_ID, clock=lambda: NOW)


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
    runner = StubRunner(
        (0, _digest_payload()),
        (0, _manifest_payload()),
        (0, json.dumps(payload)),
    )

    with pytest.raises(ReleaseIntegrityError, match="timestamp"):
        verify_remote_scan(_target(), runner=runner, expected_image_id=IMAGE_ID, clock=lambda: NOW)


def test_scan_gate_allows_omitted_individual_high_and_critical_keys() -> None:
    payload = json.loads(_scan_payload())
    payload["imageScanFindings"]["findingSeverityCounts"] = {"MEDIUM": 3, "LOW": 2}
    runner = StubRunner(
        (0, _digest_payload()),
        (0, _manifest_payload()),
        (0, json.dumps(payload)),
    )

    assert (
        verify_remote_scan(_target(), runner=runner, expected_image_id=IMAGE_ID, clock=lambda: NOW)
        == DIGEST
    )


def test_scan_gate_rejects_positive_undefined_count() -> None:
    runner = StubRunner(
        (0, _digest_payload()),
        (0, _manifest_payload()),
        (0, _scan_payload(undefined=1)),
    )

    with pytest.raises(ReleaseIntegrityError, match="1 Undefined"):
        verify_remote_scan(_target(), runner=runner, expected_image_id=IMAGE_ID, clock=lambda: NOW)


@pytest.mark.parametrize(
    ("completed_at", "source_updated_at", "message"),
    [
        ("2026-08-19T13:29:59Z", VULNERABILITY_SOURCE_UPDATED_AT, "completion.*stale"),
        (SCAN_COMPLETED_AT, "2026-08-18T14:29:59Z", "source update.*stale"),
        ("2026-08-19T14:35:01Z", VULNERABILITY_SOURCE_UPDATED_AT, "completion.*future"),
        (SCAN_COMPLETED_AT, "2026-08-19T14:35:01Z", "source update.*future"),
    ],
)
def test_scan_gate_rejects_stale_or_future_evidence(
    completed_at: str,
    source_updated_at: str,
    message: str,
) -> None:
    runner = StubRunner(
        (0, _digest_payload()),
        (0, _manifest_payload()),
        (
            0,
            _scan_payload(
                completed_at=completed_at,
                source_updated_at=source_updated_at,
            ),
        ),
    )

    with pytest.raises(ReleaseIntegrityError, match=message):
        verify_remote_scan(_target(), runner=runner, expected_image_id=IMAGE_ID, clock=lambda: NOW)


@pytest.mark.parametrize("count", [0, 1])
def test_scan_gate_rejects_unknown_severity_even_when_zero(count: int) -> None:
    payload = json.loads(_scan_payload())
    payload["imageScanFindings"]["findingSeverityCounts"]["FUTURE"] = count
    runner = StubRunner(
        (0, _digest_payload()),
        (0, _manifest_payload()),
        (0, json.dumps(payload)),
    )

    with pytest.raises(ReleaseIntegrityError, match="unknown severity"):
        verify_remote_scan(_target(), runner=runner, expected_image_id=IMAGE_ID, clock=lambda: NOW)


def test_scan_gate_uses_aggregate_counts_when_detailed_findings_have_next_token() -> None:
    payload = json.loads(_scan_payload(high=1))
    payload["nextToken"] = "more-detailed-findings"
    runner = StubRunner(
        (0, _digest_payload()),
        (0, _manifest_payload()),
        (0, json.dumps(payload)),
    )

    with pytest.raises(ReleaseIntegrityError, match="blocked release"):
        verify_remote_scan(_target(), runner=runner, expected_image_id=IMAGE_ID, clock=lambda: NOW)


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
        "--expected-image-id",
        IMAGE_ID,
        "--local-scan-receipt",
        "/tmp/local-scan-receipt.json",
        "--release-receipt",
        "/tmp/release-receipt.json",
    ]


def test_release_parser_builds_and_remote_identity_is_required() -> None:
    parser = release_image._parser()
    arguments = _verify_scan_args()
    expected_index = arguments.index("--expected-image-id")
    del arguments[expected_index : expected_index + 2]
    with pytest.raises(SystemExit):
        parser.parse_args(arguments)
    with pytest.raises(TypeError, match="expected_image_id"):
        verify_remote_scan(_target())


def test_verify_scan_cli_prints_only_full_verified_uri(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        release_image,
        "verify_remote_scan",
        lambda _, expected_image_id=None: DIGEST,
    )
    monkeypatch.setattr(release_image, "write_verified_release_receipt", lambda *_, **__: None)

    assert release_image.main(_verify_scan_args()) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == (f"{ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/ujs-scraper@{DIGEST}\n")


def test_verify_scan_cli_failure_is_nonzero_and_prints_no_uri(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_scan(
        _target: ReleaseTarget,
        *,
        expected_image_id: str | None = None,
    ) -> str:
        raise ReleaseIntegrityError("scan still pending")

    monkeypatch.setattr(release_image, "verify_remote_scan", fail_scan)

    assert release_image.main(_verify_scan_args()) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "scan still pending" in captured.err


def _local_release_evidence(directory: Path) -> Path:
    artifacts: dict[str, str] = {}
    for name in (
        "filesystem-audit.json",
        "sbom.syft.json",
        "sbom.cdx.json",
        "grype.json",
        "grype.chrome.json",
        "grype.chrome-control.json",
    ):
        content = f"evidence:{name}\n"
        (directory / name).write_text(content)
        artifacts[name] = f"sha256:{hashlib.sha256(content.encode()).hexdigest()}"
    receipt = directory / "receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "image": {
                    "id": IMAGE_ID,
                    "manifest_digest": MANIFEST_DIGEST,
                    "platform": release_image.LOCAL_SCAN_PLATFORM,
                },
                "tools": {
                    "grype": {
                        "image": release_image.GRYPE_IMAGE,
                        "version": release_image.GRYPE_VERSION,
                    },
                    "syft": {
                        "image": release_image.SYFT_IMAGE,
                        "version": release_image.SYFT_VERSION,
                        "schema": release_image.SYFT_SCHEMA_VERSION,
                    },
                },
                "filesystem": {
                    "schema_version": 1,
                    "image_id": IMAGE_ID,
                    "archive_sha256": "sha256:" + "d" * 64,
                    "members": 100,
                    "regular_files": 80,
                    "chrome_sandbox_present": False,
                    "setuid_setgid_files": 0,
                    "chrome_sandbox_policy": "forbidden",
                    "setuid_setgid_policy": "forbidden",
                },
                "chrome": {
                    "sandbox_policy": "forbidden",
                    "sandbox_present": False,
                    "sandbox_sha256": None,
                },
                "scans": {
                    "image": {"severity_counts": {"Critical": 0, "High": 0, "Unknown": 0}},
                    "chrome": {"severity_counts": {"Critical": 0, "High": 0, "Unknown": 0}},
                    "chrome_coverage_control": {
                        "severity_counts": {"Critical": 1, "High": 1, "Unknown": 0}
                    },
                },
                "artifacts": artifacts,
            }
        )
    )
    return receipt


def test_verified_release_receipt_binds_remote_digest_to_rehashed_local_evidence(
    tmp_path: Path,
) -> None:
    local_receipt = _local_release_evidence(tmp_path)
    release_receipt = tmp_path / "release.json"

    release_image.write_verified_release_receipt(
        local_receipt,
        release_receipt,
        target=_target(),
        digest=DIGEST,
        expected_image_id=IMAGE_ID,
        clock=lambda: NOW,
    )

    payload = json.loads(release_receipt.read_text())
    assert payload["status"] == "verified"
    assert payload["image"]["id"] == IMAGE_ID
    assert payload["image"]["ecr_digest"] == DIGEST
    assert payload["image"]["ecr_uri"].endswith(f"@{DIGEST}")
    assert release_image.IMAGE_DIGEST_PATTERN.fullmatch(payload["local_scan_receipt_sha256"])


def test_verified_release_receipt_supports_reviewed_setuid_sandbox_policy(
    tmp_path: Path,
) -> None:
    local_receipt = _local_release_evidence(tmp_path)
    payload = json.loads(local_receipt.read_text())
    payload["chrome"] = {
        "sandbox_policy": "setuid",
        "sandbox_present": True,
        "sandbox_sha256": "sha256:" + "e" * 64,
    }
    payload["filesystem"].update(
        {
            "chrome_sandbox_policy": "permitted",
            "setuid_setgid_policy": "permitted",
            "chrome_sandbox_present": True,
            "setuid_setgid_files": 1,
        }
    )
    local_receipt.write_text(json.dumps(payload))
    release_receipt = tmp_path / "release.json"

    release_image.write_verified_release_receipt(
        local_receipt,
        release_receipt,
        target=_target(),
        digest=DIGEST,
        expected_image_id=IMAGE_ID,
        clock=lambda: NOW,
    )

    assert json.loads(release_receipt.read_text())["status"] == "verified"


def test_verified_release_receipt_binds_independent_permitted_setid_policy(
    tmp_path: Path,
) -> None:
    local_receipt = _local_release_evidence(tmp_path)
    payload = json.loads(local_receipt.read_text())
    payload["filesystem"]["setuid_setgid_policy"] = "permitted"
    payload["filesystem"]["setuid_setgid_files"] = 2
    local_receipt.write_text(json.dumps(payload))
    release_receipt = tmp_path / "release.json"

    release_image.write_verified_release_receipt(
        local_receipt,
        release_receipt,
        target=_target(),
        digest=DIGEST,
        expected_image_id=IMAGE_ID,
        clock=lambda: NOW,
    )

    assert json.loads(release_receipt.read_text())["status"] == "verified"


@pytest.mark.parametrize(
    "mutation",
    ["image-id", "artifact", "high", "control", "bool-members", "bool-setid"],
)
def test_verified_release_receipt_rejects_tampered_or_incomplete_evidence(
    tmp_path: Path,
    mutation: str,
) -> None:
    local_receipt = _local_release_evidence(tmp_path)
    payload = json.loads(local_receipt.read_text())
    if mutation == "image-id":
        payload["image"]["id"] = "sha256:" + "f" * 64
        local_receipt.write_text(json.dumps(payload))
    elif mutation == "artifact":
        (tmp_path / "grype.json").write_text("tampered\n")
    elif mutation == "high":
        payload["scans"]["image"]["severity_counts"]["High"] = 1
        local_receipt.write_text(json.dumps(payload))
    elif mutation == "control":
        payload["scans"]["chrome_coverage_control"]["severity_counts"]["High"] = 0
        local_receipt.write_text(json.dumps(payload))
    elif mutation == "bool-members":
        payload["filesystem"]["members"] = True
        local_receipt.write_text(json.dumps(payload))
    else:
        payload["filesystem"]["setuid_setgid_files"] = False
        local_receipt.write_text(json.dumps(payload))
    release_receipt = tmp_path / "release.json"

    with pytest.raises(ReleaseIntegrityError):
        release_image.write_verified_release_receipt(
            local_receipt,
            release_receipt,
            target=_target(),
            digest=DIGEST,
            expected_image_id=IMAGE_ID,
            clock=lambda: NOW,
        )
    assert not release_receipt.exists()


def test_push_recipe_cannot_mask_scan_cli_failure_with_a_later_echo() -> None:
    recipe = (Path(__file__).resolve().parents[1] / "just" / "aws-batch-scraper.just").read_text()
    verify_lines = [line.strip() for line in recipe.splitlines() if "verify-scan" in line]

    assert len(verify_lines) == 1
    assert verify_lines[0].startswith("cd packages/aws-batch-scraper; uv run ")
    assert "set -euo pipefail" in recipe
    assert "--expected-image-id" in verify_lines[0]
    assert "--local-scan-receipt" in verify_lines[0]
    assert "--release-receipt" in verify_lines[0]
    assert "digest=$(" not in recipe
    assert "@$digest" not in recipe


def _required_packages() -> tuple[PackageRequirement, ...]:
    return parse_package_requirements(
        "python:playwright=1.62.0,"
        f"deb:google-chrome-stable={CHROME_PACKAGE_VERSION},"
        "binary:node=24.18.1"
    )


def _syft_payload() -> dict[str, object]:
    return {
        "descriptor": {"name": "syft", "version": release_image.SYFT_VERSION},
        "schema": {"version": release_image.SYFT_SCHEMA_VERSION},
        "source": {
            "type": "image",
            "metadata": {
                "imageID": IMAGE_ID,
                "manifestDigest": MANIFEST_DIGEST,
                "tags": ["scraper:test"],
            },
        },
        "artifacts": [
            {
                "name": "playwright",
                "version": "1.62.0",
                "type": "python",
                "purl": "pkg:pypi/playwright@1.62.0",
                "locations": [{"path": "/app/.venv/playwright/METADATA"}],
            },
            {
                "name": "google-chrome-stable",
                "version": CHROME_PACKAGE_VERSION,
                "type": "deb",
                "purl": (
                    "pkg:deb/ubuntu/google-chrome-stable@"
                    f"{CHROME_PACKAGE_VERSION}?arch=amd64&distro=ubuntu-26.04"
                ),
                "locations": [{"path": "/var/lib/dpkg/status"}],
                "metadata": {
                    "files": [
                        {"path": "/opt/google/chrome/chrome"},
                        {"path": "/opt/google/chrome/chrome-sandbox"},
                    ]
                },
            },
            {
                "name": "node",
                "version": "24.18.1",
                "type": "binary",
                "purl": "pkg:generic/node@24.18.1",
                "cpes": [{"cpe": "cpe:2.3:a:nodejs:node.js:24.18.1:*:*:*:*:*:*:*"}],
                "locations": [
                    {"path": ("/app/.venv/lib/python3.14/site-packages/playwright/driver/node")}
                ],
            },
        ],
        "files": [
            {
                "location": {"path": "/opt/google/chrome/chrome"},
                "metadata": {
                    "type": "RegularFile",
                    "mode": 755,
                    "userID": 0,
                    "groupID": 0,
                },
                "executable": {"format": "elf"},
                "digests": [
                    {"algorithm": "sha256", "value": CHROME_SHA256.removeprefix("sha256:")}
                ],
            },
            {
                "location": {"path": "/opt/google/chrome/chrome-sandbox"},
                "metadata": {
                    "type": "RegularFile",
                    "mode": 40000755,
                    "userID": 0,
                    "groupID": 0,
                },
                "executable": {"format": "elf"},
                "digests": [
                    {
                        "algorithm": "sha256",
                        "value": CHROME_SANDBOX_SHA256.removeprefix("sha256:"),
                    }
                ],
            },
        ],
    }


def _grype_configuration() -> dict[str, object]:
    return {
        "only-fixed": False,
        "only-notfixed": False,
        "ignore-wontfix": "",
        "fail-on-severity": "high",
        "vex-documents": [],
        "vex-add": [],
        "ignore": [],
        "exclude": [],
        "match-upstream-kernel-headers": True,
        "externalSources": {"enable": False},
        "match": {"stock": {"using-cpes": True}},
        "db": {
            "auto-update": False,
            "validate-by-hash-on-start": True,
            "validate-age": True,
        },
    }


def _grype_payload(*, source: dict[str, object], distro: str) -> dict[str, object]:
    providers = {name: {"captured": "2026-08-19T13:00:00Z"} for name in ("ubuntu", "github", "nvd")}
    return {
        "descriptor": {
            "name": "grype",
            "version": release_image.GRYPE_VERSION,
            "configuration": _grype_configuration(),
            "timestamp": "2026-08-19T14:00:00Z",
            "db": {
                "status": {
                    "schemaVersion": "v6.1.9",
                    "from": (
                        "https://grype.anchore.io/databases/v6/db.tar.zst?"
                        f"checksum={'sha256:' + 'e' * 64}"
                    ),
                    "built": "2026-08-19T13:00:00Z",
                    "valid": True,
                },
                "providers": providers,
            },
        },
        "source": source,
        "distro": {"name": distro, "version": "26.04", "idLike": []},
        "matches": [],
    }


def _clone(payload: dict[str, object]) -> dict[str, object]:
    return json.loads(json.dumps(payload))


def test_package_contract_requires_actual_system_chrome_and_playwright_node() -> None:
    assert {requirement.canonical for requirement in _required_packages()} == {
        "python:playwright=1.62.0",
        f"deb:google-chrome-stable={CHROME_PACKAGE_VERSION}",
        "binary:node=24.18.1",
    }

    with pytest.raises(ValueError, match="google-chrome-stable"):
        parse_package_requirements(
            f"python:playwright=1.62.0,binary:chrome={CHROME_VERSION},binary:node=24.18.1"
        )


def test_syft_contract_binds_exact_chrome_payload_and_playwright_node() -> None:
    result = validate_syft_sbom(
        _syft_payload(),
        image="scraper:test",
        image_id=IMAGE_ID,
        requirements=_required_packages(),
        expected_chrome_executable_sha256=CHROME_SHA256,
        expected_chrome_sandbox_sha256=CHROME_SANDBOX_SHA256,
    )

    assert result["chrome"]["cpe"] == (f"cpe:2.3:a:google:chrome:{CHROME_VERSION}:*:*:*:*:*:*:*")
    assert result["chrome"]["executable_sha256"] == CHROME_SHA256
    assert result["chrome"]["sandbox_sha256"] == CHROME_SANDBOX_SHA256
    assert result["chrome"]["sandbox_present"] is True
    assert result["chrome"]["sandbox_policy"] == "setuid"


def test_syft_contract_proves_forbidden_chrome_sandbox_helper_is_absent() -> None:
    payload = _syft_payload()
    del payload["files"][1]

    result = validate_syft_sbom(
        payload,
        image="scraper:test",
        image_id=IMAGE_ID,
        requirements=_required_packages(),
        expected_chrome_executable_sha256=CHROME_SHA256,
        forbid_chrome_sandbox=True,
        forbid_setuid_setgid_files=True,
    )

    assert result["chrome"]["sandbox"] == "/opt/google/chrome/chrome-sandbox"
    assert result["chrome"]["sandbox_present"] is False
    assert result["chrome"]["sandbox_sha256"] is None
    assert result["chrome"]["sandbox_policy"] == "forbidden"
    assert result["setuid_setgid_files_forbidden"] is True


@pytest.mark.parametrize("mode", [20000755, 40000755, 60000755])
def test_syft_contract_rejects_any_setuid_or_setgid_file(mode: int) -> None:
    payload = _syft_payload()
    del payload["files"][1]
    payload["files"][0]["location"]["path"] = "/usr/bin/unneeded-helper"
    payload["files"][0]["metadata"]["mode"] = mode

    with pytest.raises(ReleaseIntegrityError, match="setuid/setgid files"):
        validate_syft_sbom(
            payload,
            image="scraper:test",
            image_id=IMAGE_ID,
            requirements=_required_packages(),
            expected_chrome_executable_sha256=CHROME_SHA256,
            forbid_chrome_sandbox=True,
            forbid_setuid_setgid_files=True,
        )


def test_syft_contract_rejects_retained_forbidden_chrome_sandbox_helper() -> None:
    with pytest.raises(ReleaseIntegrityError, match="retained the forbidden"):
        validate_syft_sbom(
            _syft_payload(),
            image="scraper:test",
            image_id=IMAGE_ID,
            requirements=_required_packages(),
            expected_chrome_executable_sha256=CHROME_SHA256,
            forbid_chrome_sandbox=True,
        )


def test_syft_contract_rejects_conflicting_chrome_sandbox_policies() -> None:
    with pytest.raises(ReleaseIntegrityError, match="mutually exclusive"):
        validate_syft_sbom(
            _syft_payload(),
            image="scraper:test",
            image_id=IMAGE_ID,
            requirements=_required_packages(),
            expected_chrome_executable_sha256=CHROME_SHA256,
            expected_chrome_sandbox_sha256=CHROME_SANDBOX_SHA256,
            forbid_chrome_sandbox=True,
        )


def _write_filesystem_tar(path: Path, entries: dict[str, int]) -> None:
    with tarfile.open(path, mode="w") as archive:
        for name, mode in entries.items():
            info = tarfile.TarInfo(name)
            info.mode = mode
            info.size = 1
            archive.addfile(info, io.BytesIO(b"x"))


def test_final_filesystem_archive_proves_privilege_helpers_absent(tmp_path: Path) -> None:
    archive = tmp_path / "filesystem.tar"
    _write_filesystem_tar(
        archive,
        {
            "opt/google/chrome/chrome": 0o755,
            "usr/bin/python3": 0o755,
        },
    )

    result = validate_final_filesystem_archive(
        archive,
        image_id=IMAGE_ID,
        forbid_chrome_sandbox=True,
        forbid_setuid_setgid_files=True,
    )

    assert result["chrome_sandbox_present"] is False
    assert result["setuid_setgid_files"] == 0
    assert result["chrome_sandbox_policy"] == "forbidden"
    assert result["setuid_setgid_policy"] == "forbidden"
    assert result["regular_files"] == 2


def test_final_filesystem_archive_records_permitted_privilege_policy(tmp_path: Path) -> None:
    archive = tmp_path / "filesystem.tar"
    _write_filesystem_tar(
        archive,
        {
            "opt/google/chrome/chrome": 0o755,
            "opt/google/chrome/chrome-sandbox": 0o4755,
        },
    )

    result = validate_final_filesystem_archive(
        archive,
        image_id=IMAGE_ID,
        forbid_chrome_sandbox=False,
        forbid_setuid_setgid_files=False,
    )

    assert result["chrome_sandbox_present"] is True
    assert result["setuid_setgid_files"] == 1
    assert result["chrome_sandbox_policy"] == "permitted"
    assert result["setuid_setgid_policy"] == "permitted"


@pytest.mark.parametrize(
    ("path", "mode", "message"),
    [
        ("opt/google/chrome/chrome-sandbox", 0o755, "Chrome sandbox helper"),
        ("usr/bin/unneeded-helper", 0o4755, "setuid/setgid files"),
        ("usr/bin/unneeded-helper", 0o2755, "setuid/setgid files"),
    ],
)
def test_final_filesystem_archive_rejects_privilege_surface(
    tmp_path: Path,
    path: str,
    mode: int,
    message: str,
) -> None:
    archive = tmp_path / "filesystem.tar"
    _write_filesystem_tar(archive, {"usr/bin/python3": 0o755, path: mode})

    with pytest.raises(ReleaseIntegrityError, match=message):
        validate_final_filesystem_archive(
            archive,
            image_id=IMAGE_ID,
            forbid_chrome_sandbox=True,
            forbid_setuid_setgid_files=True,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "chrome-hash",
        "sandbox-hash",
        "sandbox-mode",
        "sandbox-uid",
        "sandbox-gid",
        "node-path",
        "image-id",
    ],
)
def test_syft_contract_rejects_identity_or_executable_substitution(mutation: str) -> None:
    payload = _syft_payload()
    if mutation == "chrome-hash":
        payload["files"][0]["digests"][0]["value"] = "f" * 64
    elif mutation == "sandbox-hash":
        payload["files"][1]["digests"][0]["value"] = "f" * 64
    elif mutation == "sandbox-mode":
        payload["files"][1]["metadata"]["mode"] = 755
    elif mutation == "sandbox-uid":
        payload["files"][1]["metadata"]["userID"] = 1000
    elif mutation == "sandbox-gid":
        payload["files"][1]["metadata"]["groupID"] = 1000
    elif mutation == "node-path":
        payload["artifacts"][2]["locations"][0]["path"] = "/usr/bin/node"
    else:
        payload["source"]["metadata"]["imageID"] = "sha256:" + "f" * 64

    with pytest.raises(ReleaseIntegrityError):
        validate_syft_sbom(
            payload,
            image="scraper:test",
            image_id=IMAGE_ID,
            requirements=_required_packages(),
            expected_chrome_executable_sha256=CHROME_SHA256,
            expected_chrome_sandbox_sha256=CHROME_SANDBOX_SHA256,
        )


def test_image_grype_report_accepts_real_omitted_empty_ignored_matches() -> None:
    payload = _grype_payload(
        source={
            "type": "image",
            "target": {"imageID": IMAGE_ID, "manifestDigest": MANIFEST_DIGEST},
        },
        distro="ubuntu",
    )

    result = validate_grype_report(
        payload,
        image_id=IMAGE_ID,
        manifest_digest=MANIFEST_DIGEST,
        expected_distro_name="ubuntu",
        expected_distro_version="26.04",
        now=NOW,
        scanner_returncode=0,
    )

    assert result["severity_counts"]["High"] == 0


def test_grype_provider_capture_accepts_exact_age_boundary_at_database_build() -> None:
    payload = _grype_payload(
        source={
            "type": "image",
            "target": {"imageID": IMAGE_ID, "manifestDigest": MANIFEST_DIGEST},
        },
        distro="ubuntu",
    )
    payload["descriptor"]["db"]["providers"]["ubuntu"]["captured"] = "2026-08-18T13:00:00Z"

    validate_grype_report(
        payload,
        image_id=IMAGE_ID,
        manifest_digest=MANIFEST_DIGEST,
        expected_distro_name="ubuntu",
        expected_distro_version="26.04",
        now=NOW,
        scanner_returncode=0,
    )


@pytest.mark.parametrize(
    ("captured", "message"),
    [
        ("2026-08-18T12:59:59Z", "stale when the database was built"),
        ("2026-08-19T13:00:01Z", "postdated the database build"),
        ("not-a-timestamp", "timestamp was invalid"),
    ],
)
def test_grype_provider_capture_rejects_invalid_database_build_relationship(
    captured: str,
    message: str,
) -> None:
    payload = _grype_payload(
        source={
            "type": "image",
            "target": {"imageID": IMAGE_ID, "manifestDigest": MANIFEST_DIGEST},
        },
        distro="ubuntu",
    )
    payload["descriptor"]["db"]["providers"]["ubuntu"]["captured"] = captured

    with pytest.raises(ReleaseIntegrityError, match=message):
        validate_grype_report(
            payload,
            image_id=IMAGE_ID,
            manifest_digest=MANIFEST_DIGEST,
            expected_distro_name="ubuntu",
            expected_distro_version="26.04",
            now=NOW,
            scanner_returncode=0,
        )


def test_grype_provider_capture_rejects_malformed_provider_metadata() -> None:
    payload = _grype_payload(
        source={
            "type": "image",
            "target": {"imageID": IMAGE_ID, "manifestDigest": MANIFEST_DIGEST},
        },
        distro="ubuntu",
    )
    payload["descriptor"]["db"]["providers"]["ubuntu"] = "malformed"

    with pytest.raises(ReleaseIntegrityError, match="required ubuntu provider metadata"):
        validate_grype_report(
            payload,
            image_id=IMAGE_ID,
            manifest_digest=MANIFEST_DIGEST,
            expected_distro_name="ubuntu",
            expected_distro_version="26.04",
            now=NOW,
            scanner_returncode=0,
        )


@pytest.mark.parametrize(("name", "version"), [("debian", "26.04"), ("ubuntu", "25.10")])
def test_image_grype_report_rejects_wrong_distribution_release(
    name: str,
    version: str,
) -> None:
    payload = _grype_payload(
        source={
            "type": "image",
            "target": {"imageID": IMAGE_ID, "manifestDigest": MANIFEST_DIGEST},
        },
        distro=name,
    )
    payload["distro"]["version"] = version

    with pytest.raises(ReleaseIntegrityError, match="expected image distribution"):
        validate_grype_report(
            payload,
            image_id=IMAGE_ID,
            manifest_digest=MANIFEST_DIGEST,
            expected_distro_name="ubuntu",
            expected_distro_version="26.04",
            now=NOW,
            scanner_returncode=0,
        )


def test_image_grype_report_blocks_unfixed_high_and_any_ignore_rule() -> None:
    payload = _grype_payload(
        source={
            "type": "image",
            "target": {"imageID": IMAGE_ID, "manifestDigest": MANIFEST_DIGEST},
        },
        distro="ubuntu",
    )
    payload["matches"] = [
        {
            "vulnerability": {
                "id": "CVE-2099-1",
                "severity": "High",
                "fix": {"state": "not-fixed", "versions": []},
            }
        }
    ]
    with pytest.raises(ReleaseIntegrityError, match="blocked release"):
        validate_grype_report(
            payload,
            image_id=IMAGE_ID,
            manifest_digest=MANIFEST_DIGEST,
            expected_distro_name="ubuntu",
            expected_distro_version="26.04",
            now=NOW,
            scanner_returncode=2,
        )

    ignored = _clone(payload)
    ignored["descriptor"]["configuration"]["ignore"] = [{"vulnerability": "CVE-1"}]
    with pytest.raises(ReleaseIntegrityError, match="ignore rules"):
        validate_grype_report(
            ignored,
            image_id=IMAGE_ID,
            manifest_digest=MANIFEST_DIGEST,
            expected_distro_name="ubuntu",
            expected_distro_version="26.04",
            now=NOW,
            scanner_returncode=2,
        )


def test_chrome_cpe_report_requires_exact_source_and_live_coverage_control() -> None:
    current_cpe = f"cpe:2.3:a:google:chrome:{CHROME_VERSION}:*:*:*:*:*:*:*"
    current = _grype_payload(source={"type": "cpe", "target": current_cpe}, distro="")
    result = validate_chrome_grype_report(
        current,
        cpe=current_cpe,
        now=NOW,
        scanner_returncode=0,
    )
    assert result["provider"] == "nvd"

    wrong_source = _clone(current)
    wrong_source["source"]["target"] = "cpe:2.3:a:google:chrome:1:*:*:*:*:*:*:*"
    with pytest.raises(ReleaseIntegrityError, match="exact validated CPE"):
        validate_chrome_grype_report(
            wrong_source,
            cpe=current_cpe,
            now=NOW,
            scanner_returncode=0,
        )

    control = _grype_payload(
        source={"type": "cpe", "target": release_image._CHROME_CPE_CONTROL},
        distro="",
    )
    with pytest.raises(ReleaseIntegrityError, match="did not trigger"):
        validate_chrome_control_report(control, now=NOW, scanner_returncode=0)
    control["matches"] = [
        {"vulnerability": {"id": "CVE-C", "severity": "Critical"}},
        {"vulnerability": {"id": "CVE-H", "severity": "High"}},
    ]
    validated = validate_chrome_control_report(control, now=NOW, scanner_returncode=2)
    assert validated["severity_counts"]["Critical"] == 1


def test_push_recipe_scans_and_pushes_exact_id_then_binds_remote_config() -> None:
    recipe = (Path(__file__).resolve().parents[1] / "just" / "aws-batch-scraper.just").read_text()

    assert "set -euo pipefail" in recipe
    assert "--print-identity" in recipe
    assert "*$'\\n'*" in recipe
    assert 'docker tag "${scanned_image_id}"' in recipe
    assert '--expected-image-id "${scanned_image_id}"' in recipe
    assert "--required-chrome-executable-sha256" in recipe
    assert "{{aws_batch_scraper_chrome_sandbox_scan_args}}" in recipe
    assert "--required-chrome-sandbox-sha256" not in recipe
    assert '--output-directory "${scan_output_directory}"' in recipe
    assert '"${scan_output_directory}/release.json"' in recipe
    assert "scraper-scan-container" in recipe
    immutable_label_check = (
        'verify-local-image --image "${scanned_image_id}" --tag "${SCRAPER_IMAGE_TAG}"'
    )
    assert immutable_label_check in recipe
    assert recipe.index(immutable_label_check) < recipe.index('docker tag "${scanned_image_id}"')


def test_release_build_streams_only_the_immutable_git_tree() -> None:
    recipe = (Path(__file__).resolve().parents[1] / "just" / "aws-batch-scraper.just").read_text()
    build_line = next(
        line for line in recipe.splitlines() if "git archive --format=tar HEAD" in line
    )

    assert "set -euo pipefail" in build_line
    assert "git archive --format=tar HEAD | docker buildx build" in build_line
    assert '-f "{{aws_batch_scraper_dockerfile}}" -' in build_line
    assert "aws_batch_scraper_docker_context" not in recipe
