"""Tests for courts SQS/ECS batch orchestration helpers."""

import json

import pytest
from aws_batch_scraper.aws import make_boto3_session
from aws_batch_scraper.cli import create_cli
from aws_batch_scraper.orchestrate import (
    WorkerLaunchError,
    launch_monitor,
    launch_workers,
    monitor_run,
)
from aws_batch_scraper.queue import seed_queue
from aws_batch_scraper.types import ScrapeResult, ScrapeStatus, WorkItem
from typer.testing import CliRunner

from etl.courts.config import CourtsSubmitterConfig


def _config() -> CourtsSubmitterConfig:
    return CourtsSubmitterConfig(
        _env_file=None,
        s3_bucket="bucket",
        aws_account_id="123456789012",
        ecs_subnet_ids=["subnet-1"],
        ecs_security_group_ids=["sg-1"],
    )


class FakeSQS:
    """Minimal SQS fake for send_message_batch tests."""

    def __init__(
        self,
        failed_responses: int = 0,
        *,
        visible: int = 0,
        in_flight: int = 0,
    ) -> None:
        self.failed_responses = failed_responses
        self.calls = 0
        self.visible = visible
        self.in_flight = in_flight

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

    def get_queue_attributes(self, *, QueueUrl, AttributeNames):
        attrs = {"ApproximateNumberOfMessages": str(self.visible)}
        if "ApproximateNumberOfMessagesNotVisible" in AttributeNames:
            attrs["ApproximateNumberOfMessagesNotVisible"] = str(self.in_flight)
        return {"Attributes": attrs}


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

    def describe_tasks(self, **kwargs):
        return {
            "tasks": [
                {
                    "taskArn": arn,
                    "lastStatus": "STOPPED",
                    "stopCode": "EssentialContainerExited",
                    "containers": [{"name": "worker", "essential": True, "exitCode": 0}],
                }
                for arn in kwargs["tasks"]
            ],
            "failures": [],
        }


class PartiallyFailingECS(FakeECS):
    """Launches the first task and fails later run_task calls."""

    def run_task(self, **kwargs):
        self.calls += 1
        self.requests.append(kwargs)
        if self.calls == 1:
            return {"tasks": [{"taskArn": "arn:task/1"}], "failures": []}
        return {"tasks": [], "failures": [{"reason": "RESOURCE:CPU"}]}


class FakeBody:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def read(self) -> bytes:
        return self.data


class FakeS3:
    def __init__(self) -> None:
        self.objects = {
            "ujs-scraper/runs/run-1/tasks.json": json.dumps({"task_arns": ["arn:task/1"]}).encode(),
            "ujs-scraper/runs/run-1/manifest.json": json.dumps(
                {"run_id": "run-1", "timestamp": "2026-05-24T00:00:00+00:00"}
            ).encode(),
        }
        self.puts = []

    def get_object(self, *, Bucket, Key):
        return {"Body": FakeBody(self.objects[Key])}

    def put_object(self, **kwargs):
        self.puts.append(kwargs)


class FakeSession:
    def __init__(self, *, s3=None, sqs=None, ecs=None) -> None:
        self.s3 = s3 or FakeS3()
        self.sqs = sqs or FakeSQS()
        self.ecs = ecs or FakeECS()

    def client(self, name: str):
        return {"s3": self.s3, "sqs": self.sqs, "ecs": self.ecs}[name]


def test_seed_queue_retries_failed_batch_entries() -> None:
    """SQS per-entry batch failures should be retried before counting messages sent."""
    sqs = FakeSQS(failed_responses=1)
    items = [WorkItem(item_id="1"), WorkItem(item_id="2")]

    sent = seed_queue(sqs, _config(), items, "run-1")

    assert sent == 2
    assert sqs.calls == 2


def test_seed_queue_raises_after_repeated_batch_failures() -> None:
    """Persistent SQS per-entry failures should fail the submitter loudly."""
    sqs = FakeSQS(failed_responses=3)

    with pytest.raises(RuntimeError, match="SQS batch send failed"):
        seed_queue(sqs, _config(), [WorkItem(item_id="1")], "run-1")


def test_launch_workers_raises_when_any_task_fails_to_start() -> None:
    """A seeded run should not look healthy if ECS cannot start the requested workers."""
    with pytest.raises(RuntimeError, match="Only launched 0/1"):
        launch_workers(FakeECS(fail=True), _config(), "run-1", worker_count=1)


def test_launch_workers_raises_on_partial_launch() -> None:
    """A run should fail fast if ECS starts fewer workers than requested."""
    with pytest.raises(WorkerLaunchError, match="Only launched 1/2") as exc_info:
        launch_workers(PartiallyFailingECS(), _config(), "run-1", worker_count=2)

    assert exc_info.value.launched_task_arns == ["arn:task/1"]
    assert exc_info.value.requested_count == 2


def test_submit_persists_partial_launch_task_arns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A partial launch failure should still leave monitor metadata in S3."""
    from aws_batch_scraper import aws, ids, orchestrate, queue

    fake_s3 = FakeS3()
    fake_session = FakeSession(s3=fake_s3)
    monkeypatch.setattr(aws, "make_boto3_session", lambda *, config=None: fake_session)
    monkeypatch.setattr(ids, "make_run_id", lambda: "run-1")
    monkeypatch.setattr(queue, "get_existing_items", lambda s3, config: set())
    monkeypatch.setattr(queue, "seed_queue", lambda sqs, config, items, run_id: len(items))

    def _partial_launch(*args, **kwargs):
        raise WorkerLaunchError(["arn:task/1"], 2)

    monkeypatch.setattr(orchestrate, "launch_workers", _partial_launch)

    class TestSubmitterConfig(CourtsSubmitterConfig):
        model_config = CourtsSubmitterConfig.model_config | {"env_file": None}

        s3_bucket: str = "bucket"
        aws_account_id: str = "123456789012"
        ecs_subnet_ids: list[str] = ["subnet-1"]
        ecs_security_group_ids: list[str] = ["sg-1"]

    app = create_cli(
        name="courts",
        script_name="gv-dashboard-etl",
        scraper_factory=lambda: None,  # not used by submit
        input_loader=lambda config: [WorkItem(item_id="1")],
        worker_config_class=TestSubmitterConfig,
        submitter_config_class=TestSubmitterConfig,
    )

    result = CliRunner().invoke(app, ["submit", "--workers", "2"])

    assert result.exit_code != 0
    tasks_puts = [put for put in fake_s3.puts if put["Key"] == "ujs-scraper/runs/run-1/tasks.json"]
    assert tasks_puts
    assert json.loads(tasks_puts[0]["Body"]) == {"task_arns": ["arn:task/1"]}


def test_launch_monitor_overrides_worker_command(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ECS monitor task should run the coordinator command, not another worker."""
    ecs = FakeECS()
    config = _config()
    config.github_repository = "owner/repo"
    monitor_cmd = ["uv", "run", "gv-dashboard-etl", "courts", "monitor", "--run-id", "run-1"]

    task_arn = launch_monitor(ecs, config, "run-1", monitor_cmd)

    assert task_arn == "arn:task/1"
    override = ecs.requests[0]["overrides"]["containerOverrides"][0]
    assert override["command"] == monitor_cmd
    assert {"name": "GITHUB_REPOSITORY", "value": "owner/repo"} in override["environment"]


def test_monitor_run_refuses_to_finalize_when_queue_not_empty() -> None:
    """Stopped ECS tasks are not enough if SQS still has visible work."""
    with pytest.raises(RuntimeError, match="queue is not empty"):
        monitor_run(
            FakeECS(),
            FakeSQS(visible=1),
            FakeS3(),
            _config(),
            "run-1",
            poll_interval=0,
        )


def test_scrape_result_accepts_legacy_courts_payload() -> None:
    """Old S3 result JSON should validate into the generic ScrapeResult model."""
    result = ScrapeResult.model_validate(
        {
            "status": "success",
            "results": [{"docket_number": "CP-51-CR-1"}],
            "incident_number": "240000000001",
            "classification": "HAS_RESULTS",
            "marker_hits": {"results_container": True},
        }
    )

    assert result.status == ScrapeStatus.SUCCESS
    assert result.item_id == "240000000001"
    assert result.data == {"results": [{"docket_number": "CP-51-CR-1"}]}
    assert result.extra == {"marker_hits": {"results_container": True}}


def test_boto_session_uses_resolved_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Boto clients should defer credentials to boto3's default chain."""
    calls = []

    class Session:
        region_name = "us-west-2"

        def __init__(self, **kwargs):
            calls.append(kwargs)

    import boto3

    monkeypatch.setattr(boto3, "Session", Session)

    config = CourtsSubmitterConfig(
        _env_file=None,
        s3_bucket="bucket",
        aws_account_id="123456789012",
        aws_profile="profile",
        aws_region="us-west-2",
        ecs_subnet_ids=["subnet-1"],
        ecs_security_group_ids=["sg-1"],
    )

    make_boto3_session(config=config)

    assert calls == [
        {
            "profile_name": "profile",
            "region_name": "us-west-2",
        }
    ]
