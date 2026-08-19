"""Tests for courts SQS/ECS batch orchestration helpers."""

import json

import pytest
from aws_batch_scraper.aws import make_boto3_session
from aws_batch_scraper.cli import create_cli
from aws_batch_scraper.orchestrate import (
    MonitorLaunchError,
    WorkerLaunchError,
    launch_monitor,
    launch_workers,
    monitor_run,
)
from aws_batch_scraper.queue import seed_queue
from aws_batch_scraper.types import ScrapeResult, ScrapeStatus, WorkItem
from typer.testing import CliRunner

from etl.courts.config import CourtsSubmitterConfig

IMAGE_URI = "123456789012.dkr.ecr.us-east-1.amazonaws.com/ujs-scraper@sha256:" + "a" * 64


def _config() -> CourtsSubmitterConfig:
    return CourtsSubmitterConfig(
        _env_file=None,
        s3_bucket="bucket",
        aws_account_id="123456789012",
        ecs_task_definition="ujs-scraper:1",
        ecs_monitor_task_definition="ujs-scraper-monitor:2",
        ecs_expected_image_uri=IMAGE_URI,
        github_repository="owner/repository",
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
        delayed: int = 0,
    ) -> None:
        self.failed_responses = failed_responses
        self.calls = 0
        self.visible = visible
        self.in_flight = in_flight
        self.delayed = delayed

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
        if "ApproximateNumberOfMessagesDelayed" in AttributeNames:
            attrs["ApproximateNumberOfMessagesDelayed"] = str(self.delayed)
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
        count = kwargs.get("count", 1)
        return {
            "tasks": [{"taskArn": f"arn:task/{index + 1}"} for index in range(count)],
            "failures": [],
        }

    def describe_task_definition(self, *, taskDefinition):
        is_monitor = "monitor" in taskDefinition
        arn = (
            taskDefinition
            if taskDefinition.startswith("arn:")
            else (f"arn:aws:ecs:us-east-1:123456789012:task-definition/{taskDefinition}")
        )
        container = {
            "name": "ujs-scraper",
            "image": IMAGE_URI,
            "secrets": (
                [
                    {
                        "name": "GITHUB_DISPATCH_TOKEN",
                        "valueFrom": "arn:aws:secretsmanager:token",
                    }
                ]
                if is_monitor
                else []
            ),
            "environment": [],
            "user": "app",
            "readonlyRootFilesystem": True,
            "privileged": False,
            "mountPoints": [
                {
                    "sourceVolume": "tmp",
                    "containerPath": "/tmp",
                    "readOnly": False,
                }
            ],
        }
        return {
            "taskDefinition": {
                "taskDefinitionArn": arn,
                "status": "ACTIVE",
                "requiresCompatibilities": ["FARGATE"],
                "networkMode": "awsvpc",
                "runtimePlatform": {
                    "operatingSystemFamily": "LINUX",
                    "cpuArchitecture": "X86_64",
                },
                "volumes": [{"name": "tmp"}],
                "containerDefinitions": [container],
            }
        }

    def describe_clusters(self, *, clusters):
        return {
            "clusters": [
                {
                    "clusterArn": "arn:aws:ecs:us-east-1:123456789012:cluster/ujs-scraper",
                    "status": "ACTIVE",
                }
            ],
            "failures": [],
        }

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
    """Returns one accepted task and one definitive capacity failure."""

    def run_task(self, **kwargs):
        self.calls += 1
        self.requests.append(kwargs)
        return {
            "tasks": [{"taskArn": "arn:task/1"}],
            "failures": [{"reason": "RESOURCE:CPU"}],
        }


class PartiallyThrowingECS(FakeECS):
    """Loses every response to the same idempotent RunTask request."""

    def run_task(self, **kwargs):
        self.calls += 1
        self.requests.append(kwargs)
        raise TimeoutError("ECS request timed out")


class DuplicateTaskECS(FakeECS):
    """Returns an invalid response that repeats one task ARN."""

    def run_task(self, **kwargs):
        self.calls += 1
        self.requests.append(kwargs)
        return {
            "tasks": [{"taskArn": "arn:task/1"}, {"taskArn": "arn:task/1"}],
            "failures": [],
        }


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
    with pytest.raises(RuntimeError, match="only confirmed 0/1"):
        launch_workers(FakeECS(fail=True), _config(), "run-1", worker_count=1)


def test_launch_workers_raises_on_partial_launch() -> None:
    """A run should fail fast if ECS starts fewer workers than requested."""
    with pytest.raises(WorkerLaunchError, match="only confirmed 1/2") as exc_info:
        launch_workers(PartiallyFailingECS(), _config(), "run-1", worker_count=2)

    assert exc_info.value.launched_task_arns == ["arn:task/1"]
    assert exc_info.value.requested_count == 2


def test_workers_launch_in_one_idempotent_request() -> None:
    """One stable token owns the complete requested worker set."""
    ecs = FakeECS()

    launch_workers(ecs, _config(), "run-1", worker_count=2)

    assert len(ecs.requests) == 1
    assert ecs.requests[0]["count"] == 2
    assert ecs.requests[0]["taskDefinition"] == "ujs-scraper:1"
    assert ecs.requests[0]["taskDefinition"] != "ujs-scraper-monitor:2"
    assert ecs.requests[0]["clientToken"].startswith("gv-worker-")


def test_launch_workers_marks_exhausted_transport_error_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lost response is not evidence that ECS started zero tasks."""
    from aws_batch_scraper import orchestrate

    monkeypatch.setattr(orchestrate.time, "sleep", lambda _seconds: None)
    ecs = PartiallyThrowingECS()

    with pytest.raises(WorkerLaunchError, match="outcome is unknown") as exc_info:
        launch_workers(ecs, _config(), "run-1", worker_count=2)

    assert exc_info.value.launched_task_arns == []
    assert exc_info.value.launch_ambiguous is True
    assert len({request["clientToken"] for request in ecs.requests}) == 1
    assert isinstance(exc_info.value.__cause__, TimeoutError)


def test_launch_workers_rejects_duplicate_task_identity_as_ambiguous() -> None:
    with pytest.raises(WorkerLaunchError) as exc_info:
        launch_workers(DuplicateTaskECS(), _config(), "run-1", worker_count=2)

    assert exc_info.value.launch_ambiguous is True


def test_submit_persists_partial_launch_task_arns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A partial launch failure should persist tasks and hand off lease cleanup."""
    from aws_batch_scraper import aws, ids, lease, orchestrate, queue

    fake_s3 = FakeS3()
    fake_session = FakeSession(s3=fake_s3)
    monkeypatch.setattr(aws, "make_boto3_session", lambda *, config=None: fake_session)
    monkeypatch.setattr(ids, "make_run_id", lambda: "run-1")
    monkeypatch.setattr(queue, "get_existing_items", lambda s3, config: set())
    monkeypatch.setattr(
        queue,
        "seed_queue",
        lambda sqs, config, items, run_id, **kwargs: len(items),
    )

    def _partial_launch(*args, **kwargs):
        raise WorkerLaunchError(["arn:task/1"], 2)

    monkeypatch.setattr(orchestrate, "launch_workers", _partial_launch)
    release_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        lease,
        "release_run_lease",
        lambda *args, **kwargs: release_calls.append(kwargs) or True,
    )

    class TestSubmitterConfig(CourtsSubmitterConfig):
        model_config = CourtsSubmitterConfig.model_config | {"env_file": None}

        s3_bucket: str = "bucket"
        aws_account_id: str = "123456789012"
        ecs_task_definition: str = "ujs-scraper:42"
        ecs_monitor_task_definition: str = "ujs-scraper-monitor:17"
        ecs_expected_image_uri: str = IMAGE_URI
        github_repository: str = "owner/repository"
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

    result = CliRunner().invoke(app, ["submit", "--workers", "2", "--monitor-in-ecs"])

    assert result.exit_code != 0
    tasks_puts = [put for put in fake_s3.puts if put["Key"] == "ujs-scraper/runs/run-1/tasks.json"]
    assert tasks_puts
    assert json.loads(tasks_puts[0]["Body"]) == {"task_arns": ["arn:task/1"]}
    assert fake_session.ecs.requests
    override = fake_session.ecs.requests[0]["overrides"]["containerOverrides"][0]
    assert override["command"] == [
        "gv-dashboard-etl",
        "courts",
        "monitor",
        "--run-id",
        "run-1",
    ]
    assert release_calls == []


def test_launch_monitor_overrides_worker_command(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ECS monitor task should run the coordinator command, not another worker."""
    ecs = FakeECS()
    config = _config()
    config.github_repository = "owner/repo"
    monitor_cmd = ["gv-dashboard-etl", "courts", "monitor", "--run-id", "run-1"]

    task_arn = launch_monitor(ecs, config, "run-1", monitor_cmd)

    assert task_arn == "arn:task/1"
    override = ecs.requests[0]["overrides"]["containerOverrides"][0]
    assert override["command"] == monitor_cmd
    assert {"name": "GITHUB_REPOSITORY", "value": "owner/repo"} in override["environment"]
    assert {"name": "GITHUB_WORKFLOW_FILE", "value": "courts-process.yml"} in override[
        "environment"
    ]
    assert ecs.requests[0]["taskDefinition"] == "ujs-scraper-monitor:2"
    assert ecs.requests[0]["taskDefinition"] != "ujs-scraper:1"
    assert ecs.requests[0]["clientToken"].startswith("gv-monitor-")
    monitor_environment = {entry["name"]: entry["value"] for entry in override["environment"]}
    assert monitor_environment["ECS_CLUSTER_NAME"] == "ujs-scraper"
    assert monitor_environment["ECS_TASK_DEFINITION"] == "ujs-scraper:1"
    assert monitor_environment["ECS_MONITOR_TASK_DEFINITION"] == "ujs-scraper-monitor:2"
    assert monitor_environment["ECS_EXPECTED_IMAGE_URI"] == IMAGE_URI
    assert monitor_environment["ECS_CONTAINER_NAME"] == "ujs-scraper"

    for name, value in monitor_environment.items():
        monkeypatch.setenv(name, value)
    launched_config = CourtsSubmitterConfig(_env_file=None)
    assert launched_config.ecs_task_definition == "ujs-scraper:1"
    assert launched_config.ecs_monitor_task_definition == "ujs-scraper-monitor:2"


def test_launch_monitor_rejects_definitive_zero_task_response() -> None:
    with pytest.raises(MonitorLaunchError, match="confirmed no monitor task") as exc_info:
        launch_monitor(FakeECS(fail=True), _config(), "run-1", ["monitor"])

    assert exc_info.value.launch_ambiguous is False


def test_launch_monitor_rejects_malformed_task_identity_as_ambiguous() -> None:
    class MalformedMonitorECS(FakeECS):
        def run_task(self, **kwargs):
            self.requests.append(kwargs)
            return {"tasks": [{"taskArn": "not-an-arn"}], "failures": []}

    with pytest.raises(MonitorLaunchError, match="outcome is unknown") as exc_info:
        launch_monitor(MalformedMonitorECS(), _config(), "run-1", ["monitor"])

    assert exc_info.value.launch_ambiguous is True


def test_launch_monitor_marks_exhausted_transport_error_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aws_batch_scraper import orchestrate

    monkeypatch.setattr(orchestrate.time, "sleep", lambda _seconds: None)
    ecs = PartiallyThrowingECS()

    with pytest.raises(MonitorLaunchError, match="outcome is unknown") as exc_info:
        launch_monitor(ecs, _config(), "run-1", ["monitor"])

    assert exc_info.value.launch_ambiguous is True
    assert len(ecs.requests) == 4
    assert len({request["clientToken"] for request in ecs.requests}) == 1


def test_monitor_run_refuses_to_finalize_when_queue_not_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stopped ECS tasks are not enough if SQS still has visible work."""
    from aws_batch_scraper import orchestrate

    releases: list[dict[str, object]] = []
    monkeypatch.setattr(orchestrate, "renew_run_lease", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        orchestrate,
        "release_run_lease",
        lambda *args, **kwargs: releases.append(kwargs) or True,
    )
    s3 = FakeS3()
    with pytest.raises(RuntimeError, match="queue is not empty"):
        monitor_run(
            FakeECS(),
            FakeSQS(visible=1),
            s3,
            _config(),
            "run-1",
            poll_interval=0,
        )

    assert releases == []
    evidence = [
        put for put in s3.puts if put["Key"] == "ujs-scraper/runs/run-1/monitor-recovery.json"
    ]
    assert len(evidence) == 1
    assert json.loads(evidence[0]["Body"])["lease_action"] == "retained"


def test_monitor_run_requires_zero_delayed_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A delayed retry is owned work even when visible and in-flight are zero."""
    from aws_batch_scraper import orchestrate

    s3 = FakeS3()
    releases: list[dict[str, object]] = []
    monkeypatch.setattr(orchestrate, "renew_run_lease", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        orchestrate,
        "release_run_lease",
        lambda *args, **kwargs: releases.append(kwargs) or True,
    )

    with pytest.raises(RuntimeError, match="1 delayed"):
        monitor_run(
            FakeECS(),
            FakeSQS(delayed=1),
            s3,
            _config(),
            "run-1",
            poll_interval=0,
        )

    assert releases == []
    assert any(put["Key"] == "ujs-scraper/runs/run-1/monitor-recovery.json" for put in s3.puts)


def test_monitor_rejects_stopped_task_without_container_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """STOPPED is not success unless the essential container reports exit zero."""
    from aws_batch_scraper import orchestrate

    class MissingExitCodeECS(FakeECS):
        def describe_tasks(self, **kwargs):
            return {
                "tasks": [
                    {
                        "taskArn": arn,
                        "lastStatus": "STOPPED",
                        "stopCode": "EssentialContainerExited",
                        "containers": [{"name": "worker", "essential": True}],
                    }
                    for arn in kwargs["tasks"]
                ],
                "failures": [],
            }

    releases: list[dict[str, object]] = []
    monkeypatch.setattr(orchestrate, "renew_run_lease", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        orchestrate,
        "release_run_lease",
        lambda *args, **kwargs: releases.append(kwargs) or True,
    )

    with pytest.raises(RuntimeError, match="missing exitCode"):
        monitor_run(
            MissingExitCodeECS(),
            FakeSQS(),
            FakeS3(),
            _config(),
            "run-1",
            poll_interval=0,
        )

    assert releases[0]["terminal_status"] == "failure"


def test_monitor_keeps_lease_when_task_manifest_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An observability failure is not evidence that live workers are terminal."""
    from aws_batch_scraper import orchestrate
    from botocore.exceptions import ClientError

    class ForbiddenS3:
        def get_object(self, **kwargs):
            raise ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "denied"}},
                "GetObject",
            )

    releases: list[dict[str, object]] = []
    monkeypatch.setattr(
        orchestrate,
        "release_run_lease",
        lambda *args, **kwargs: releases.append(kwargs) or True,
    )

    with pytest.raises(ClientError):
        monitor_run(
            FakeECS(),
            FakeSQS(),
            ForbiddenS3(),  # ty: ignore[invalid-argument-type]
            _config(),
            "run-1",
            poll_interval=0,
        )

    assert releases == []


def test_monitor_does_not_finalize_missing_task_manifest_from_queue_depth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty queue cannot prove that this run's worker tasks have stopped."""
    from aws_batch_scraper import orchestrate
    from botocore.exceptions import ClientError

    class MissingTasksS3:
        def get_object(self, **kwargs):
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "missing"}},
                "GetObject",
            )

    releases: list[dict[str, object]] = []
    dispatches: list[str] = []
    monkeypatch.setattr(
        orchestrate,
        "release_run_lease",
        lambda *args, **kwargs: releases.append(kwargs) or True,
    )
    monkeypatch.setattr(
        orchestrate,
        "dispatch_workflow",
        lambda run_id, **kwargs: dispatches.append(run_id),
    )

    with pytest.raises(FileNotFoundError, match="Task manifest"):
        monitor_run(
            FakeECS(),
            FakeSQS(visible=0, in_flight=0),
            MissingTasksS3(),  # ty: ignore[invalid-argument-type]
            _config(),
            "run-1",
            poll_interval=0,
        )

    assert dispatches == []
    assert releases == []


def test_monitor_keeps_lease_when_ecs_state_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Transient ECS inspection errors must fail closed against overlap."""
    from aws_batch_scraper import orchestrate

    class FailingDescribeECS(FakeECS):
        def describe_tasks(self, **kwargs):
            raise TimeoutError("ECS unavailable")

    releases: list[dict[str, object]] = []
    monkeypatch.setattr(orchestrate, "renew_run_lease", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        orchestrate,
        "release_run_lease",
        lambda *args, **kwargs: releases.append(kwargs) or True,
    )

    with pytest.raises(TimeoutError, match="ECS unavailable"):
        monitor_run(
            FailingDescribeECS(),
            FakeSQS(),
            FakeS3(),
            _config(),
            "run-1",
            poll_interval=0,
        )

    assert releases == []


def test_monitor_marks_lease_failed_when_completion_dispatch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed required dispatch must be a terminal monitored-run failure."""
    from aws_batch_scraper import orchestrate
    from aws_batch_scraper.dispatch import WorkflowDispatchRejectedError

    releases: list[dict[str, object]] = []
    monkeypatch.setattr(orchestrate, "renew_run_lease", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        orchestrate,
        "release_run_lease",
        lambda *args, **kwargs: releases.append(kwargs) or True,
    )
    monkeypatch.setattr(
        orchestrate,
        "dispatch_workflow",
        lambda run_id, **kwargs: (_ for _ in ()).throw(
            WorkflowDispatchRejectedError("dispatch failed")
        ),
    )

    s3 = FakeS3()
    with pytest.raises(WorkflowDispatchRejectedError, match="dispatch failed"):
        monitor_run(
            FakeECS(),
            FakeSQS(),
            s3,
            _config(),
            "run-1",
            poll_interval=0,
        )

    assert releases == [
        {
            "terminal_status": "failure",
            "detail": "dispatch failed",
        }
    ]
    completed_manifest = json.loads(
        next(put["Body"] for put in s3.puts if put["Key"] == "ujs-scraper/runs/run-1/manifest.json")
    )
    assert completed_manifest["terminal_queue_counts"] == {
        "visible": 0,
        "in_flight": 0,
        "delayed": 0,
    }


def test_monitor_retains_lease_when_dispatch_delivery_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A process workflow may already be running after a lost HTTP response."""
    from aws_batch_scraper import orchestrate
    from aws_batch_scraper.dispatch import WorkflowDispatchDeliveryUnknownError

    s3 = FakeS3()
    releases: list[dict[str, object]] = []
    monkeypatch.setattr(orchestrate, "renew_run_lease", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        orchestrate,
        "release_run_lease",
        lambda *args, **kwargs: releases.append(kwargs) or True,
    )
    monkeypatch.setattr(
        orchestrate,
        "dispatch_workflow",
        lambda run_id, **kwargs: (_ for _ in ()).throw(
            WorkflowDispatchDeliveryUnknownError("delivery unknown")
        ),
    )

    with pytest.raises(WorkflowDispatchDeliveryUnknownError, match="delivery unknown"):
        monitor_run(
            FakeECS(),
            FakeSQS(),
            s3,
            _config(),
            "run-1",
            poll_interval=0,
        )

    assert releases == []
    evidence = [
        put for put in s3.puts if put["Key"] == "ujs-scraper/runs/run-1/dispatch-ambiguous.json"
    ]
    assert len(evidence) == 1
    assert json.loads(evidence[0]["Body"])["lease_action"] == "retained"


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
        ecs_task_definition="ujs-scraper:1",
        ecs_monitor_task_definition="ujs-scraper-monitor:2",
        ecs_expected_image_uri=(
            "123456789012.dkr.ecr.us-west-2.amazonaws.com/ujs-scraper@sha256:" + "a" * 64
        ),
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


def test_courts_process_preserves_pipeline_error_when_lease_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Best-effort terminal cleanup must not replace the processing traceback."""
    from aws_batch_scraper import aggregate, lease

    from etl.courts import cli, pipeline

    config = _config()
    config.run_id = "run-1"
    session = FakeSession()
    monkeypatch.setattr(cli, "CourtsWorkerConfig", lambda: config)
    monkeypatch.setattr(cli, "make_boto3_session", lambda *, config=None: session)
    pipeline_error = RuntimeError("aggregation failed")
    monkeypatch.setattr(
        pipeline,
        "process_results",
        lambda *args, **kwargs: (_ for _ in ()).throw(pipeline_error),
    )
    monkeypatch.setattr(
        aggregate,
        "read_run_items",
        lambda *args, **kwargs: [WorkItem(item_id="100")],
    )
    monkeypatch.setattr(
        lease,
        "claim_run_lease_for_processing",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        lease,
        "release_run_lease",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("cleanup failed")),
    )

    with pytest.raises(RuntimeError) as exc_info:
        cli.process()

    assert exc_info.value is pipeline_error


def test_courts_process_rejects_success_without_lease_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A success response is not terminal until the owned lease is released."""
    from aws_batch_scraper import aggregate, lease

    from etl.courts import cli, pipeline

    config = _config()
    config.run_id = "run-1"
    session = FakeSession()
    monkeypatch.setattr(cli, "CourtsWorkerConfig", lambda: config)
    monkeypatch.setattr(cli, "make_boto3_session", lambda *, config=None: session)
    monkeypatch.setattr(pipeline, "process_results", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        aggregate,
        "read_run_items",
        lambda *args, **kwargs: [WorkItem(item_id="100")],
    )
    claimed_owners: list[str] = []
    monkeypatch.setattr(
        lease,
        "claim_run_lease_for_processing",
        lambda *args, **kwargs: claimed_owners.append(args[3]),
    )

    def reject_release(*args, **kwargs):
        assert kwargs["owner"] == claimed_owners[0]
        return False

    monkeypatch.setattr(lease, "release_run_lease", reject_release)

    with pytest.raises(RuntimeError, match="did not own its lease"):
        cli.process()

    assert len(claimed_owners) == 1
    assert claimed_owners[0].startswith("process:")


def test_courts_process_requires_concrete_run_id_before_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from etl.courts import cli, pipeline

    config = _config()
    config.run_id = "unknown"
    called: list[object] = []
    monkeypatch.setattr(cli, "CourtsWorkerConfig", lambda: config)
    monkeypatch.setattr(cli, "make_boto3_session", lambda *, config=None: FakeSession())
    monkeypatch.setattr(
        pipeline,
        "process_results",
        lambda *args, **kwargs: called.append(args),
    )

    with pytest.raises(Exception, match="concrete RUN_ID"):
        cli.process()

    assert called == []


def test_courts_process_claims_lease_before_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aws_batch_scraper import aggregate, lease
    from aws_batch_scraper.lease import RunLeaseConflict

    from etl.courts import cli, pipeline

    config = _config()
    config.run_id = "run-old"
    called: list[object] = []
    monkeypatch.setattr(cli, "CourtsWorkerConfig", lambda: config)
    monkeypatch.setattr(cli, "make_boto3_session", lambda *, config=None: FakeSession())
    monkeypatch.setattr(
        aggregate,
        "read_run_items",
        lambda *args, **kwargs: [WorkItem(item_id="100")],
    )
    monkeypatch.setattr(
        lease,
        "claim_run_lease_for_processing",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RunLeaseConflict("replacement run owns lease")
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "process_results",
        lambda *args, **kwargs: called.append(args),
    )

    with pytest.raises(RunLeaseConflict, match="replacement run"):
        cli.process()

    assert called == []


def test_early_courts_process_does_not_release_live_run_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An incomplete manifest is not a terminal run-processing failure."""
    from aws_batch_scraper import aggregate, lease

    from etl.courts import cli, pipeline

    config = _config()
    config.run_id = "run-live"
    calls: list[str] = []
    monkeypatch.setattr(cli, "CourtsWorkerConfig", lambda: config)
    monkeypatch.setattr(cli, "make_boto3_session", lambda *, config=None: FakeSession())
    monkeypatch.setattr(
        aggregate,
        "read_run_items",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("run is not completed")),
    )
    monkeypatch.setattr(
        lease,
        "claim_run_lease_for_processing",
        lambda *args, **kwargs: calls.append("claim"),
    )
    monkeypatch.setattr(
        lease,
        "release_run_lease",
        lambda *args, **kwargs: calls.append("release"),
    )
    monkeypatch.setattr(
        pipeline,
        "process_results",
        lambda *args, **kwargs: calls.append("pipeline"),
    )

    with pytest.raises(ValueError, match="not completed"):
        cli.process()

    assert calls == []
