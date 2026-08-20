"""Contracts for persisted ECS task metadata."""

import json
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from aws_batch_scraper.config import SubmitterConfig, WorkerConfig
from aws_batch_scraper.orchestrate import (
    _finalize_manifest,
    get_task_arns,
    launch_monitor,
    launch_workers,
    resolve_split_task_definitions,
    write_run_manifest,
)
from aws_batch_scraper.types import WorkItem
from botocore.exceptions import ClientError

IMAGE_URI = "123456789012.dkr.ecr.us-east-1.amazonaws.com/ujs-scraper@sha256:" + "a" * 64
TASK_ROLE_ARN = "arn:aws:iam::123456789012:role/ujs-scraper-task"
EXECUTION_ROLE_ARN = "arn:aws:iam::123456789012:role/ujs-scraper-execution"
MONITOR_SECRET_ARN = (
    "arn:aws:secretsmanager:us-east-1:123456789012:secret:ujs-scraper/github-dispatch-token-AbCdEf"
)


def _config() -> WorkerConfig:
    return WorkerConfig(
        _env_file=None,
        s3_bucket="bucket",
        s3_scraper_prefix="scraper",
        aws_account_id="123456789012",
        sqs_queue_name="queue",
        sqs_dlq_name="queue-dlq",
    )


def _submitter_config() -> SubmitterConfig:
    return SubmitterConfig(
        _env_file=None,
        s3_bucket="bucket",
        s3_scraper_prefix="scraper",
        aws_account_id="123456789012",
        sqs_queue_name="queue",
        sqs_dlq_name="queue-dlq",
        ecs_cluster_name="cluster",
        ecs_task_definition="task:1",
        ecs_monitor_task_definition="monitor-task:2",
        ecs_expected_image_uri=IMAGE_URI,
        ecs_expected_task_role_arn=TASK_ROLE_ARN,
        ecs_expected_execution_role_arn=EXECUTION_ROLE_ARN,
        ecs_expected_monitor_secret_arn=MONITOR_SECRET_ARN,
        ecs_platform_version="1.4.0",
        github_repository="owner/repository",
        github_workflow_file="process.yml",
        ecs_container_name="worker",
        ecs_subnet_ids=["subnet-1"],
        ecs_security_group_ids=["sg-1"],
    )


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, "GetObject")


def _task_definition_response(
    family_revision: str,
    *,
    image: str | None = None,
    secrets: list[dict[str, str]] | None = None,
    environment: list[dict[str, str]] | None = None,
    command: list[str] | None = None,
    entry_point: list[str] | None = None,
) -> dict[str, object]:
    resolved_command = (
        command
        if command is not None
        else (["/bin/false"] if family_revision.startswith("monitor") else [])
    )
    return {
        "taskDefinition": {
            "taskDefinitionArn": (
                f"arn:aws:ecs:us-east-1:123456789012:task-definition/{family_revision}"
            ),
            "taskRoleArn": TASK_ROLE_ARN,
            "executionRoleArn": EXECUTION_ROLE_ARN,
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
                    "image": image or IMAGE_URI,
                    "secrets": secrets or [],
                    "environment": environment or [],
                    "command": resolved_command,
                    "entryPoint": entry_point or [],
                    "user": "app",
                    "readonlyRootFilesystem": True,
                    "privileged": False,
                    "linuxParameters": {"capabilities": {"drop": ["ALL"]}},
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
    }


def _split_definition_ecs(
    *,
    worker_response: dict[str, object] | None = None,
    monitor_response: dict[str, object] | None = None,
) -> MagicMock:
    ecs = MagicMock()
    ecs.describe_clusters.return_value = {
        "clusters": [
            {
                "clusterArn": "arn:aws:ecs:us-east-1:123456789012:cluster/cluster",
                "status": "ACTIVE",
            }
        ],
        "failures": [],
    }
    ecs.describe_task_definition.side_effect = [
        worker_response or _task_definition_response("task:1"),
        monitor_response
        or _task_definition_response(
            "monitor-task:2",
            secrets=[
                {
                    "name": "GITHUB_DISPATCH_TOKEN",
                    "valueFrom": MONITOR_SECRET_ARN,
                }
            ],
        ),
    ]
    return ecs


def _s3_with_body(body: bytes) -> MagicMock:
    stream = MagicMock()
    stream.read.return_value = body
    s3 = MagicMock()
    s3.get_object.return_value = {"Body": stream}
    return s3


@pytest.mark.parametrize(
    ("selection_mode", "candidate_count"),
    [("sample", 10), ("incremental", 10), ("full", 1)],
)
def test_run_manifest_persists_selection_provenance(
    selection_mode: str,
    candidate_count: int,
) -> None:
    s3 = MagicMock()

    write_run_manifest(
        s3,
        _submitter_config(),
        "run-1",
        [WorkItem(item_id="100")],
        worker_count=1,
        selection_mode=selection_mode,  # ty: ignore[invalid-argument-type]
        candidate_count=candidate_count,
    )

    manifest_put = s3.put_object.call_args_list[0].kwargs
    manifest = json.loads(manifest_put["Body"])
    assert manifest["selection_mode"] == selection_mode
    assert manifest["candidate_count"] == candidate_count
    assert manifest["input_size"] == 1


@pytest.mark.parametrize(
    ("selection_mode", "candidate_count", "message"),
    [
        ("sample", 0, "candidate count"),
        ("incremental", 0, "candidate count"),
        ("full", 2, "full run"),
        ("preview", 1, "selection mode"),
        ("sample", True, "integer"),
    ],
)
def test_run_manifest_rejects_impossible_selection_provenance_before_writing(
    selection_mode: str,
    candidate_count: int,
    message: str,
) -> None:
    s3 = MagicMock()

    with pytest.raises(ValueError, match=message):
        write_run_manifest(
            s3,
            _submitter_config(),
            "run-1",
            [WorkItem(item_id="100")],
            worker_count=1,
            selection_mode=selection_mode,  # ty: ignore[invalid-argument-type]
            candidate_count=candidate_count,
        )

    s3.put_object.assert_not_called()


def test_run_manifest_rejects_empty_selection_before_writing() -> None:
    s3 = MagicMock()

    with pytest.raises(ValueError, match="at least one"):
        write_run_manifest(
            s3,
            _submitter_config(),
            "run-1",
            [],
            worker_count=1,
            selection_mode="sample",
            candidate_count=1,
        )

    s3.put_object.assert_not_called()


def test_missing_task_manifest_fails_closed() -> None:
    s3 = MagicMock()
    s3.get_object.side_effect = _client_error("NoSuchKey")

    with pytest.raises(FileNotFoundError, match="run-1"):
        get_task_arns(s3, _config(), "run-1")


def test_task_manifest_access_error_fails_closed() -> None:
    s3 = MagicMock()
    forbidden = _client_error("AccessDenied")
    s3.get_object.side_effect = forbidden

    with pytest.raises(ClientError) as exc_info:
        get_task_arns(s3, _config(), "run-1")

    assert exc_info.value is forbidden


@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        b"[]",
        json.dumps({"task_arns": []}).encode(),
        json.dumps({"task_arns": "arn:task/1"}).encode(),
        json.dumps({"task_arns": ["arn:task/1", None]}).encode(),
        json.dumps({"task_arns": [""]}).encode(),
        json.dumps({"task_arns": ["not-an-arn"]}).encode(),
    ],
)
def test_malformed_task_manifest_fails_closed(body: bytes) -> None:
    with pytest.raises(ValueError, match="Task manifest"):
        get_task_arns(_s3_with_body(body), _config(), "run-1")


def test_valid_task_manifest_preserves_every_arn() -> None:
    body = json.dumps({"task_arns": ["arn:task/1", "arn:task/2"]}).encode()

    assert get_task_arns(_s3_with_body(body), _config(), "run-1") == [
        "arn:task/1",
        "arn:task/2",
    ]


def test_worker_launch_rejects_mutated_bare_task_definition() -> None:
    config = _submitter_config()
    config.ecs_task_definition = "task"
    ecs = MagicMock()

    with pytest.raises(ValueError, match="exact family:revision"):
        launch_workers(ecs, config, "run-1")

    ecs.run_task.assert_not_called()


@pytest.mark.parametrize("launcher", ["worker", "monitor"])
def test_task_launch_rejects_mutated_fargate_platform(launcher: str) -> None:
    config = _submitter_config()
    config.ecs_platform_version = "LATEST"
    ecs = _split_definition_ecs()

    with pytest.raises(ValueError, match="ECS_PLATFORM_VERSION"):
        if launcher == "worker":
            launch_workers(ecs, config, "run-1")
        else:
            launch_monitor(ecs, config, "run-1", ["tool", "monitor"])

    ecs.run_task.assert_not_called()


def test_split_task_definition_contract_resolves_both_exact_revisions() -> None:
    ecs = _split_definition_ecs()

    assert resolve_split_task_definitions(ecs, _submitter_config()) == (
        "task:1",
        "monitor-task:2",
    )
    assert [
        call.kwargs["taskDefinition"] for call in ecs.describe_task_definition.call_args_list
    ] == [
        "task:1",
        "monitor-task:2",
    ]


@pytest.mark.parametrize("secret_name", ["GITHUB_DISPATCH_TOKEN", "OTHER_SECRET"])
def test_split_task_definition_contract_rejects_every_worker_secret(
    secret_name: str,
) -> None:
    ecs = _split_definition_ecs(
        worker_response=_task_definition_response(
            "task:1",
            secrets=[
                {
                    "name": secret_name,
                    "valueFrom": "arn:aws:secretsmanager:token",
                }
            ],
        )
    )

    with pytest.raises(ValueError, match="must not include any ECS secrets"):
        resolve_split_task_definitions(ecs, _submitter_config())


def test_split_task_definition_contract_rejects_static_worker_environment() -> None:
    ecs = _split_definition_ecs(
        worker_response=_task_definition_response(
            "task:1",
            environment=[{"name": "UNREVIEWED", "value": "value"}],
        )
    )

    with pytest.raises(ValueError, match="must not include static environment"):
        resolve_split_task_definitions(ecs, _submitter_config())


def test_split_task_definition_contract_rejects_worker_environment_files() -> None:
    worker_response = _task_definition_response("task:1")
    definition = cast(dict[str, Any], worker_response["taskDefinition"])
    container = cast(dict[str, Any], definition["containerDefinitions"][0])
    container["environmentFiles"] = [{"type": "s3", "value": "arn:aws:s3:::bucket/env"}]

    with pytest.raises(ValueError, match="opaque environment files"):
        resolve_split_task_definitions(
            _split_definition_ecs(worker_response=worker_response),
            _submitter_config(),
        )


@pytest.mark.parametrize(
    "image",
    ["repository.example/task:latest", "repository.example/task:release-1"],
)
def test_split_task_definition_contract_rejects_mutable_images(image: str) -> None:
    ecs = _split_definition_ecs(
        worker_response=_task_definition_response(
            "task:1",
            image=image,
        )
    )

    with pytest.raises(ValueError, match="repository@sha256"):
        resolve_split_task_definitions(ecs, _submitter_config())


@pytest.mark.parametrize(
    ("setting", "value", "message"),
    [
        ("user", None, "app user"),
        ("user", "root", "app user"),
        ("user", "0:0", "app user"),
        ("readonlyRootFilesystem", False, "read-only root filesystem"),
        ("readonlyRootFilesystem", None, "read-only root filesystem"),
        ("linuxParameters", None, "linuxParameters"),
    ],
)
def test_split_task_definition_contract_requires_hardened_runtime(
    setting: str,
    value: object,
    message: str,
) -> None:
    worker_response = _task_definition_response("task:1")
    definition = cast(dict[str, Any], worker_response["taskDefinition"])
    container = cast(dict[str, Any], definition["containerDefinitions"][0])
    if value is None:
        container.pop(setting)
    else:
        container[setting] = value
    ecs = _split_definition_ecs(worker_response=worker_response)

    with pytest.raises(ValueError, match=message):
        resolve_split_task_definitions(ecs, _submitter_config())


@pytest.mark.parametrize(
    ("setting", "value", "message"),
    [
        ("networkMode", "bridge", "awsvpc"),
        (
            "runtimePlatform",
            {"operatingSystemFamily": "LINUX", "cpuArchitecture": "ARM64"},
            "LINUX/X86_64",
        ),
        ("volumes", [], "one temporary volume"),
        (
            "volumes",
            [{"name": "tmp", "efsVolumeConfiguration": {"fileSystemId": "fs-123"}}],
            "ephemeral task storage",
        ),
    ],
)
def test_split_task_definition_contract_requires_exact_platform_and_temporary_volume(
    setting: str,
    value: object,
    message: str,
) -> None:
    worker_response = _task_definition_response("task:1")
    definition = cast(dict[str, Any], worker_response["taskDefinition"])
    definition[setting] = value
    ecs = _split_definition_ecs(worker_response=worker_response)

    with pytest.raises(ValueError, match=message):
        resolve_split_task_definitions(ecs, _submitter_config())


@pytest.mark.parametrize(
    ("setting", "value", "message"),
    [
        ("privileged", True, "unprivileged"),
        ("mountPoints", [], "writable /tmp"),
        (
            "mountPoints",
            [{"sourceVolume": "tmp", "containerPath": "/tmp", "readOnly": True}],
            "writable /tmp",
        ),
        ("volumesFrom", [{"sourceContainer": "sidecar"}], "opaque volumes"),
        (
            "repositoryCredentials",
            {"credentialsParameter": MONITOR_SECRET_ARN},
            "repository credentials",
        ),
        (
            "credentialSpecs",
            ["credentialspecdomainless:arn:aws:s3:::bucket/spec"],
            "credential specs",
        ),
        (
            "firelensConfiguration",
            {"type": "fluentbit"},
            "log router",
        ),
        (
            "dockerLabels",
            {"GITHUB_DISPATCH_TOKEN": "plaintext"},
            "opaque labels",
        ),
        (
            "healthCheck",
            {"command": ["CMD-SHELL", "browser-worker"]},
            "static health command",
        ),
        (
            "portMappings",
            [{"containerPort": 8080, "hostPort": 8080}],
            "expose network ports",
        ),
        ("interactive", True, "noninteractive"),
        ("pseudoTerminal", True, "noninteractive"),
        (
            "logConfiguration",
            {
                "logDriver": "awslogs",
                "secretOptions": [{"name": "token", "valueFrom": MONITOR_SECRET_ARN}],
            },
            "without secret options",
        ),
        (
            "logConfiguration",
            {"logDriver": "splunk", "secretOptions": []},
            "use awslogs",
        ),
        ("linuxParameters", {"capabilities": {"add": ["SYS_ADMIN"]}}, "capabilities"),
        ("linuxParameters", {"capabilities": {"drop": []}}, "drop every"),
        ("linuxParameters", {"capabilities": {"drop": ["NET_RAW"]}}, "drop every"),
        (
            "linuxParameters",
            {
                "capabilities": {"drop": ["ALL"]},
                "tmpfs": [{"containerPath": "/app", "size": 64}],
            },
            "tmpfs",
        ),
    ],
)
def test_split_task_definition_contract_rejects_runtime_isolation_bypasses(
    setting: str,
    value: object,
    message: str,
) -> None:
    worker_response = _task_definition_response("task:1")
    definition = cast(dict[str, Any], worker_response["taskDefinition"])
    container = cast(dict[str, Any], definition["containerDefinitions"][0])
    container[setting] = value
    ecs = _split_definition_ecs(worker_response=worker_response)

    with pytest.raises(ValueError, match=message):
        resolve_split_task_definitions(ecs, _submitter_config())


def test_split_task_definition_contract_requires_monitor_secret_injection() -> None:
    ecs = _split_definition_ecs(monitor_response=_task_definition_response("monitor-task:2"))

    with pytest.raises(ValueError, match="inject only GITHUB_DISPATCH_TOKEN"):
        resolve_split_task_definitions(ecs, _submitter_config())


@pytest.mark.parametrize(
    "command",
    [
        [],
        ["gv-dashboard-etl", "courts", "worker"],
        ["/bin/false", "unexpected-argument"],
    ],
)
def test_split_task_definition_contract_requires_fail_closed_monitor_default(
    command: list[str],
) -> None:
    ecs = _split_definition_ecs(
        monitor_response=_task_definition_response(
            "monitor-task:2",
            command=command,
            secrets=[
                {
                    "name": "GITHUB_DISPATCH_TOKEN",
                    "valueFrom": MONITOR_SECRET_ARN,
                }
            ],
        )
    )

    with pytest.raises(ValueError, match=r"default to \['/bin/false'\]"):
        resolve_split_task_definitions(ecs, _submitter_config())


def test_split_task_definition_contract_rejects_extra_monitor_secret() -> None:
    ecs = _split_definition_ecs(
        monitor_response=_task_definition_response(
            "monitor-task:2",
            secrets=[
                {
                    "name": "GITHUB_DISPATCH_TOKEN",
                    "valueFrom": MONITOR_SECRET_ARN,
                },
                {
                    "name": "UNREVIEWED",
                    "valueFrom": "arn:aws:secretsmanager:other",
                },
            ],
        )
    )

    with pytest.raises(ValueError, match="inject only GITHUB_DISPATCH_TOKEN"):
        resolve_split_task_definitions(ecs, _submitter_config())


@pytest.mark.parametrize(
    "secrets",
    [
        [
            {
                "name": "GITHUB_DISPATCH_TOKEN",
                "valueFrom": ("arn:aws:secretsmanager:us-east-1:123456789012:secret:other-AbCdEf"),
            }
        ],
        [
            {"name": "GITHUB_DISPATCH_TOKEN", "valueFrom": MONITOR_SECRET_ARN},
            {"name": "GITHUB_DISPATCH_TOKEN", "valueFrom": MONITOR_SECRET_ARN},
        ],
    ],
)
def test_split_task_definition_contract_binds_one_exact_monitor_secret(
    secrets: list[dict[str, str]],
) -> None:
    ecs = _split_definition_ecs(
        monitor_response=_task_definition_response("monitor-task:2", secrets=secrets)
    )

    with pytest.raises(ValueError, match="reviewed ECS secret"):
        resolve_split_task_definitions(ecs, _submitter_config())


def test_split_task_definition_contract_rejects_plaintext_monitor_token() -> None:
    ecs = _split_definition_ecs(
        monitor_response=_task_definition_response(
            "monitor-task:2",
            secrets=[
                {
                    "name": "GITHUB_DISPATCH_TOKEN",
                    "valueFrom": "arn:aws:secretsmanager:token",
                }
            ],
            environment=[{"name": "GITHUB_DISPATCH_TOKEN", "value": "plaintext"}],
        )
    )

    with pytest.raises(ValueError, match="must not include static environment"):
        resolve_split_task_definitions(ecs, _submitter_config())


def test_split_task_definition_contract_requires_one_shared_image_digest() -> None:
    ecs = _split_definition_ecs(
        monitor_response=_task_definition_response(
            "monitor-task:2",
            image="repository.example/task@sha256:" + "b" * 64,
            secrets=[
                {
                    "name": "GITHUB_DISPATCH_TOKEN",
                    "valueFrom": "arn:aws:secretsmanager:token",
                }
            ],
        )
    )

    with pytest.raises(ValueError, match="same image digest"):
        resolve_split_task_definitions(ecs, _submitter_config())


def test_split_task_definition_contract_requires_the_release_gate_image() -> None:
    config = _submitter_config()
    config.ecs_expected_image_uri = (
        "123456789012.dkr.ecr.us-east-1.amazonaws.com/ujs-scraper@sha256:" + "b" * 64
    )

    with pytest.raises(ValueError, match="ECS_EXPECTED_IMAGE_URI"):
        resolve_split_task_definitions(_split_definition_ecs(), config)


@pytest.mark.parametrize(
    ("field", "definition_key", "message"),
    [
        ("ecs_expected_task_role_arn", "taskRoleArn", "reviewed task role"),
        (
            "ecs_expected_execution_role_arn",
            "executionRoleArn",
            "reviewed execution role",
        ),
    ],
)
def test_split_task_definition_contract_binds_reviewed_roles(
    field: str,
    definition_key: str,
    message: str,
) -> None:
    config = _submitter_config()
    setattr(config, field, "arn:aws:iam::123456789012:role/reviewed-other-role")

    with pytest.raises(ValueError, match=message):
        resolve_split_task_definitions(_split_definition_ecs(), config)


@pytest.mark.parametrize(
    "field",
    ["ecs_expected_task_role_arn", "ecs_expected_execution_role_arn"],
)
def test_split_task_definition_contract_requires_reviewed_role_config(field: str) -> None:
    config = _submitter_config()
    setattr(config, field, None)

    with pytest.raises(ValueError, match="exact same-account IAM role ARN"):
        resolve_split_task_definitions(_split_definition_ecs(), config)


def test_split_task_definition_contract_rejects_missing_release_gate_image() -> None:
    config = _submitter_config()
    config.ecs_expected_image_uri = None

    with pytest.raises(ValueError, match="ECS_EXPECTED_IMAGE_URI"):
        resolve_split_task_definitions(_split_definition_ecs(), config)


def test_split_task_definition_contract_rejects_worker_command_override() -> None:
    ecs = _split_definition_ecs(
        worker_response=_task_definition_response(
            "task:1",
            command=["monitor"],
        )
    )

    with pytest.raises(ValueError, match="default worker command"):
        resolve_split_task_definitions(ecs, _submitter_config())


def test_split_task_definition_contract_rejects_monitor_entry_point_override() -> None:
    ecs = _split_definition_ecs(
        monitor_response=_task_definition_response(
            "monitor-task:2",
            entry_point=["unexpected-entrypoint"],
            secrets=[
                {
                    "name": "GITHUB_DISPATCH_TOKEN",
                    "valueFrom": "arn:aws:secretsmanager:token",
                }
            ],
        )
    )

    with pytest.raises(ValueError, match="must not override the image entry point"):
        resolve_split_task_definitions(ecs, _submitter_config())


def test_split_task_definition_contract_rejects_inactive_cluster() -> None:
    ecs = _split_definition_ecs()
    ecs.describe_clusters.return_value["clusters"][0]["status"] = "INACTIVE"

    with pytest.raises(ValueError, match="must be ACTIVE"):
        resolve_split_task_definitions(ecs, _submitter_config())


def test_split_task_definition_contract_rejects_cluster_lookup_failure() -> None:
    ecs = _split_definition_ecs()
    ecs.describe_clusters.return_value = {
        "clusters": [],
        "failures": [{"arn": "cluster", "reason": "MISSING"}],
    }

    with pytest.raises(ValueError, match="could not be resolved exactly"):
        resolve_split_task_definitions(ecs, _submitter_config())


def test_worker_launch_rejects_mutated_monitor_task_definition() -> None:
    config = _submitter_config()
    config.ecs_monitor_task_definition = "monitor-task"
    ecs = MagicMock()

    with pytest.raises(ValueError, match="ECS_MONITOR_TASK_DEFINITION"):
        launch_workers(ecs, config, "run-1")

    ecs.run_task.assert_not_called()


def test_monitor_launch_rejects_shared_task_definition_after_mutation() -> None:
    config = _submitter_config()
    config.ecs_monitor_task_definition = "task:1"
    ecs = MagicMock()

    with pytest.raises(ValueError, match="different task-definition revisions"):
        launch_monitor(ecs, config, "run-1", ["monitor"])

    ecs.run_task.assert_not_called()


def test_monitor_launch_rejects_mutated_workflow_target() -> None:
    config = _submitter_config()
    config.github_workflow_file = "../process.yml"
    ecs = MagicMock()

    with pytest.raises(ValueError, match="workflow filename"):
        launch_monitor(ecs, config, "run-1", ["monitor"])

    ecs.run_task.assert_not_called()


def test_finalize_manifest_access_error_fails_closed() -> None:
    s3 = MagicMock()
    forbidden = _client_error("AccessDenied")
    s3.get_object.side_effect = forbidden

    with pytest.raises(ClientError) as exc_info:
        _finalize_manifest(
            s3,
            MagicMock(),
            _submitter_config(),
            "run-1",
            datetime.now(UTC),
        )

    assert exc_info.value is forbidden
    s3.put_object.assert_not_called()


@pytest.mark.parametrize("body", [b"not-json", b"[]"])
def test_finalize_manifest_rejects_corrupt_record(body: bytes) -> None:
    s3 = _s3_with_body(body)

    with pytest.raises(ValueError, match="Run manifest"):
        _finalize_manifest(
            s3,
            MagicMock(),
            _submitter_config(),
            "run-1",
            datetime.now(UTC),
        )

    s3.put_object.assert_not_called()
