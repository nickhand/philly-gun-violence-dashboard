"""Tests for optimization-safe CLI run selection."""

import json
from unittest.mock import MagicMock

import pytest
import typer
from aws_batch_scraper.cli import (
    _monitor_command,
    _record_submission_recovery,
    _resolve_run_id,
    _SubmitPhase,
    create_cli,
)
from aws_batch_scraper.config import SubmitterConfig
from aws_batch_scraper.types import WorkItem
from click.utils import strip_ansi
from typer.testing import CliRunner

IMAGE_URI = "123456789012.dkr.ecr.us-east-1.amazonaws.com/ujs-scraper@sha256:" + "a" * 64


class _SubmitConfig(SubmitterConfig):
    model_config = SubmitterConfig.model_config | {"env_file": None}

    s3_bucket: str = "bucket"
    s3_scraper_prefix: str = "scraper"
    aws_account_id: str = "123456789012"
    sqs_queue_name: str = "queue"
    sqs_dlq_name: str = "queue-dlq"
    ecs_cluster_name: str = "cluster"
    ecs_task_definition: str = "task-definition:1"
    ecs_monitor_task_definition: str = "monitor-task-definition:1"
    ecs_expected_image_uri: str = IMAGE_URI
    github_repository: str = "owner/repository"
    github_workflow_file: str = "process.yml"
    ecs_container_name: str = "worker"
    ecs_subnet_ids: list[str] = ["subnet-1"]
    ecs_security_group_ids: list[str] = ["sg-1"]


def _submit_app(
    config_class: type[SubmitterConfig] = _SubmitConfig,
) -> typer.Typer:
    return create_cli(
        name="test",
        script_name="test-etl",
        scraper_factory=MagicMock(),
        input_loader=lambda _config: [WorkItem(item_id="item-1")],
        worker_config_class=config_class,
        submitter_config_class=config_class,
    )


def _patch_submit_session(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    from aws_batch_scraper import aws, queue

    session = MagicMock()
    clients = {name: MagicMock(name=name) for name in ("s3", "sqs", "ecs")}
    clients["ecs"].describe_clusters.return_value = {
        "clusters": [
            {
                "clusterArn": "arn:aws:ecs:us-east-1:123456789012:cluster/cluster",
                "status": "ACTIVE",
            }
        ],
        "failures": [],
    }
    clients["ecs"].describe_task_definition.side_effect = [
        {
            "taskDefinition": {
                "taskDefinitionArn": (
                    "arn:aws:ecs:us-east-1:123456789012:task-definition/task-definition:1"
                ),
                "status": "ACTIVE",
                "requiresCompatibilities": ["FARGATE"],
                "networkMode": "awsvpc",
                "runtimePlatform": {
                    "operatingSystemFamily": "LINUX",
                    "cpuArchitecture": "X86_64",
                },
                "volumes": [{"name": "tmp"}],
                "containerDefinitions": [
                    {
                        "name": "worker",
                        "image": IMAGE_URI,
                        "secrets": [],
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
                ],
            }
        },
        {
            "taskDefinition": {
                "taskDefinitionArn": (
                    "arn:aws:ecs:us-east-1:123456789012:task-definition/monitor-task-definition:1"
                ),
                "status": "ACTIVE",
                "requiresCompatibilities": ["FARGATE"],
                "networkMode": "awsvpc",
                "runtimePlatform": {
                    "operatingSystemFamily": "LINUX",
                    "cpuArchitecture": "X86_64",
                },
                "volumes": [{"name": "tmp"}],
                "containerDefinitions": [
                    {
                        "name": "worker",
                        "image": IMAGE_URI,
                        "secrets": [
                            {
                                "name": "GITHUB_DISPATCH_TOKEN",
                                "valueFrom": "arn:aws:secretsmanager:token",
                            }
                        ],
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
                ],
            }
        },
    ]
    session.client.side_effect = clients.__getitem__
    monkeypatch.setattr(aws, "make_boto3_session", lambda *, config=None: session)
    monkeypatch.setattr(queue, "get_existing_items", lambda s3, config: set())
    return session


def test_monitor_command_uses_installed_console_script_directly() -> None:
    assert _monitor_command("test-etl", "test", "run-1") == [
        "test-etl",
        "test",
        "monitor",
        "--run-id",
        "run-1",
    ]


def test_submit_definition_preflight_happens_before_durable_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aws_batch_scraper import lease

    session = _patch_submit_session(monkeypatch)
    preflight_error = RuntimeError("DescribeTaskDefinition denied")
    session.client("ecs").describe_task_definition.side_effect = preflight_error
    acquire = MagicMock()
    monkeypatch.setattr(lease, "acquire_run_lease", acquire)

    result = CliRunner().invoke(_submit_app(), ["submit", "--monitor-in-ecs"])

    assert result.exit_code != 0
    assert result.exception is preflight_error
    acquire.assert_not_called()


def test_resolve_run_id_returns_explicit_value() -> None:
    assert _resolve_run_id("run-1", False, MagicMock(), MagicMock()) == "run-1"


def test_resolve_run_id_rejects_missing_selection() -> None:
    with pytest.raises(typer.BadParameter, match="Provide a run ID"):
        _resolve_run_id(None, False, MagicMock(), MagicMock())


def test_resolve_run_id_rejects_conflicting_selection() -> None:
    with pytest.raises(typer.BadParameter, match="both"):
        _resolve_run_id("run-1", True, MagicMock(), MagicMock())


def test_manual_run_monitor_requires_dispatch_repository_before_polling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aws_batch_scraper import orchestrate

    class MissingRepositoryConfig(_SubmitConfig):
        github_repository: str | None = None

    # GitHub Actions injects this variable into every step. This test exercises
    # the missing-setting boundary, so it must not inherit the runner context.
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    _patch_submit_session(monkeypatch)
    monitor_run = MagicMock()
    monkeypatch.setattr(orchestrate, "monitor_run", monitor_run)

    result = CliRunner().invoke(
        _submit_app(MissingRepositoryConfig),
        ["monitor", "--run-id", "run-1"],
    )

    assert result.exit_code != 0
    assert "GITHUB_REPOSITORY" in str(result.exception)
    monitor_run.assert_not_called()


def test_manual_run_monitor_requires_dispatch_workflow_before_polling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aws_batch_scraper import orchestrate

    class MissingWorkflowConfig(_SubmitConfig):
        github_workflow_file: str | None = None

    _patch_submit_session(monkeypatch)
    monitor_run = MagicMock()
    monkeypatch.setattr(orchestrate, "monitor_run", monitor_run)

    result = CliRunner().invoke(
        _submit_app(MissingWorkflowConfig),
        ["monitor", "--run-id", "run-1"],
    )

    assert result.exit_code != 0
    assert "GITHUB_WORKFLOW_FILE" in str(result.exception)
    monitor_run.assert_not_called()


def test_submit_requires_dispatch_workflow_before_durable_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aws_batch_scraper import lease

    class MissingWorkflowConfig(_SubmitConfig):
        github_workflow_file: str | None = None

    _patch_submit_session(monkeypatch)
    acquire = MagicMock()
    monkeypatch.setattr(lease, "acquire_run_lease", acquire)

    result = CliRunner().invoke(
        _submit_app(MissingWorkflowConfig),
        ["submit", "--monitor-in-ecs"],
    )

    assert result.exit_code != 0
    assert "GITHUB_WORKFLOW_FILE" in str(result.exception)
    acquire.assert_not_called()


def test_submit_dry_run_has_no_aws_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    """Preview mode must stop before the lease, queue, manifest, or ECS mutate."""
    from aws_batch_scraper import ids, lease, orchestrate, queue

    _patch_submit_session(monkeypatch)
    monkeypatch.setattr(ids, "make_run_id", lambda: "run-1")
    acquire = MagicMock()
    seed = MagicMock()
    manifest = MagicMock()
    launch = MagicMock()
    monkeypatch.setattr(lease, "acquire_run_lease", acquire)
    monkeypatch.setattr(queue, "seed_queue", seed)
    monkeypatch.setattr(orchestrate, "write_run_manifest", manifest)
    monkeypatch.setattr(orchestrate, "launch_workers", launch)

    result = CliRunner().invoke(_submit_app(), ["submit", "--dry-run"])

    assert result.exit_code == 0, result.output
    acquire.assert_not_called()
    seed.assert_not_called()
    manifest.assert_not_called()
    launch.assert_not_called()


def test_submit_seed_failure_retains_lease_after_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SQS transport failure may follow partial delivery, so it is recoverable."""
    from aws_batch_scraper import cli, ids, lease, orchestrate, queue

    _patch_submit_session(monkeypatch)
    monkeypatch.setattr(ids, "make_run_id", lambda: "run-1")
    monkeypatch.setattr(lease, "acquire_run_lease", lambda *args, **kwargs: None)
    calls: list[str] = []
    monkeypatch.setattr(
        orchestrate,
        "write_run_manifest",
        lambda *args, **kwargs: calls.append("manifest"),
    )
    seed_error = RuntimeError("seed failed")

    def fail_seed(*args, **kwargs):
        calls.append("seed")
        raise seed_error

    monkeypatch.setattr(
        queue,
        "seed_queue",
        fail_seed,
    )
    release = MagicMock()
    evidence = MagicMock()
    monkeypatch.setattr(lease, "release_run_lease", release)
    monkeypatch.setattr(cli, "_record_submission_recovery", evidence)

    result = CliRunner().invoke(_submit_app(), ["submit", "--monitor-in-ecs"])

    assert result.exit_code != 0
    assert result.exception is seed_error
    assert calls == ["manifest", "seed"]
    release.assert_not_called()
    assert evidence.call_args.args[3] is _SubmitPhase.QUEUE_SEED_STARTED


def test_submit_manifest_failure_prevents_seed_and_retains_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An interrupted multi-object manifest write is recoverable, not terminal."""
    from aws_batch_scraper import cli, ids, lease, orchestrate, queue

    _patch_submit_session(monkeypatch)
    monkeypatch.setattr(ids, "make_run_id", lambda: "run-1")
    monkeypatch.setattr(lease, "acquire_run_lease", lambda *args, **kwargs: None)
    seed = MagicMock(return_value=1)
    monkeypatch.setattr(queue, "seed_queue", seed)
    manifest_error = RuntimeError("manifest failed")
    monkeypatch.setattr(
        orchestrate,
        "write_run_manifest",
        lambda *args, **kwargs: (_ for _ in ()).throw(manifest_error),
    )
    release = MagicMock()
    evidence = MagicMock()
    monkeypatch.setattr(lease, "release_run_lease", release)
    monkeypatch.setattr(cli, "_record_submission_recovery", evidence)

    result = CliRunner().invoke(_submit_app(), ["submit", "--monitor-in-ecs"])

    assert result.exit_code != 0
    assert result.exception is manifest_error
    seed.assert_not_called()
    release.assert_not_called()
    assert evidence.call_args.args[3] is _SubmitPhase.MANIFEST_WRITE_STARTED


def test_submit_partial_seed_count_retains_lease_without_launching_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A short SQS send count is orphan work until an operator recovers it."""
    from aws_batch_scraper import cli, ids, lease, orchestrate, queue

    _patch_submit_session(monkeypatch)
    monkeypatch.setattr(ids, "make_run_id", lambda: "run-1")
    monkeypatch.setattr(lease, "acquire_run_lease", lambda *args, **kwargs: None)
    monkeypatch.setattr(orchestrate, "write_run_manifest", lambda *args, **kwargs: None)
    monkeypatch.setattr(queue, "seed_queue", lambda *args, **kwargs: 0)
    launch = MagicMock()
    evidence = MagicMock()
    release = MagicMock()
    monkeypatch.setattr(orchestrate, "launch_workers", launch)
    monkeypatch.setattr(cli, "_record_submission_recovery", evidence)
    monkeypatch.setattr(lease, "release_run_lease", release)

    result = CliRunner().invoke(_submit_app(), ["submit", "--monitor-in-ecs"])

    assert result.exit_code != 0
    assert "accepted only 0/1" in str(result.exception)
    launch.assert_not_called()
    release.assert_not_called()
    assert evidence.call_args.args[3] is _SubmitPhase.QUEUE_SEED_STARTED


def test_submit_monitor_failure_keeps_live_worker_lease_for_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A live worker must never be made overlap-safe merely by releasing its lease."""
    from aws_batch_scraper import ids, lease, orchestrate, queue

    _patch_submit_session(monkeypatch)
    monkeypatch.setattr(ids, "make_run_id", lambda: "run-1")
    monkeypatch.setattr(lease, "acquire_run_lease", lambda *args, **kwargs: None)
    monkeypatch.setattr(queue, "seed_queue", lambda *args, **kwargs: 1)
    monkeypatch.setattr(orchestrate, "write_run_manifest", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        orchestrate,
        "launch_workers",
        lambda *args, **kwargs: ["arn:task/1"],
    )
    task_writes = MagicMock()
    monitor_error = RuntimeError("monitor launch failed")
    monitor_launch = MagicMock(side_effect=monitor_error)
    release = MagicMock(return_value=True)
    monkeypatch.setattr(orchestrate, "write_task_arns", task_writes)
    monkeypatch.setattr(orchestrate, "launch_monitor", monitor_launch)
    monkeypatch.setattr(lease, "release_run_lease", release)

    result = CliRunner().invoke(_submit_app(), ["submit", "--monitor-in-ecs"])

    assert result.exit_code != 0
    assert result.exception is monitor_error
    assert task_writes.call_count == 2
    assert monitor_launch.call_count == 2
    release.assert_not_called()


def test_submit_requires_a_terminal_coordinator_before_mutating_aws(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aws_batch_scraper import lease

    acquire = MagicMock()
    monkeypatch.setattr(lease, "acquire_run_lease", acquire)

    result = CliRunner().invoke(_submit_app(), ["submit"])

    assert result.exit_code == 2
    output = " ".join(strip_ansi(result.output).split())
    assert "terminal run ownership" in output
    acquire.assert_not_called()


def test_submit_retains_lease_when_worker_launch_is_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lost RunTask response cannot be compensated as a confirmed zero launch."""
    from aws_batch_scraper import cli, ids, lease, orchestrate, queue
    from aws_batch_scraper.orchestrate import WorkerLaunchError

    _patch_submit_session(monkeypatch)
    monkeypatch.setattr(ids, "make_run_id", lambda: "run-1")
    monkeypatch.setattr(lease, "acquire_run_lease", lambda *args, **kwargs: None)
    monkeypatch.setattr(queue, "seed_queue", lambda *args, **kwargs: 1)
    monkeypatch.setattr(orchestrate, "write_run_manifest", lambda *args, **kwargs: None)
    launch_error = WorkerLaunchError([], 1, launch_ambiguous=True)
    monkeypatch.setattr(
        orchestrate,
        "launch_workers",
        lambda *args, **kwargs: (_ for _ in ()).throw(launch_error),
    )
    release = MagicMock()
    evidence = MagicMock()
    monkeypatch.setattr(lease, "release_run_lease", release)
    monkeypatch.setattr(cli, "_record_submission_recovery", evidence)

    result = CliRunner().invoke(_submit_app(), ["submit", "--monitor-in-ecs"])

    assert result.exit_code != 0
    assert result.exception is launch_error
    release.assert_not_called()
    evidence.assert_called_once()
    assert evidence.call_args.args[3] is _SubmitPhase.WORKER_LAUNCH_UNKNOWN


def test_submit_definitive_zero_worker_failure_retains_seeded_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A definitive ECS capacity failure does not make queued work disappear."""
    from aws_batch_scraper import cli, ids, lease, orchestrate, queue
    from aws_batch_scraper.orchestrate import WorkerLaunchError

    _patch_submit_session(monkeypatch)
    monkeypatch.setattr(ids, "make_run_id", lambda: "run-1")
    monkeypatch.setattr(lease, "acquire_run_lease", lambda *args, **kwargs: None)
    monkeypatch.setattr(orchestrate, "write_run_manifest", lambda *args, **kwargs: None)
    monkeypatch.setattr(queue, "seed_queue", lambda *args, **kwargs: 1)
    launch_error = WorkerLaunchError([], 1)
    monkeypatch.setattr(
        orchestrate,
        "launch_workers",
        lambda *args, **kwargs: (_ for _ in ()).throw(launch_error),
    )
    release = MagicMock()
    evidence = MagicMock()
    monkeypatch.setattr(lease, "release_run_lease", release)
    monkeypatch.setattr(cli, "_record_submission_recovery", evidence)

    result = CliRunner().invoke(_submit_app(), ["submit", "--monitor-in-ecs"])

    assert result.exit_code != 0
    assert result.exception is launch_error
    release.assert_not_called()
    assert evidence.call_args.args[3] is _SubmitPhase.QUEUE_SEEDED


def test_submission_recovery_evidence_records_phase_and_known_tasks() -> None:
    s3 = MagicMock()
    error = RuntimeError("capacity exhausted")

    _record_submission_recovery(
        s3,
        _SubmitConfig(),
        "run-1",
        _SubmitPhase.WORKERS_PARTIALLY_STARTED,
        error,
        task_arns=["arn:task/1"],
    )

    request = s3.put_object.call_args.kwargs
    assert request["Key"] == "scraper/runs/run-1/submission-recovery.json"
    body = json.loads(request["Body"])
    assert body == {
        "run_id": "run-1",
        "recorded_at": body["recorded_at"],
        "phase": "workers-partially-started",
        "detail": "capacity exhausted",
        "lease_action": "retained",
        "task_arns": ["arn:task/1"],
    }
