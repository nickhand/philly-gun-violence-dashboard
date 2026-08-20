"""Tests for durable full-run duplicate suppression."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from aws_batch_scraper.config import WorkerConfig
from aws_batch_scraper.run_guard import find_full_run_suppression
from botocore.exceptions import ClientError

NOW = datetime(2026, 8, 20, 20, tzinfo=UTC)


def _config() -> WorkerConfig:
    return WorkerConfig(
        _env_file=None,
        s3_bucket="bucket",
        s3_scraper_prefix="scraper",
        aws_account_id="123456789012",
        sqs_queue_name="queue",
        sqs_dlq_name="queue-dlq",
    )


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, "GetObject")


class _Body:
    def __init__(self, value: bytes) -> None:
        self.value = value

    def read(self) -> bytes:
        return self.value


class _Paginator:
    def __init__(self, s3: "FakeS3") -> None:
        self.s3 = s3

    def paginate(self, *, Bucket, Prefix, Delimiter=None):
        if Delimiter == "/":
            common_prefixes = {
                f"{Prefix}{key.removeprefix(Prefix).split('/', maxsplit=1)[0]}/"
                for key in self.s3.objects
                if key.startswith(Prefix) and "/" in key.removeprefix(Prefix)
            }
            return [{"CommonPrefixes": [{"Prefix": value} for value in sorted(common_prefixes)]}]
        return [
            {
                "Contents": [
                    {"Key": key} for key in sorted(self.s3.objects) if key.startswith(Prefix)
                ]
            }
        ]


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def get_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise _client_error("NoSuchKey")
        return {"Body": _Body(self.objects[Key])}

    def get_paginator(self, name: str):
        assert name == "list_objects_v2"
        return _Paginator(self)


def _put_json(s3: FakeS3, key: str, value: object) -> None:
    s3.objects[key] = json.dumps(value).encode()


def _manifest(
    s3: FakeS3,
    run_id: str,
    *,
    mode: str = "full",
    candidate_count: int = 100,
    input_size: int | None = None,
    completed_at: datetime | None = None,
) -> None:
    _put_json(
        s3,
        f"scraper/runs/{run_id}/manifest.json",
        {
            "run_id": run_id,
            "selection_mode": mode,
            "candidate_count": candidate_count,
            "input_size": candidate_count if input_size is None else input_size,
            "completed_at": completed_at.isoformat() if completed_at else None,
        },
    )


def _terminal(
    s3: FakeS3,
    run_id: str,
    *,
    released_at: datetime,
    status: str = "success",
    owner: str | None = None,
    record_run_id: str | None = None,
) -> None:
    created_at = released_at - timedelta(hours=1)
    _put_json(
        s3,
        f"scraper/runs/{run_id}/lease-terminal.json",
        {
            "run_id": record_run_id or run_id,
            "owner": owner or f"process:{run_id}",
            "created_at": created_at.isoformat(),
            "expires_at": released_at.isoformat(),
            "terminal_status": status,
            "detail": None,
            "release_requested_at": released_at.isoformat(),
            "released_at": released_at.isoformat(),
        },
    )


def _active(s3: FakeS3, run_id: str, *, expires_at: datetime) -> None:
    _put_json(
        s3,
        "scraper/active-run.json",
        {
            "run_id": run_id,
            "owner": run_id,
            "created_at": (NOW - timedelta(hours=1)).isoformat(),
            "expires_at": expires_at.isoformat(),
        },
    )


def _find(s3: FakeS3, *, count: int = 100):
    return find_full_run_suppression(
        s3,  # ty: ignore[invalid-argument-type]
        _config(),
        current_candidate_count=count,
        minimum_interval=timedelta(hours=24),
        now=NOW,
    )


def test_active_full_run_suppresses_cleanly_and_reports_count_drift() -> None:
    s3 = FakeS3()
    _active(s3, "run-active", expires_at=NOW + timedelta(hours=23))
    _manifest(s3, "run-active", candidate_count=100)

    suppression = _find(s3, count=103)

    assert suppression is not None
    assert suppression.run_id == "run-active"
    assert suppression.reason == "active"
    assert suppression.candidate_count_drift == 3


def test_active_sample_run_cannot_suppress_a_full_run() -> None:
    s3 = FakeS3()
    _active(s3, "run-sample", expires_at=NOW + timedelta(hours=23))
    _manifest(s3, "run-sample", mode="sample", candidate_count=100, input_size=10)

    assert _find(s3) is None


def test_recent_successful_full_run_suppresses_despite_count_drift() -> None:
    s3 = FakeS3()
    released_at = NOW - timedelta(hours=12)
    _manifest(
        s3,
        "run-full",
        candidate_count=100,
        completed_at=released_at - timedelta(minutes=5),
    )
    _terminal(s3, "run-full", released_at=released_at)

    suppression = _find(s3, count=101)

    assert suppression is not None
    assert suppression.reason == "recent-success"
    assert suppression.reference_at == released_at
    assert suppression.candidate_count_drift == 1


@pytest.mark.parametrize(
    ("mode", "status", "age_hours"),
    [
        ("sample", "success", 12),
        ("incremental", "success", 12),
        ("full", "failure", 12),
        ("full", "success", 25),
    ],
)
def test_ineligible_terminal_run_does_not_suppress(
    mode: str,
    status: str,
    age_hours: int,
) -> None:
    s3 = FakeS3()
    released_at = NOW - timedelta(hours=age_hours)
    input_size = 10 if mode != "full" else 100
    _manifest(
        s3,
        "run-old",
        mode=mode,
        candidate_count=100,
        input_size=input_size,
        completed_at=released_at - timedelta(minutes=5),
    )
    _terminal(s3, "run-old", released_at=released_at, status=status)

    assert _find(s3) is None


def test_legacy_untyped_success_cannot_suppress_required_full_run() -> None:
    s3 = FakeS3()
    released_at = NOW - timedelta(hours=1)
    _put_json(
        s3,
        "scraper/runs/run-legacy/manifest.json",
        {
            "run_id": "run-legacy",
            "timestamp": (released_at - timedelta(hours=1)).isoformat(),
            "input_size": 10,
            "completed_at": (released_at - timedelta(minutes=5)).isoformat(),
        },
    )
    _terminal(s3, "run-legacy", released_at=released_at)

    assert _find(s3) is None


def test_non_processing_success_cannot_suppress_required_full_run() -> None:
    s3 = FakeS3()
    released_at = NOW - timedelta(hours=1)
    _manifest(
        s3,
        "run-monitor",
        completed_at=released_at - timedelta(minutes=5),
    )
    _terminal(s3, "run-monitor", released_at=released_at, owner="run-monitor")

    assert _find(s3) is None


def test_terminal_identity_mismatch_cannot_suppress_required_full_run() -> None:
    s3 = FakeS3()
    released_at = NOW - timedelta(hours=1)
    _manifest(
        s3,
        "run-path",
        completed_at=released_at - timedelta(minutes=5),
    )
    _terminal(
        s3,
        "run-path",
        released_at=released_at,
        record_run_id="run-other",
    )

    assert _find(s3) is None


def test_malformed_typed_success_fails_closed() -> None:
    s3 = FakeS3()
    released_at = NOW - timedelta(hours=1)
    _put_json(
        s3,
        "scraper/runs/run-malformed/manifest.json",
        {
            "run_id": "run-malformed",
            "selection_mode": "full",
            "candidate_count": 100,
            "input_size": 99,
            "completed_at": (released_at - timedelta(minutes=5)).isoformat(),
        },
    )
    _terminal(s3, "run-malformed", released_at=released_at)

    with pytest.raises(ValueError, match="manifest.*invalid"):
        _find(s3)


def test_future_dated_success_fails_closed() -> None:
    s3 = FakeS3()
    released_at = NOW + timedelta(minutes=1)
    _manifest(
        s3,
        "run-future",
        completed_at=NOW,
    )
    _terminal(s3, "run-future", released_at=released_at)

    with pytest.raises(ValueError, match="future-dated"):
        _find(s3)


@pytest.mark.parametrize(
    ("count", "interval", "message"),
    [
        (0, timedelta(hours=24), "candidate_count"),
        (100, timedelta(0), "minimum_interval"),
    ],
)
def test_invalid_guard_arguments_fail_closed(
    count: int,
    interval: timedelta,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        find_full_run_suppression(
            FakeS3(),  # ty: ignore[invalid-argument-type]
            _config(),
            current_candidate_count=count,
            minimum_interval=interval,
            now=NOW,
        )
