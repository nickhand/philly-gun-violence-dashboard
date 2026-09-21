"""Regression for a stopped worker aging out while another worker is still live."""

import json
from datetime import UTC, datetime
from io import BytesIO
from unittest.mock import MagicMock

import pytest
from aws_batch_scraper.task_evidence import (
    TaskEvidenceError,
    describe_tasks_with_evidence,
    persist_terminal_task,
    read_terminal_task,
    terminal_task_key,
)
from botocore.exceptions import ClientError
from test_orchestrate import _submitter_config


class MemoryS3:
    def __init__(self):
        self.objects = {}
        self.writes = 0

    def get_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": BytesIO(self.objects[Key])}

    def put_object(self, *, Bucket, Key, Body, **kwargs):
        if kwargs.get("IfNoneMatch") == "*" and Key in self.objects:
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        self.writes += 1
        self.objects[Key] = Body
        return {}


def task(arn, status="STOPPED", exit_code=0):
    return {
        "taskArn": arn,
        "lastStatus": status,
        "stopCode": "EssentialContainerExited",
        "containers": [{"name": "worker", "exitCode": exit_code}],
    }


def test_terminal_worker_is_not_requeried_after_ecs_expiry():
    s3, ecs, config = MemoryS3(), MagicMock(), _submitter_config()
    ecs.describe_tasks.side_effect = [
        {"tasks": [task("arn:task/a"), task("arn:task/b", "RUNNING")]},
        {"tasks": [task("arn:task/b")]},
    ]
    cache = {}
    first = describe_tasks_with_evidence(
        ecs, s3, config, "run-1", ["arn:task/a", "arn:task/b"], cache
    )
    assert [row["lastStatus"] for row in first] == ["STOPPED", "RUNNING"]
    second = describe_tasks_with_evidence(
        ecs, s3, config, "run-1", ["arn:task/a", "arn:task/b"], cache
    )
    assert all(row["lastStatus"] == "STOPPED" for row in second)
    assert ecs.describe_tasks.call_args.kwargs["tasks"] == ["arn:task/b"]
    # A restarted monitor reads durable records and makes no ECS call.
    ecs.reset_mock()
    describe_tasks_with_evidence(ecs, s3, config, "run-1", ["arn:task/a", "arn:task/b"])
    ecs.describe_tasks.assert_not_called()


def test_missing_task_without_saved_evidence_remains_an_error():
    s3, ecs = MemoryS3(), MagicMock()
    ecs.describe_tasks.return_value = {"failures": [{"arn": "arn:task/a", "reason": "MISSING"}]}
    with pytest.raises(TaskEvidenceError, match="without terminal evidence"):
        describe_tasks_with_evidence(ecs, s3, _submitter_config(), "run-1", ["arn:task/a"])


def test_exit_failure_and_unknown_status_are_preserved():
    s3, config = MemoryS3(), _submitter_config()
    failed = persist_terminal_task(s3, config, "run-1", task("arn:task/a", exit_code=137))
    assert failed.as_task()["containers"][0]["exitCode"] == 137
    unknown = task("arn:task/b")
    unknown["containers"] = [{"name": "worker"}]
    saved = persist_terminal_task(s3, config, "run-1", unknown)
    assert "exitCode" not in saved.as_task()["containers"][0]


def test_conflicting_or_wrong_run_evidence_cannot_authorize_recovery():
    s3, config = MemoryS3(), _submitter_config()
    persist_terminal_task(s3, config, "run-1", task("arn:task/a"))
    with pytest.raises(TaskEvidenceError, match="reconciled"):
        persist_terminal_task(s3, config, "run-1", task("arn:task/a", exit_code=1))
    key = terminal_task_key(config, "run-1", "arn:task/a")
    body = json.loads(s3.objects[key])
    body["run_id"] = "wrong-run"
    s3.objects[key] = json.dumps(body).encode()
    with pytest.raises(TaskEvidenceError, match="different run"):
        read_terminal_task(s3, config, "run-1", "arn:task/a")


def test_lost_put_response_is_reconciled_from_exact_terminal_record():
    s3, config = MemoryS3(), _submitter_config()
    original = s3.put_object

    def lost_response(**kwargs):
        original(**kwargs)
        raise TimeoutError("lost response")

    s3.put_object = lost_response
    assert persist_terminal_task(
        s3, config, "run-1", task("arn:task/a")
    ).observed_at <= datetime.now(UTC)


def test_recovery_preflight_reads_live_terminal_state_without_writing_it():
    from aws_batch_scraper.recovery import _describe_recovery_tasks, require_prior_tasks_stopped

    s3, ecs, config = MemoryS3(), MagicMock(), _submitter_config()
    ecs.describe_tasks.return_value = {"tasks": [task("arn:task/a")]}
    require_prior_tasks_stopped(ecs, config, ("arn:task/a",), s3, "run-1")
    assert (
        _describe_recovery_tasks(ecs, config, ("arn:task/a",), s3, "run-1")[0]["lastStatus"]
        == "STOPPED"
    )
    assert s3.writes == 0


def test_recovery_execution_retains_prior_terminal_observations():
    from aws_batch_scraper.recovery import require_prior_tasks_stopped

    s3, ecs, config = MemoryS3(), MagicMock(), _submitter_config()
    ecs.describe_tasks.return_value = {"tasks": [task("arn:task/a", exit_code=1)]}
    require_prior_tasks_stopped(ecs, config, ("arn:task/a",), s3, "run-1", True)
    assert s3.writes == 1
    assert read_terminal_task(s3, config, "run-1", "arn:task/a").containers[0].exit_code == 1


def test_partial_ecs_response_keeps_observed_terminal_evidence_but_fails():
    s3, ecs, config = MemoryS3(), MagicMock(), _submitter_config()
    ecs.describe_tasks.return_value = {
        "tasks": [task("arn:task/a")],
        "failures": [{"arn": "arn:task/b", "reason": "MISSING"}],
    }
    with pytest.raises(TaskEvidenceError):
        describe_tasks_with_evidence(ecs, s3, config, "run-1", ["arn:task/a", "arn:task/b"])
    assert read_terminal_task(s3, config, "run-1", "arn:task/a") is not None
