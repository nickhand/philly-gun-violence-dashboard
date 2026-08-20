"""Tests for the S3 compare-and-swap active-run lease."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Lock
from typing import Literal

import pytest
from aws_batch_scraper.config import WorkerConfig
from aws_batch_scraper.lease import (
    RunLeaseConflict,
    acquire_run_lease,
    claim_run_lease,
    claim_run_lease_for_processing,
    claim_run_lease_for_recovery,
    finalizing_run_owner,
    reconcile_run_lease_from_recovery,
    release_run_lease,
    renew_run_lease,
    return_run_lease_from_recovery,
)
from botocore.exceptions import ClientError


def _config() -> WorkerConfig:
    return WorkerConfig(
        _env_file=None,
        s3_bucket="bucket",
        s3_scraper_prefix="scraper",
        aws_account_id="123456789012",
        sqs_queue_name="queue",
        sqs_dlq_name="queue-dlq",
    )


class FakeBody:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def read(self) -> bytes:
        return self.data


def _client_error(code: str, operation: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, operation)


class FakeS3:
    """In-memory S3 fake implementing conditional object operations."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.etags: dict[str, int] = {}

    def get_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise _client_error("NoSuchKey", "GetObject")
        return {"Body": FakeBody(self.objects[Key]), "ETag": f'"{self.etags[Key]}"'}

    def put_object(self, *, Bucket, Key, Body, IfNoneMatch=None, IfMatch=None, **kwargs):
        if IfNoneMatch == "*" and Key in self.objects:
            raise _client_error("PreconditionFailed", "PutObject")
        current_etag = f'"{self.etags.get(Key, 0)}"'
        if IfMatch is not None and (Key not in self.objects or IfMatch != current_etag):
            raise _client_error("PreconditionFailed", "PutObject")
        self.objects[Key] = bytes(Body)
        self.etags[Key] = self.etags.get(Key, 0) + 1
        return {"ETag": f'"{self.etags[Key]}"'}

    def delete_object(self, *, Bucket, Key, IfMatch=None):
        if Key not in self.objects:
            raise _client_error("NoSuchKey", "DeleteObject")
        if IfMatch is not None and IfMatch != f'"{self.etags[Key]}"':
            raise _client_error("PreconditionFailed", "DeleteObject")
        del self.objects[Key]
        del self.etags[Key]


def test_rejects_overlapping_acquisition() -> None:
    s3 = FakeS3()
    now = datetime(2026, 8, 18, tzinfo=UTC)
    acquire_run_lease(s3, _config(), "run-1", now=now)

    with pytest.raises(RunLeaseConflict, match="Run run-1 owns"):
        acquire_run_lease(s3, _config(), "run-2", now=now + timedelta(minutes=1))

    active = json.loads(s3.objects["scraper/active-run.json"])
    assert active["run_id"] == "run-1"


def test_natural_expiry_cannot_authorize_cross_run_takeover() -> None:
    s3 = FakeS3()
    now = datetime(2026, 8, 18, tzinfo=UTC)
    acquire_run_lease(s3, _config(), "run-1", now=now, ttl=timedelta(minutes=1))

    with pytest.raises(RunLeaseConflict, match="no completed terminal evidence.*Reconcile"):
        acquire_run_lease(
            s3,
            _config(),
            "run-2",
            now=now + timedelta(minutes=2),
        )

    active = json.loads(s3.objects["scraper/active-run.json"])
    assert active["run_id"] == "run-1"


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("run_id", "run-other"),
        ("owner", "owner-other"),
        ("created_at", "2026-08-17T00:00:00Z"),
    ],
)
def test_cross_run_takeover_rejects_terminal_evidence_for_another_lease(
    field: str,
    bad_value: str,
) -> None:
    s3 = FakeS3()
    now = datetime(2026, 8, 18, tzinfo=UTC)
    acquire_run_lease(s3, _config(), "run-1", now=now)
    assert release_run_lease(
        s3,
        _config(),
        "run-1",
        terminal_status="failure",
        detail="tasks and queues reconciled",
        now=now + timedelta(minutes=1),
    )
    terminal_key = "scraper/runs/run-1/lease-terminal.json"
    terminal = json.loads(s3.objects[terminal_key])
    terminal[field] = bad_value
    s3.objects[terminal_key] = json.dumps(terminal).encode()

    with pytest.raises(RunLeaseConflict, match="terminal evidence does not match"):
        acquire_run_lease(
            s3,
            _config(),
            "run-2",
            now=now + timedelta(minutes=1, microseconds=1),
        )

    assert json.loads(s3.objects["scraper/active-run.json"])["run_id"] == "run-1"


def test_cross_run_takeover_rejects_incomplete_release_protocol() -> None:
    s3 = FakeS3()
    now = datetime(2026, 8, 18, tzinfo=UTC)
    acquire_run_lease(s3, _config(), "run-1", now=now)
    assert release_run_lease(
        s3,
        _config(),
        "run-1",
        terminal_status="failure",
        detail="tasks and queues reconciled",
        now=now + timedelta(minutes=1),
    )
    terminal_key = "scraper/runs/run-1/lease-terminal.json"
    terminal = json.loads(s3.objects[terminal_key])
    del terminal["released_at"]
    s3.objects[terminal_key] = json.dumps(terminal).encode()

    with pytest.raises(RunLeaseConflict, match="release of expired lease.*did not complete"):
        acquire_run_lease(
            s3,
            _config(),
            "run-2",
            now=now + timedelta(minutes=1, microseconds=1),
        )

    assert json.loads(s3.objects["scraper/active-run.json"])["run_id"] == "run-1"


def test_wrong_owner_cannot_release() -> None:
    s3 = FakeS3()
    now = datetime(2026, 8, 18, tzinfo=UTC)
    acquire_run_lease(s3, _config(), "run-1", owner="owner-1", now=now)

    released = release_run_lease(
        s3,
        _config(),
        "run-1",
        owner="owner-2",
        terminal_status="failure",
        now=now,
    )

    assert released is False
    assert "scraper/active-run.json" in s3.objects


def test_stale_generation_cannot_release_successor_with_same_owner() -> None:
    s3 = FakeS3()
    now = datetime(2026, 8, 18, tzinfo=UTC)
    acquire_run_lease(s3, _config(), "run-1", now=now)

    released = release_run_lease(
        s3,
        _config(),
        "run-1",
        expected_created_at=now - timedelta(minutes=1),
        terminal_status="failure",
    )

    assert released is False
    assert "scraper/runs/run-1/lease-terminal.json" not in s3.objects


def test_processing_claim_accepts_exact_finalizing_generation() -> None:
    s3 = FakeS3()
    now = datetime(2026, 8, 18, tzinfo=UTC)
    acquired = acquire_run_lease(s3, _config(), "run-1", now=now)
    finalizing_owner = finalizing_run_owner("run-1", acquired.created_at)
    claim_run_lease(
        s3,
        _config(),
        "run-1",
        finalizing_owner,
        expected_created_at=acquired.created_at,
        now=now + timedelta(seconds=1),
    )

    claimed = claim_run_lease_for_processing(
        s3,
        _config(),
        "run-1",
        "process:attempt-1",
        now=now + timedelta(seconds=2),
    )

    assert claimed.owner == "process:attempt-1"
    assert claimed.created_at == acquired.created_at


def test_failed_release_preserves_terminal_evidence() -> None:
    s3 = FakeS3()
    now = datetime(2026, 8, 18, tzinfo=UTC)
    acquire_run_lease(s3, _config(), "run-1", now=now)

    released = release_run_lease(
        s3,
        _config(),
        "run-1",
        terminal_status="failure",
        detail="worker failed",
        now=now + timedelta(minutes=1),
    )

    assert released is True
    released_lease = json.loads(s3.objects["scraper/active-run.json"])
    assert released_lease["expires_at"] == "2026-08-18T00:01:00Z"
    terminal = json.loads(s3.objects["scraper/runs/run-1/lease-terminal.json"])
    assert terminal["terminal_status"] == "failure"
    assert terminal["detail"] == "worker failed"
    assert terminal["released_at"] == "2026-08-18T00:01:00Z"

    replacement = acquire_run_lease(
        s3,
        _config(),
        "run-2",
        now=now + timedelta(minutes=1, microseconds=1),
    )
    assert replacement.run_id == "run-2"


def test_recovery_claim_fences_old_coordinator_and_can_return_to_run_owner() -> None:
    s3 = FakeS3()
    now = datetime(2026, 8, 18, tzinfo=UTC)
    acquire_run_lease(s3, _config(), "run-1", now=now)

    recovery_lease = claim_run_lease_for_recovery(
        s3,
        _config(),
        "run-1",
        "attempt-1",
        now=now + timedelta(minutes=1),
    )

    assert recovery_lease.owner == "recovery:attempt-1"
    with pytest.raises(RunLeaseConflict, match="owned by.*recovery"):
        renew_run_lease(s3, _config(), "run-1", now=now + timedelta(minutes=2))

    returned = return_run_lease_from_recovery(
        s3,
        _config(),
        "run-1",
        "attempt-1",
        now=now + timedelta(minutes=2),
    )
    assert returned.owner == "run-1"
    renewed = renew_run_lease(
        s3,
        _config(),
        "run-1",
        now=now + timedelta(minutes=3),
    )
    assert renewed.owner == "run-1"


def test_reconciled_expired_recovery_stays_same_run_fenced() -> None:
    s3 = FakeS3()
    now = datetime(2026, 8, 18, tzinfo=UTC)
    acquire_run_lease(s3, _config(), "run-1", now=now)
    recovery = claim_run_lease_for_recovery(
        s3,
        _config(),
        "run-1",
        "attempt-1",
        now=now + timedelta(minutes=1),
        ttl=timedelta(minutes=1),
    )

    returned = reconcile_run_lease_from_recovery(
        s3,
        _config(),
        "run-1",
        "attempt-1",
        expected_created_at=recovery.created_at,
        now=now + timedelta(minutes=3),
        ttl=timedelta(minutes=1),
    )

    assert returned.owner == "run-1"
    assert returned.created_at == now + timedelta(minutes=3)
    assert not release_run_lease(
        s3,
        _config(),
        "run-1",
        owner="recovery:attempt-1",
        expected_created_at=recovery.created_at,
        terminal_status="failure",
        now=now + timedelta(minutes=4),
    )
    with pytest.raises(RunLeaseConflict, match="terminal evidence"):
        acquire_run_lease(
            s3,
            _config(),
            "run-2",
            now=now + timedelta(minutes=5),
        )
    retried = claim_run_lease_for_recovery(
        s3,
        _config(),
        "run-1",
        "attempt-2",
        now=now + timedelta(minutes=5),
    )
    assert retried.owner == "recovery:attempt-2"


def test_reconciled_handoff_accepts_lost_put_response_only_after_exact_read() -> None:
    class LostResponseS3(FakeS3):
        lose_next_response = False

        def put_object(self, **kwargs):
            response = super().put_object(**kwargs)
            if self.lose_next_response:
                self.lose_next_response = False
                raise TimeoutError("lease response lost")
            return response

    s3 = LostResponseS3()
    now = datetime(2026, 8, 18, tzinfo=UTC)
    acquire_run_lease(s3, _config(), "run-1", now=now)
    recovery_lease = claim_run_lease_for_recovery(
        s3,
        _config(),
        "run-1",
        "attempt-1",
        now=now + timedelta(minutes=1),
    )
    s3.lose_next_response = True

    returned = reconcile_run_lease_from_recovery(
        s3,
        _config(),
        "run-1",
        "attempt-1",
        expected_created_at=recovery_lease.created_at,
        now=now + timedelta(minutes=2),
    )

    assert returned.owner == "run-1"
    assert json.loads(s3.objects["scraper/active-run.json"])["created_at"] == (
        returned.created_at.isoformat().replace("+00:00", "Z")
    )


def test_recovery_claim_rejects_successfully_released_run() -> None:
    s3 = FakeS3()
    now = datetime(2026, 8, 18, tzinfo=UTC)
    acquire_run_lease(s3, _config(), "run-1", now=now)
    assert release_run_lease(
        s3,
        _config(),
        "run-1",
        terminal_status="success",
        now=now + timedelta(minutes=1),
    )

    with pytest.raises(RunLeaseConflict, match="successfully completed"):
        claim_run_lease_for_recovery(
            s3,
            _config(),
            "run-1",
            "attempt-1",
            now=now + timedelta(minutes=2),
        )


def test_failed_recovery_can_be_reclaimed_only_after_expiry_and_terminal_release() -> None:
    s3 = FakeS3()
    now = datetime(2026, 8, 18, tzinfo=UTC)
    acquire_run_lease(s3, _config(), "run-1", now=now)
    claim_run_lease_for_recovery(
        s3,
        _config(),
        "run-1",
        "attempt-1",
        now=now + timedelta(minutes=1),
        ttl=timedelta(minutes=1),
    )

    with pytest.raises(RunLeaseConflict, match="active recovery lease"):
        claim_run_lease_for_recovery(
            s3,
            _config(),
            "run-1",
            "attempt-2",
            now=now + timedelta(minutes=1, seconds=30),
        )

    assert release_run_lease(
        s3,
        _config(),
        "run-1",
        owner="recovery:attempt-1",
        terminal_status="failure",
        now=now + timedelta(minutes=2),
    )
    retried = claim_run_lease_for_recovery(
        s3,
        _config(),
        "run-1",
        "attempt-2",
        now=now + timedelta(minutes=2, microseconds=1),
    )
    assert retried.owner == "recovery:attempt-2"


def test_only_one_cross_run_acquirer_can_replace_a_released_lease() -> None:
    s3 = FakeS3()
    now = datetime(2026, 8, 18, tzinfo=UTC)
    acquire_run_lease(s3, _config(), "run-1", now=now)
    assert release_run_lease(
        s3,
        _config(),
        "run-1",
        terminal_status="success",
        now=now + timedelta(minutes=1),
    )
    acquired_at = now + timedelta(minutes=1, microseconds=1)

    def acquire(candidate: str) -> str:
        try:
            acquire_run_lease(s3, _config(), candidate, now=acquired_at)
        except RunLeaseConflict:
            return "conflict"
        return candidate

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(acquire, ["run-2", "run-3"]))

    winners = [outcome for outcome in outcomes if outcome != "conflict"]
    assert len(winners) == 1
    assert outcomes.count("conflict") == 1
    assert json.loads(s3.objects["scraper/active-run.json"])["run_id"] == winners[0]


def test_concurrent_releaser_cannot_overwrite_winners_terminal_evidence() -> None:
    class ConcurrentReleaseS3(FakeS3):
        def __init__(self) -> None:
            super().__init__()
            self._active_reads = 0
            self._read_lock = Lock()
            self._put_lock = Lock()
            self._release_barrier = Barrier(2)

        def get_object(self, *, Bucket, Key):
            response = super().get_object(Bucket=Bucket, Key=Key)
            wait_for_peer = False
            if Key == "scraper/active-run.json":
                with self._read_lock:
                    if self._active_reads < 2:
                        self._active_reads += 1
                        wait_for_peer = True
            if wait_for_peer:
                self._release_barrier.wait()
            return response

        def put_object(self, **kwargs):
            with self._put_lock:
                return super().put_object(**kwargs)

    s3 = ConcurrentReleaseS3()
    now = datetime(2026, 8, 18, tzinfo=UTC)
    acquire_run_lease(s3, _config(), "run-1", now=now)
    released_at = now + timedelta(minutes=1)

    def release(status: Literal["success", "failure"]) -> tuple[str, str]:
        try:
            release_run_lease(
                s3,
                _config(),
                "run-1",
                terminal_status=status,
                now=released_at,
            )
        except RunLeaseConflict:
            return status, "conflict"
        return status, "released"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(release, ["success", "failure"]))

    winner = next(status for status, outcome in outcomes if outcome == "released")
    assert [outcome for _, outcome in outcomes].count("released") == 1
    assert [outcome for _, outcome in outcomes].count("conflict") == 1
    terminal = json.loads(s3.objects["scraper/runs/run-1/lease-terminal.json"])
    assert terminal["terminal_status"] == winner
    assert terminal["released_at"] == "2026-08-18T00:01:00Z"
    replacement = acquire_run_lease(
        s3,
        _config(),
        "run-2",
        now=released_at + timedelta(microseconds=1),
    )
    assert replacement.run_id == "run-2"


def test_completed_release_is_idempotent_but_cannot_change_terminal_status() -> None:
    s3 = FakeS3()
    now = datetime(2026, 8, 18, tzinfo=UTC)
    acquire_run_lease(s3, _config(), "run-1", now=now)
    assert release_run_lease(
        s3,
        _config(),
        "run-1",
        terminal_status="success",
        detail="complete",
        now=now + timedelta(minutes=1),
    )
    terminal_key = "scraper/runs/run-1/lease-terminal.json"
    first_terminal = s3.objects[terminal_key]

    assert release_run_lease(
        s3,
        _config(),
        "run-1",
        terminal_status="success",
        detail="complete",
        now=now + timedelta(minutes=2),
    )
    assert s3.objects[terminal_key] == first_terminal

    with pytest.raises(RunLeaseConflict, match="already released with status=success"):
        release_run_lease(
            s3,
            _config(),
            "run-1",
            terminal_status="failure",
            detail="changed conclusion",
            now=now + timedelta(minutes=2),
        )
    assert s3.objects[terminal_key] == first_terminal


def test_renewal_extends_only_owned_lease() -> None:
    s3 = FakeS3()
    now = datetime(2026, 8, 18, tzinfo=UTC)
    original = acquire_run_lease(s3, _config(), "run-1", owner="owner-1", now=now)

    renewed = renew_run_lease(
        s3,
        _config(),
        "run-1",
        owner="owner-1",
        now=now + timedelta(hours=1),
    )

    assert renewed.created_at == original.created_at
    assert renewed.expires_at == now + timedelta(hours=25)
    with pytest.raises(RunLeaseConflict, match="Cannot renew"):
        renew_run_lease(s3, _config(), "run-1", owner="owner-2", now=now)


def test_expired_lease_cannot_be_renewed_by_its_former_owner() -> None:
    s3 = FakeS3()
    now = datetime(2026, 8, 18, tzinfo=UTC)
    acquire_run_lease(s3, _config(), "run-1", now=now, ttl=timedelta(minutes=1))

    with pytest.raises(RunLeaseConflict, match="expired lease"):
        renew_run_lease(
            s3,
            _config(),
            "run-1",
            now=now + timedelta(minutes=1),
        )


def test_only_one_processor_can_claim_a_completed_run() -> None:
    s3 = FakeS3()
    now = datetime(2026, 8, 18, tzinfo=UTC)
    acquire_run_lease(s3, _config(), "run-1", now=now)

    claimed = claim_run_lease_for_processing(
        s3,
        _config(),
        "run-1",
        "process:first",
        now=now + timedelta(minutes=1),
    )

    assert claimed.owner == "process:first"
    with pytest.raises(RunLeaseConflict, match="active processing lease"):
        claim_run_lease_for_processing(
            s3,
            _config(),
            "run-1",
            "process:duplicate",
            now=now + timedelta(minutes=2),
        )

    assert release_run_lease(
        s3,
        _config(),
        "run-1",
        owner="process:first",
        terminal_status="success",
        now=now + timedelta(minutes=2),
    )


def test_completed_run_can_claim_its_expired_coordinator_lease() -> None:
    s3 = FakeS3()
    now = datetime(2026, 8, 18, tzinfo=UTC)
    acquire_run_lease(s3, _config(), "run-1", now=now, ttl=timedelta(minutes=1))

    claimed = claim_run_lease_for_processing(
        s3,
        _config(),
        "run-1",
        "process:recovery",
        now=now + timedelta(minutes=2),
    )

    assert claimed.owner == "process:recovery"
    assert claimed.expires_at == now + timedelta(hours=24, minutes=2)


def test_expired_run_cannot_reclaim_after_replacement_takes_over() -> None:
    s3 = FakeS3()
    now = datetime(2026, 8, 18, tzinfo=UTC)
    acquire_run_lease(s3, _config(), "run-1", now=now, ttl=timedelta(minutes=1))
    assert release_run_lease(
        s3,
        _config(),
        "run-1",
        terminal_status="failure",
        detail="tasks and queues reconciled",
        now=now + timedelta(minutes=2),
    )
    acquire_run_lease(
        s3,
        _config(),
        "run-2",
        now=now + timedelta(minutes=2, microseconds=1),
    )

    with pytest.raises(RunLeaseConflict, match="Cannot claim lease owned by run=run-2"):
        claim_run_lease_for_processing(
            s3,
            _config(),
            "run-1",
            "process:late",
            now=now + timedelta(minutes=3),
        )


def test_failed_processing_lease_can_be_retried() -> None:
    s3 = FakeS3()
    now = datetime(2026, 8, 18, tzinfo=UTC)
    acquire_run_lease(s3, _config(), "run-1", now=now)
    claim_run_lease_for_processing(
        s3,
        _config(),
        "run-1",
        "process:first",
        now=now + timedelta(minutes=1),
    )
    assert release_run_lease(
        s3,
        _config(),
        "run-1",
        owner="process:first",
        terminal_status="failure",
        detail="aggregation failed",
        now=now + timedelta(minutes=2),
    )

    retried = claim_run_lease_for_processing(
        s3,
        _config(),
        "run-1",
        "process:retry",
        now=now + timedelta(minutes=2, microseconds=1),
    )

    assert retried.owner == "process:retry"


def test_successful_processing_lease_cannot_be_retried() -> None:
    s3 = FakeS3()
    now = datetime(2026, 8, 18, tzinfo=UTC)
    acquire_run_lease(s3, _config(), "run-1", now=now)
    claim_run_lease_for_processing(
        s3,
        _config(),
        "run-1",
        "process:first",
        now=now + timedelta(minutes=1),
    )
    assert release_run_lease(
        s3,
        _config(),
        "run-1",
        owner="process:first",
        terminal_status="success",
        now=now + timedelta(minutes=2),
    )

    with pytest.raises(RunLeaseConflict, match="successfully processed"):
        claim_run_lease_for_processing(
            s3,
            _config(),
            "run-1",
            "process:duplicate",
            now=now + timedelta(minutes=2, microseconds=1),
        )


@pytest.mark.parametrize("field,bad_value", [("run_id", "run-2"), ("owner", "process:other")])
def test_processing_retry_rejects_terminal_evidence_for_another_owner(
    field: str,
    bad_value: str,
) -> None:
    s3 = FakeS3()
    now = datetime(2026, 8, 18, tzinfo=UTC)
    acquire_run_lease(s3, _config(), "run-1", now=now)
    claim_run_lease_for_processing(
        s3,
        _config(),
        "run-1",
        "process:first",
        now=now + timedelta(minutes=1),
    )
    assert release_run_lease(
        s3,
        _config(),
        "run-1",
        owner="process:first",
        terminal_status="failure",
        now=now + timedelta(minutes=2),
    )
    terminal_key = "scraper/runs/run-1/lease-terminal.json"
    terminal = json.loads(s3.objects[terminal_key])
    terminal[field] = bad_value
    s3.objects[terminal_key] = json.dumps(terminal).encode()

    with pytest.raises(RunLeaseConflict, match="terminal evidence does not match"):
        claim_run_lease_for_processing(
            s3,
            _config(),
            "run-1",
            "process:retry",
            now=now + timedelta(minutes=2, microseconds=1),
        )


def test_processing_retry_rejects_missing_terminal_evidence() -> None:
    s3 = FakeS3()
    now = datetime(2026, 8, 18, tzinfo=UTC)
    acquire_run_lease(s3, _config(), "run-1", now=now)
    claim_run_lease_for_processing(
        s3,
        _config(),
        "run-1",
        "process:first",
        now=now + timedelta(minutes=1),
        ttl=timedelta(minutes=1),
    )

    with pytest.raises(RunLeaseConflict, match="no completed terminal evidence"):
        claim_run_lease_for_processing(
            s3,
            _config(),
            "run-1",
            "process:retry",
            now=now + timedelta(minutes=2),
        )


def test_processing_retry_rejects_incomplete_terminal_release() -> None:
    s3 = FakeS3()
    now = datetime(2026, 8, 18, tzinfo=UTC)
    acquire_run_lease(s3, _config(), "run-1", now=now)
    claim_run_lease_for_processing(
        s3,
        _config(),
        "run-1",
        "process:first",
        now=now + timedelta(minutes=1),
    )
    assert release_run_lease(
        s3,
        _config(),
        "run-1",
        owner="process:first",
        terminal_status="failure",
        now=now + timedelta(minutes=2),
    )
    terminal_key = "scraper/runs/run-1/lease-terminal.json"
    terminal = json.loads(s3.objects[terminal_key])
    del terminal["released_at"]
    s3.objects[terminal_key] = json.dumps(terminal).encode()

    with pytest.raises(RunLeaseConflict, match="release of expired lease.*did not complete"):
        claim_run_lease_for_processing(
            s3,
            _config(),
            "run-1",
            "process:retry",
            now=now + timedelta(minutes=2, microseconds=1),
        )
