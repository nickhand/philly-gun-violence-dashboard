"""Independent watchdog detects the actual failure modes without AWS mutation."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from aws_batch_scraper import health
from aws_batch_scraper.aggregate import RunManifest
from aws_batch_scraper.health import Diagnostic, check_run_health, monitor_state_key
from aws_batch_scraper.lease import RunLease
from test_orchestrate import _submitter_config
from test_task_evidence import MemoryS3, task

NOW = datetime(2026, 9, 21, 19, tzinfo=UTC)


def setup_run(monkeypatch, *, age=timedelta(hours=1)):
    s3, ecs, config = MemoryS3(), MagicMock(), _submitter_config()
    lease = RunLease(
        run_id="run-1", owner="run-1", created_at=NOW - age, expires_at=NOW + timedelta(hours=1)
    )
    manifest = RunManifest(
        run_id="run-1",
        selection_mode="full",
        candidate_count=1,
        input_size=1,
        timestamp=(NOW - age).isoformat(),
    )
    monkeypatch.setattr(health, "read_run_lease", lambda *args: lease)
    monkeypatch.setattr(health, "read_run_manifest", lambda *args: manifest)
    from aws_batch_scraper import recovery

    monkeypatch.setattr(recovery, "read_prior_task_arns", lambda *args: ("arn:task/a",))
    ecs.describe_tasks.return_value = {"tasks": [task("arn:task/a", "RUNNING")]}
    s3.get_paginator = MagicMock()
    s3.get_paginator.return_value.paginate.return_value = []
    return s3, ecs, config, lease


def test_healthy_run_is_read_only(monkeypatch):
    s3, ecs, config, _ = setup_run(monkeypatch)
    assert check_run_health(s3, ecs, config, now=NOW) == ("run-1", [])
    assert s3.writes == 0
    ecs.run_task.assert_not_called()
    ecs.stop_task.assert_not_called()


def test_original_incident_is_detected_without_monitor_diagnostics(monkeypatch):
    s3, ecs, config, lease = setup_run(monkeypatch, age=timedelta(days=3))
    monkeypatch.setattr(
        health,
        "read_run_lease",
        lambda *args: lease.model_copy(update={"expires_at": NOW - timedelta(days=2)}),
    )
    ecs.describe_tasks.return_value = {"tasks": [], "failures": [{"reason": "MISSING"}]}
    _, findings = check_run_health(s3, ecs, config, now=NOW)
    assert any("lease expired" in value for value in findings)
    assert any("run age" in value for value in findings)
    assert any("unavailable" in value for value in findings)
    assert s3.writes == 0


@pytest.mark.parametrize(
    "status,age,expected",
    [
        ("failed", timedelta(0), "monitor failed"),
        ("running", timedelta(minutes=11), "monitor heartbeat"),
        ("running", timedelta(minutes=-1), "future-dated"),
    ],
)
def test_failed_stale_and_future_monitor_diagnostics(monkeypatch, status, age, expected):
    s3, ecs, config, lease = setup_run(monkeypatch)
    diagnostic = Diagnostic(
        run_id="run-1",
        identity="run-1",
        lease_created_at=lease.created_at,
        observed_at=NOW - age,
        status=status,
        error_type="TaskEvidenceError" if status == "failed" else None,
    )
    s3.objects[monitor_state_key(config, lease)] = diagnostic.model_dump_json().encode()
    assert any(expected in value for value in check_run_health(s3, ecs, config, now=NOW)[1])


def test_worker_without_progress_is_reported(monkeypatch):
    s3, ecs, config, _ = setup_run(monkeypatch)
    key = "scraper/runs/run-1/worker-progress/v1/worker.json"
    s3.objects[key] = (
        Diagnostic(
            run_id="run-1",
            identity="worker-a",
            observed_at=NOW - timedelta(minutes=11),
            status="running",
        )
        .model_dump_json()
        .encode()
    )
    s3.get_paginator.return_value.paginate.return_value = [{"Contents": [{"Key": key}]}]
    assert any(
        "worker-a stopped reporting" in value
        for value in check_run_health(s3, ecs, config, now=NOW)[1]
    )


def test_dead_monitor_is_detected_before_twelve_hour_deadline(monkeypatch):
    s3, ecs, config, _ = setup_run(monkeypatch)
    s3.objects["scraper/runs/run-1/monitor-task.json"] = json.dumps(
        {"run_id": "run-1", "task_arn": "arn:task/monitor"}
    ).encode()
    ecs.describe_tasks.side_effect = [
        {"tasks": [task("arn:task/monitor", exit_code=1)]},
        {"tasks": [task("arn:task/a", "RUNNING")]},
    ]
    assert (
        "monitor task stopped before run completion"
        in check_run_health(s3, ecs, config, now=NOW)[1]
    )


def test_new_run_cannot_silently_omit_heartbeats(monkeypatch):
    s3, ecs, config, lease = setup_run(monkeypatch)
    manifest = RunManifest(
        run_id="run-1",
        selection_mode="full",
        candidate_count=1,
        input_size=1,
        timestamp=lease.created_at.isoformat(),
        monitoring_contract_version=1,
    )
    monkeypatch.setattr(health, "read_run_manifest", lambda *args: manifest)
    findings = check_run_health(s3, ecs, config, now=NOW)[1]
    assert "monitor has not reported its required heartbeat" in findings
    assert "workers have not reported required progress" in findings
    assert s3.writes == 0


def test_heartbeat_written_during_probe_is_not_future_dated(monkeypatch):
    s3, ecs, config, lease = setup_run(monkeypatch)
    clock = {"now": NOW}
    datetime_mock = MagicMock(wraps=datetime)
    datetime_mock.now.side_effect = lambda zone: clock["now"]
    monkeypatch.setattr(health, "datetime", datetime_mock)
    original_read = health._optional_json

    def read(s3, config, key):
        if key == monitor_state_key(config, lease):
            clock["now"] = NOW + timedelta(seconds=2)
            return (
                Diagnostic(
                    run_id=lease.run_id,
                    identity=lease.owner,
                    lease_created_at=lease.created_at,
                    observed_at=NOW + timedelta(seconds=1),
                    status="running",
                )
                .model_dump_json()
                .encode()
            )
        return original_read(s3, config, key)

    monkeypatch.setattr(health, "_optional_json", read)
    assert check_run_health(s3, ecs, config)[1] == []
