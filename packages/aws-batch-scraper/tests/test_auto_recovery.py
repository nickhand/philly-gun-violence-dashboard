"""Automatic retry must be bounded even after an ambiguous launch."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from aws_batch_scraper import auto_recovery as auto
from botocore.exceptions import ClientError
from test_orchestrate import _submitter_config
from test_task_evidence import MemoryS3, task


def pull_failure():
    return {
        "taskArn": "arn:task/failed",
        "lastStatus": "STOPPED",
        "stopCode": "TaskFailedToStart",
        "stoppedReason": "CannotPullContainerError: manifest not found",
        "containers": [{"name": "worker"}],
    }


def test_pull_failure_with_successful_siblings_is_eligible():
    auto.require_startup_failures([pull_failure(), task("arn:task/ok")])


@pytest.mark.parametrize(
    "bad",
    [
        [],
        [task("arn:task/ok")],
        [task("arn:task/live", "RUNNING")],
        [pull_failure(), task("arn:task/crash", exit_code=1)],
        [pull_failure(), task("arn:task/unknown", exit_code=None)],
        [{**pull_failure(), "stopCode": "UserInitiated"}],
        [{**pull_failure(), "stoppedReason": "ResourceInitializationError: credentials"}],
        [{**pull_failure(), "containers": [{"exitCode": 0}]}],
    ],
)
def test_other_failures_require_operator(bad):
    with pytest.raises(RuntimeError):
        auto.require_startup_failures(bad)


def setup(monkeypatch):
    s3 = MemoryS3()
    config = _submitter_config()
    monkeypatch.setattr(auto, "check_run_health", lambda *a: ("run-1", ["monitor failed"]))
    monkeypatch.setattr(
        auto, "read_run_lease", lambda *a: SimpleNamespace(run_id="run-1", owner="run-1")
    )
    monkeypatch.setattr(auto, "read_run_manifest", lambda *a: SimpleNamespace(completed_at=None))
    plan = SimpleNamespace(
        run_id="run-1",
        attempt_id="recovery-1",
        prior_task_arns=("arn:task/failed",),
        action=SimpleNamespace(value="complete"),
        as_dict=lambda: {"run_id": "run-1"},
    )
    monkeypatch.setattr(auto, "build_recovery_plan", lambda *a: plan)
    monkeypatch.setattr(auto, "describe_tasks_with_evidence", lambda *a, **kw: [pull_failure()])
    execute = MagicMock()
    monkeypatch.setattr(auto, "execute_recovery_plan", execute)
    return s3, config, execute


def test_preview_does_not_reserve_or_execute(monkeypatch):
    s3, config, execute = setup(monkeypatch)
    auto.auto_recover(s3, MagicMock(), MagicMock(), config, monitor_command=lambda *a: [])
    assert s3.writes == 0
    execute.assert_not_called()


def test_ambiguous_launch_consumes_the_single_attempt(monkeypatch):
    s3, config, execute = setup(monkeypatch)
    execute.side_effect = TimeoutError("unknown RunTask delivery")
    with pytest.raises(TimeoutError):
        auto.auto_recover(
            s3, MagicMock(), MagicMock(), config, execute=True, monitor_command=lambda *a: []
        )
    with pytest.raises(ClientError, match="PreconditionFailed"):
        auto.auto_recover(
            s3, MagicMock(), MagicMock(), config, execute=True, monitor_command=lambda *a: []
        )
    assert execute.call_count == 1


def test_failed_preflight_never_reserves_attempt(monkeypatch):
    s3, config, execute = setup(monkeypatch)
    monkeypatch.setattr(
        auto, "build_recovery_plan", MagicMock(side_effect=RuntimeError("conflict"))
    )
    with pytest.raises(RuntimeError, match="conflict"):
        auto.auto_recover(
            s3, MagicMock(), MagicMock(), config, execute=True, monitor_command=lambda *a: []
        )
    assert s3.writes == 0
    execute.assert_not_called()
