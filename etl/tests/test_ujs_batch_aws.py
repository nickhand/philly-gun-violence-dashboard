"""Tests for courts SQS/ECS batch orchestration helpers."""

import pytest

from etl.courts.batch.aws import launch_monitor, launch_workers, seed_queue
from etl.courts.config import SubmitterConfig


def _config() -> SubmitterConfig:
    return SubmitterConfig(
        s3_bucket="bucket",
        aws_account_id="123456789012",
        ecs_subnet_ids=["subnet-1"],
        ecs_security_group_ids=["sg-1"],
    )


class FakeSQS:
    """Minimal SQS fake for send_message_batch tests."""

    def __init__(self, failed_responses: int = 0) -> None:
        self.failed_responses = failed_responses
        self.calls = 0

    def send_message_batch(self, *, QueueUrl, Entries):
        self.calls += 1
        if self.calls <= self.failed_responses:
            return {
                "Successful": [],
                "Failed": [
                    {
                        "Id": entry["Id"],
                        "SenderFault": False,
                        "Code": "InternalError",
                        "Message": "temporary",
                    }
                    for entry in Entries
                ],
            }
        return {
            "Successful": [{"Id": entry["Id"], "MessageId": entry["Id"]} for entry in Entries],
            "Failed": [],
        }


class FakeECS:
    """Minimal ECS fake for run_task tests."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0
        self.requests = []

    def run_task(self, **kwargs):
        self.calls += 1
        self.requests.append(kwargs)
        if self.fail:
            return {"tasks": [], "failures": [{"reason": "RESOURCE:MEMORY"}]}
        return {"tasks": [{"taskArn": f"arn:task/{self.calls}"}], "failures": []}


def test_seed_queue_retries_failed_batch_entries() -> None:
    """SQS per-entry batch failures should be retried before counting messages sent."""
    sqs = FakeSQS(failed_responses=1)

    sent = seed_queue(sqs, _config(), ["1", "2"], "run-1")

    assert sent == 2
    assert sqs.calls == 2


def test_seed_queue_raises_after_repeated_batch_failures() -> None:
    """Persistent SQS per-entry failures should fail the submitter loudly."""
    sqs = FakeSQS(failed_responses=3)

    with pytest.raises(RuntimeError, match="SQS batch send failed"):
        seed_queue(sqs, _config(), ["1"], "run-1")


def test_launch_workers_raises_when_any_task_fails_to_start() -> None:
    """A seeded run should not look healthy if ECS cannot start the requested workers."""
    with pytest.raises(RuntimeError, match="Only launched 0/1"):
        launch_workers(FakeECS(fail=True), _config(), "run-1", worker_count=1)


def test_launch_monitor_overrides_worker_command(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ECS monitor task should run the coordinator command, not another worker."""
    ecs = FakeECS()
    config = _config()
    config.github_repository = "owner/repo"

    task_arn = launch_monitor(ecs, config, "run-1")

    assert task_arn == "arn:task/1"
    override = ecs.requests[0]["overrides"]["containerOverrides"][0]
    assert override["command"] == [
        "uv",
        "run",
        "gv-dashboard-etl",
        "courts",
        "monitor",
        "--run-id",
        "run-1",
    ]
    assert {"name": "GITHUB_REPOSITORY", "value": "owner/repo"} in override["environment"]
