"""Reviewed retirement remains run-bound, explicit, and distinct from success."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from aws_batch_scraper import recovery
from aws_batch_scraper import task_reconciliation as reconciliation
from aws_batch_scraper.aggregate import RunManifest
from aws_batch_scraper.lease import RunLease
from aws_batch_scraper.recovery import QueueState
from aws_batch_scraper.task_reconciliation import (
    RetirementReview,
    read_retired_task,
    reconcile_retired_tasks,
)
from test_orchestrate import _submitter_config
from test_task_evidence import MemoryS3


def setup_review(monkeypatch):
    now = datetime.now(UTC)
    s3, sqs, ecs, config = MemoryS3(), MagicMock(), MagicMock(), _submitter_config()
    lease = RunLease(
        run_id="run-1",
        owner="run-1",
        created_at=now - timedelta(days=3),
        expires_at=now - timedelta(days=2),
    )
    manifest = RunManifest(
        run_id="run-1",
        selection_mode="full",
        candidate_count=1,
        input_size=1,
        input_sha256="a" * 64,
    )
    monkeypatch.setattr(reconciliation, "read_run_lease", lambda *args: lease)
    monkeypatch.setattr(reconciliation, "read_run_manifest", lambda *args: manifest)
    monkeypatch.setattr(recovery, "read_prior_task_arns", lambda *args: ("arn:task/a",))
    monkeypatch.setattr(recovery, "_recovery_attempt_ids", lambda *args: ())
    monkeypatch.setattr(recovery, "_require_no_live_started_by_set", lambda *args: None)
    monkeypatch.setattr(recovery, "read_queue_state", lambda *args: QueueState(0, 0, 0))
    monkeypatch.setattr(reconciliation.time, "sleep", lambda seconds: None)
    ecs.describe_tasks.return_value = {
        "tasks": [],
        "failures": [{"arn": "arn:task/a", "reason": "MISSING"}],
    }
    review = RetirementReview(
        run_id="run-1",
        cluster_arn=config.ecs_cluster_arn,
        input_sha256="a" * 64,
        task_set_sha256=hashlib.sha256(b'["arn:task/a"]').hexdigest(),
        lease_created_at=lease.created_at,
        reviewed_at=now,
        reviewer="operator",
        rationale="Reviewed retained task status and original monitor evidence.",
        evidence=(
            "Retained CloudWatch event with exact original run/task identities "
            "and STOPPED observation."
        ),
        retired_task_arns=("arn:task/a",),
        conclusion="stopped-exit-status-unknown",
    )
    return s3, sqs, ecs, config, review


def test_preview_is_read_only_and_execution_is_idempotent(monkeypatch):
    s3, sqs, ecs, config, review = setup_review(monkeypatch)
    reconcile_retired_tasks(s3, sqs, ecs, config, review)
    assert s3.writes == 0
    reconcile_retired_tasks(s3, sqs, ecs, config, review, execute=True)
    assert s3.writes == 1
    reconcile_retired_tasks(s3, sqs, ecs, config, review, execute=True)
    assert s3.writes == 1
    task = read_retired_task(s3, config, "run-1", "arn:task/a")
    assert task["lastStatus"] == "STOPPED"
    assert task["containers"] == []  # no invented successful exit code
    ecs.stop_task.assert_not_called()
    sqs.send_message.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("input_sha256", "b" * 64),
        ("task_set_sha256", "b" * 64),
        ("run_id", "other-run"),
        ("retired_task_arns", ("arn:task/other",)),
        ("reviewed_at", datetime.now(UTC) + timedelta(days=1)),
    ],
)
def test_changed_or_future_review_cannot_write(monkeypatch, field, value):
    s3, sqs, ecs, config, review = setup_review(monkeypatch)
    with pytest.raises(ValueError):
        reconcile_retired_tasks(
            s3, sqs, ecs, config, review.model_copy(update={field: value}), execute=True
        )
    assert s3.writes == 0


def test_live_task_and_transport_errors_are_not_retirement(monkeypatch):
    s3, sqs, ecs, config, review = setup_review(monkeypatch)
    for response in [
        {"tasks": [{"taskArn": "arn:task/a", "lastStatus": "RUNNING"}]},
        {"tasks": [], "failures": [{"arn": "arn:task/a", "reason": "AccessDenied"}]},
        {"tasks": [], "failures": []},
    ]:
        ecs.describe_tasks.return_value = response
        with pytest.raises(ValueError):
            reconcile_retired_tasks(s3, sqs, ecs, config, review, execute=True)
    assert s3.writes == 0


def test_queue_race_blocks_writes(monkeypatch):
    s3, sqs, ecs, config, review = setup_review(monkeypatch)
    monkeypatch.setattr(
        recovery,
        "read_queue_state",
        MagicMock(side_effect=[QueueState(0, 0, 0), QueueState(1, 0, 0)]),
    )
    with pytest.raises(ValueError, match="Queue changed"):
        reconcile_retired_tasks(s3, sqs, ecs, config, review, execute=True)
    assert s3.writes == 0


def test_conflicting_review_cannot_replace_an_earlier_resolution(monkeypatch):
    s3, sqs, ecs, config, review = setup_review(monkeypatch)
    reconcile_retired_tasks(s3, sqs, ecs, config, review, execute=True)
    with pytest.raises(ValueError, match="conflicts"):
        reconcile_retired_tasks(
            s3,
            sqs,
            ecs,
            config,
            review.model_copy(update={"reviewer": "another-operator"}),
            execute=True,
        )
    assert json.loads(next(iter(s3.objects.values())))["reviewer"] == "operator"


def test_lease_change_during_quiet_window_blocks_writes(monkeypatch):
    s3, sqs, ecs, config, review = setup_review(monkeypatch)
    lease = reconciliation.read_run_lease(s3, config)
    monkeypatch.setattr(
        reconciliation,
        "read_run_lease",
        MagicMock(
            side_effect=[
                lease,
                lease.model_copy(update={"created_at": lease.created_at + timedelta(seconds=1)}),
            ]
        ),
    )
    with pytest.raises(ValueError, match="lease"):
        reconcile_retired_tasks(s3, sqs, ecs, config, review, execute=True)
    assert s3.writes == 0


def test_review_proves_quiescence_but_cannot_make_normal_monitor_succeed(monkeypatch):
    from aws_batch_scraper.orchestrate import _assert_tasks_succeeded
    from aws_batch_scraper.task_evidence import TaskEvidenceError, describe_tasks_with_evidence

    s3, sqs, ecs, config, review = setup_review(monkeypatch)
    reconcile_retired_tasks(s3, sqs, ecs, config, review, execute=True)
    tasks = describe_tasks_with_evidence(
        ecs, s3, config, "run-1", ["arn:task/a"], allow_reviewed_retirement=True
    )
    assert tasks[0]["containers"] == []
    with pytest.raises(RuntimeError):
        _assert_tasks_succeeded(tasks)
    with pytest.raises(TaskEvidenceError):
        describe_tasks_with_evidence(ecs, s3, config, "run-1", ["arn:task/a"])
