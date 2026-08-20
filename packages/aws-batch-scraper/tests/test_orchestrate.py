"""Contracts for persisted ECS task metadata."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from aws_batch_scraper.config import SubmitterConfig, WorkerConfig
from aws_batch_scraper.orchestrate import (
    ManifestPublicationDeliveryUnknownError,
    _ecs_client_token,
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


def _one_item_terminal_inventory() -> MagicMock:
    return MagicMock(
        input_sha256="a" * 64,
        force_rescrape=True,
        items=(WorkItem(item_id="1"),),
        result_ids={"1"},
        failure_ids=set(),
        completed_ids={"1"},
        terminal_evidence_sha256="b" * 64,
        candidate_count=1,
        candidate_evidence_sha256="d" * 64,
        conflict_policy_version=1,
        conflict_evidence_sha256="c" * 64,
        resolved_conflict_count=0,
        invalid_resolution_count=0,
    )


def _empty_sqs() -> MagicMock:
    sqs = MagicMock()
    sqs.get_queue_attributes.return_value = {
        "Attributes": {
            "ApproximateNumberOfMessages": "0",
            "ApproximateNumberOfMessagesNotVisible": "0",
            "ApproximateNumberOfMessagesDelayed": "0",
        }
    }
    return sqs


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
        force_rescrape=selection_mode == "full",
    )

    input_put = s3.put_object.call_args_list[0].kwargs
    manifest_put = s3.put_object.call_args_list[1].kwargs
    manifest = json.loads(manifest_put["Body"])
    assert manifest["selection_mode"] == selection_mode
    assert manifest["candidate_count"] == candidate_count
    assert manifest["input_size"] == 1
    assert manifest["force_rescrape"] is (selection_mode == "full")
    assert manifest["terminal_candidate_journal_schema_version"] == 1
    assert manifest["input_sha256"] == hashlib.sha256(input_put["Body"]).hexdigest()
    assert manifest_put["IfNoneMatch"] == "*"
    assert input_put["IfNoneMatch"] == "*"
    assert input_put["Key"].endswith("/input.jsonl")
    assert manifest_put["Key"].endswith("/manifest.json")


def test_run_commit_never_writes_manifest_when_input_cannot_be_confirmed() -> None:
    s3 = MagicMock()
    s3.put_object.side_effect = TimeoutError("input response lost")
    s3.get_object.side_effect = TimeoutError("input read failed")

    with pytest.raises(RuntimeError, match="could not be committed or reconciled"):
        write_run_manifest(
            s3,
            _submitter_config(),
            "run-1",
            [WorkItem(item_id="100")],
            worker_count=1,
            selection_mode="incremental",
            candidate_count=1,
            force_rescrape=False,
        )

    assert s3.put_object.call_count == 1
    assert s3.put_object.call_args.kwargs["Key"].endswith("/input.jsonl")


@pytest.mark.parametrize("lost_key", ["input.jsonl", "manifest.json"])
def test_run_commit_exact_read_recovers_lost_put_response(lost_key: str) -> None:
    s3 = MagicMock()
    attempted: dict[str, bytes] = {}
    lost = False

    def put_object(**kwargs):
        nonlocal lost
        key = str(kwargs["Key"])
        attempted[key] = kwargs["Body"]
        if key.endswith(lost_key) and not lost:
            lost = True
            raise TimeoutError("response lost after commit")
        return {"ETag": '"etag"'}

    def get_object(*, Bucket, Key):
        stream = MagicMock()
        stream.read.return_value = attempted[Key]
        return {"Body": stream, "ETag": '"etag"'}

    s3.put_object.side_effect = put_object
    s3.get_object.side_effect = get_object

    write_run_manifest(
        s3,
        _submitter_config(),
        "run-1",
        [WorkItem(item_id="100")],
        worker_count=1,
        selection_mode="incremental",
        candidate_count=1,
        force_rescrape=False,
    )

    assert any(key.endswith("/input.jsonl") for key in attempted)
    assert any(key.endswith("/manifest.json") for key in attempted)


def test_recovery_attempt_uses_a_distinct_but_retry_stable_ecs_token() -> None:
    initial = _ecs_client_token("run-1", "worker")
    first_attempt = _ecs_client_token(
        "run-1",
        "worker",
        recovery_attempt_id="attempt-1",
    )
    same_attempt_retry = _ecs_client_token(
        "run-1",
        "worker",
        recovery_attempt_id="attempt-1",
    )
    second_attempt = _ecs_client_token(
        "run-1",
        "worker",
        recovery_attempt_id="attempt-2",
    )

    assert len({initial, first_attempt, second_attempt}) == 3
    assert first_attempt == same_attempt_retry


@pytest.mark.parametrize("delay", [0, 43_201])
def test_worker_launch_rejects_invalid_soft_blocked_delay(delay: int) -> None:
    ecs = MagicMock()

    with pytest.raises(ValueError, match="between 1 and 43200"):
        launch_workers(
            ecs,
            _submitter_config(),
            "run-1",
            soft_blocked_delay_max=delay,
        )

    ecs.run_task.assert_not_called()


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
            force_rescrape=False,
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
            force_rescrape=False,
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


def test_finalize_manifest_cas_gates_dispatch_on_exact_terminal_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aws_batch_scraper import orchestrate, recovery

    manifest = {
        "run_id": "run-1",
        "timestamp": datetime.now(UTC).isoformat(),
        "selection_mode": "full",
        "candidate_count": 2,
        "input_size": 2,
    }
    stream = MagicMock()
    stream.read.return_value = json.dumps(manifest).encode()
    s3 = MagicMock()
    s3.get_object.return_value = {"Body": stream, "ETag": '"manifest-etag"'}
    sqs = MagicMock()
    sqs.get_queue_attributes.return_value = {
        "Attributes": {
            "ApproximateNumberOfMessages": "0",
            "ApproximateNumberOfMessagesNotVisible": "0",
            "ApproximateNumberOfMessagesDelayed": "0",
        }
    }
    inventory = MagicMock()
    inventory.input_sha256 = "a" * 64
    inventory.force_rescrape = True
    inventory.items = (WorkItem(item_id="1"), WorkItem(item_id="2"))
    inventory.result_ids = {"1"}
    inventory.failure_ids = {"2"}
    inventory.completed_ids = {"1", "2"}
    inventory.terminal_evidence_sha256 = "b" * 64
    inventory.candidate_count = 2
    inventory.candidate_evidence_sha256 = "d" * 64
    inventory.conflict_policy_version = 1
    inventory.conflict_evidence_sha256 = "c" * 64
    inventory.resolved_conflict_count = 0
    inventory.invalid_resolution_count = 0
    coverage = MagicMock(return_value=inventory)
    dispatch = MagicMock()
    monkeypatch.setattr(recovery, "require_exact_terminal_coverage", coverage)
    monkeypatch.setattr(orchestrate, "dispatch_workflow", dispatch)
    monkeypatch.setattr(orchestrate, "_TERMINAL_QUEUE_QUIET_SECONDS", 0)

    _finalize_manifest(
        s3,
        sqs,
        _submitter_config(),
        "run-1",
        datetime.now(UTC),
        terminal_queue_counts=(0, 0, 0),
    )

    coverage.assert_called_once()
    put = s3.put_object.call_args.kwargs
    assert put["IfMatch"] == '"manifest-etag"'
    finalized = json.loads(put["Body"])
    assert finalized["terminal_coverage"]["completed_count"] == 2
    assert finalized["terminal_coverage"]["unresolved_conflict_count"] == 0
    dispatch.assert_called_once()


def test_monitor_coverage_failure_retains_same_run_lease_for_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aws_batch_scraper import orchestrate
    from aws_batch_scraper.recovery import RecoveryInvariantError

    generation = datetime(2026, 8, 20, 20, 0, tzinfo=UTC)
    task = {
        "taskArn": "arn:aws:ecs:us-east-1:123456789012:task/cluster/task-1",
        "lastStatus": "STOPPED",
        "stopCode": "EssentialContainerExited",
        "containers": [{"name": "worker", "essential": True, "exitCode": 0}],
    }
    ecs = MagicMock()
    ecs.describe_tasks.return_value = {"tasks": [task], "failures": []}
    s3 = MagicMock()
    released = MagicMock()
    monkeypatch.setattr(orchestrate, "get_task_arns", lambda *args: [task["taskArn"]])
    monkeypatch.setattr(
        orchestrate,
        "renew_run_lease",
        lambda *args: MagicMock(created_at=generation),
    )
    monkeypatch.setattr(orchestrate, "_require_empty_main_queue", lambda *args: (0, 0, 0))
    monkeypatch.setattr(
        orchestrate,
        "_finalize_manifest",
        MagicMock(side_effect=RecoveryInvariantError("candidate conflict blocks coverage")),
    )
    monkeypatch.setattr(orchestrate, "release_run_lease", released)

    with pytest.raises(RecoveryInvariantError, match="candidate conflict"):
        orchestrate._monitor_run(
            ecs,
            MagicMock(),
            s3,
            _submitter_config(),
            "run-1",
            poll_interval=0,
        )

    released.assert_not_called()
    evidence = s3.put_object.call_args.kwargs
    assert "/monitor-recovery/v1/" in evidence["Key"]
    assert evidence["IfNoneMatch"] == "*"
    record = json.loads(evidence["Body"])
    assert record["lease_action"] == "retained"
    assert record["recovery_action"] == "same-run-resume"


def test_finalize_manifest_never_rewrites_or_dispatches_completed_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aws_batch_scraper import orchestrate, recovery

    stream = MagicMock()
    stream.read.return_value = json.dumps(
        {
            "run_id": "run-1",
            "completed_at": "2026-08-20T20:00:00+00:00",
        }
    ).encode()
    s3 = MagicMock()
    s3.get_object.return_value = {"Body": stream, "ETag": '"manifest-etag"'}
    dispatch = MagicMock()
    coverage = MagicMock()
    monkeypatch.setattr(orchestrate, "dispatch_workflow", dispatch)
    monkeypatch.setattr(recovery, "require_exact_terminal_coverage", coverage)

    _finalize_manifest(
        s3,
        MagicMock(),
        _submitter_config(),
        "run-1",
        datetime.now(UTC),
        terminal_queue_counts=(0, 0, 0),
    )

    s3.put_object.assert_not_called()
    coverage.assert_not_called()
    dispatch.assert_not_called()


def test_finalize_manifest_rejects_changed_lease_generation_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aws_batch_scraper import orchestrate

    expected = datetime(2026, 8, 20, 19, 0, tzinfo=UTC)
    successor = MagicMock(
        run_id="run-1",
        owner="run-1",
        created_at=datetime(2026, 8, 20, 20, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(orchestrate, "read_run_lease", lambda *args: successor)
    dispatch = MagicMock()
    monkeypatch.setattr(orchestrate, "dispatch_workflow", dispatch)
    s3 = MagicMock()

    with pytest.raises(RuntimeError, match="dispatch is fenced"):
        _finalize_manifest(
            s3,
            MagicMock(),
            _submitter_config(),
            "run-1",
            datetime.now(UTC),
            terminal_queue_counts=(0, 0, 0),
            expected_lease_owner="run-1",
            expected_lease_created_at=expected,
        )

    s3.get_object.assert_not_called()
    s3.put_object.assert_not_called()
    dispatch.assert_not_called()


def test_finalize_manifest_claims_finalizer_fence_before_manifest_put(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aws_batch_scraper import orchestrate, recovery

    generation = datetime(2026, 8, 20, 20, 0, tzinfo=UTC)
    lease_state: dict[str, Any] = {
        "run_id": "run-1",
        "owner": "run-1",
        "created_at": generation,
    }
    events: list[str] = []

    def read_lease(*args):
        return MagicMock(**lease_state)

    def claim_lease(s3, config, run_id, claimant, **kwargs):
        assert lease_state["owner"] == kwargs["current_owner"]
        assert lease_state["created_at"] == kwargs["expected_created_at"]
        lease_state["owner"] = claimant
        events.append("claim-finalizer")
        return MagicMock(**lease_state)

    stream = MagicMock()
    stream.read.return_value = json.dumps(
        {"run_id": "run-1", "timestamp": generation.isoformat()}
    ).encode()
    s3 = MagicMock()
    s3.get_object.return_value = {"Body": stream, "ETag": '"manifest-etag"'}

    def put_manifest(**kwargs):
        assert str(lease_state["owner"]).startswith("finalize:")
        events.append("put-manifest")

    s3.put_object.side_effect = put_manifest
    sqs = MagicMock()
    sqs.get_queue_attributes.return_value = {
        "Attributes": {
            "ApproximateNumberOfMessages": "0",
            "ApproximateNumberOfMessagesNotVisible": "0",
            "ApproximateNumberOfMessagesDelayed": "0",
        }
    }
    inventory = MagicMock(
        input_sha256="a" * 64,
        force_rescrape=True,
        items=(WorkItem(item_id="1"),),
        result_ids={"1"},
        failure_ids=set(),
        completed_ids={"1"},
        terminal_evidence_sha256="b" * 64,
        candidate_count=1,
        candidate_evidence_sha256="d" * 64,
        conflict_policy_version=1,
        conflict_evidence_sha256="c" * 64,
        resolved_conflict_count=0,
        invalid_resolution_count=0,
    )
    monkeypatch.setattr(orchestrate, "read_run_lease", read_lease)
    monkeypatch.setattr(orchestrate, "claim_run_lease", claim_lease)
    monkeypatch.setattr(orchestrate, "_TERMINAL_QUEUE_QUIET_SECONDS", 0)
    monkeypatch.setattr(recovery, "require_exact_terminal_coverage", lambda *args: inventory)

    def dispatch(*args, **kwargs):
        assert str(lease_state["owner"]).startswith("finalize:")
        events.append("dispatch")

    monkeypatch.setattr(orchestrate, "dispatch_workflow", dispatch)

    _finalize_manifest(
        s3,
        sqs,
        _submitter_config(),
        "run-1",
        generation,
        terminal_queue_counts=(0, 0, 0),
        expected_lease_owner="run-1",
        expected_lease_created_at=generation,
    )

    assert events == ["claim-finalizer", "put-manifest", "dispatch"]


def test_finalize_manifest_reenters_exact_prepublication_finalizer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aws_batch_scraper import orchestrate, recovery
    from aws_batch_scraper.lease import finalizing_run_owner

    generation = datetime(2026, 8, 20, 20, 0, tzinfo=UTC)
    finalizer = finalizing_run_owner("run-1", generation)
    active = MagicMock(
        run_id="run-1",
        owner=finalizer,
        created_at=generation,
    )
    stream = MagicMock()
    stream.read.return_value = json.dumps(
        {"run_id": "run-1", "timestamp": generation.isoformat()}
    ).encode()
    s3 = MagicMock()
    s3.get_object.return_value = {"Body": stream, "ETag": '"manifest-etag"'}
    claim = MagicMock()
    dispatch = MagicMock()
    monkeypatch.setattr(orchestrate, "read_run_lease", lambda *args: active)
    monkeypatch.setattr(orchestrate, "claim_run_lease", claim)
    monkeypatch.setattr(orchestrate, "dispatch_workflow", dispatch)
    monkeypatch.setattr(orchestrate, "_TERMINAL_QUEUE_QUIET_SECONDS", 0)
    monkeypatch.setattr(
        recovery,
        "require_exact_terminal_coverage",
        lambda *args: _one_item_terminal_inventory(),
    )

    _finalize_manifest(
        s3,
        _empty_sqs(),
        _submitter_config(),
        "run-1",
        generation,
        terminal_queue_counts=(0, 0, 0),
        expected_lease_owner=finalizer,
        expected_lease_created_at=generation,
    )

    claim.assert_not_called()
    put = s3.put_object.call_args.kwargs
    assert put["IfMatch"] == '"manifest-etag"'
    assert json.loads(put["Body"])["completed_at"]
    dispatch.assert_called_once()


def test_finalize_manifest_dispatches_after_exact_read_proves_lost_put_committed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aws_batch_scraper import orchestrate, recovery

    generation = datetime(2026, 8, 20, 20, 0, tzinfo=UTC)
    original_body = json.dumps({"run_id": "run-1", "timestamp": generation.isoformat()}).encode()
    attempted_put: dict[str, Any] = {}
    get_count = 0

    def get_manifest(**kwargs):
        nonlocal get_count
        get_count += 1
        stream = MagicMock()
        if get_count == 1:
            stream.read.return_value = original_body
            return {"Body": stream, "ETag": '"manifest-etag"'}
        stream.read.return_value = attempted_put["Body"]
        return {"Body": stream, "ETag": '"committed-etag"'}

    def put_manifest(**kwargs):
        attempted_put.update(kwargs)
        raise TimeoutError("response lost after commit")

    s3 = MagicMock()
    s3.get_object.side_effect = get_manifest
    s3.put_object.side_effect = put_manifest
    dispatch = MagicMock()
    monkeypatch.setattr(orchestrate, "dispatch_workflow", dispatch)
    monkeypatch.setattr(orchestrate, "_TERMINAL_QUEUE_QUIET_SECONDS", 0)
    monkeypatch.setattr(
        recovery,
        "require_exact_terminal_coverage",
        lambda *args: _one_item_terminal_inventory(),
    )

    _finalize_manifest(
        s3,
        _empty_sqs(),
        _submitter_config(),
        "run-1",
        generation,
        terminal_queue_counts=(0, 0, 0),
    )

    assert get_count == 2
    dispatch.assert_called_once()


def test_finalize_manifest_records_unknown_dispatch_delivery_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aws_batch_scraper import orchestrate, recovery
    from aws_batch_scraper.dispatch import WorkflowDispatchDeliveryUnknownError

    generation = datetime(2026, 8, 20, 20, 0, tzinfo=UTC)
    stream = MagicMock()
    stream.read.return_value = json.dumps(
        {"run_id": "run-1", "timestamp": generation.isoformat()}
    ).encode()
    s3 = MagicMock()
    s3.get_object.return_value = {"Body": stream, "ETag": '"manifest-etag"'}
    monkeypatch.setattr(orchestrate, "_TERMINAL_QUEUE_QUIET_SECONDS", 0)
    monkeypatch.setattr(
        recovery,
        "require_exact_terminal_coverage",
        lambda *args: _one_item_terminal_inventory(),
    )
    monkeypatch.setattr(
        orchestrate,
        "dispatch_workflow",
        MagicMock(side_effect=WorkflowDispatchDeliveryUnknownError("delivery unknown")),
    )

    with pytest.raises(WorkflowDispatchDeliveryUnknownError, match="delivery unknown"):
        _finalize_manifest(
            s3,
            _empty_sqs(),
            _submitter_config(),
            "run-1",
            generation,
            terminal_queue_counts=(0, 0, 0),
        )

    ambiguous_evidence = [
        call.kwargs
        for call in s3.put_object.call_args_list
        if call.kwargs["Key"] == "scraper/runs/run-1/dispatch-ambiguous.json"
    ]
    assert len(ambiguous_evidence) == 1
    record = json.loads(ambiguous_evidence[0]["Body"])
    assert record["detail"] == "delivery unknown"
    assert record["lease_action"] == "retained"


def test_finalize_manifest_retains_finalizer_when_put_outcome_cannot_be_proven(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aws_batch_scraper import orchestrate, recovery

    generation = datetime(2026, 8, 20, 20, 0, tzinfo=UTC)
    lease_state: dict[str, Any] = {
        "run_id": "run-1",
        "owner": "run-1",
        "created_at": generation,
    }
    claimants: list[str] = []

    def read_lease(*args):
        return MagicMock(**lease_state)

    def claim_lease(s3, config, run_id, claimant, **kwargs):
        assert lease_state["owner"] == kwargs["current_owner"]
        lease_state["owner"] = claimant
        claimants.append(claimant)
        return MagicMock(**lease_state)

    stream = MagicMock()
    stream.read.return_value = json.dumps(
        {"run_id": "run-1", "timestamp": generation.isoformat()}
    ).encode()
    s3 = MagicMock()
    s3.get_object.side_effect = [
        {"Body": stream, "ETag": '"manifest-etag"'},
        TimeoutError("reconciliation read failed"),
    ]
    s3.put_object.side_effect = TimeoutError("publication response lost")
    dispatch = MagicMock()
    monkeypatch.setattr(orchestrate, "read_run_lease", read_lease)
    monkeypatch.setattr(orchestrate, "claim_run_lease", claim_lease)
    monkeypatch.setattr(orchestrate, "dispatch_workflow", dispatch)
    monkeypatch.setattr(orchestrate, "_TERMINAL_QUEUE_QUIET_SECONDS", 0)
    monkeypatch.setattr(
        recovery,
        "require_exact_terminal_coverage",
        lambda *args: _one_item_terminal_inventory(),
    )

    with pytest.raises(ManifestPublicationDeliveryUnknownError, match="outcome.*unknown"):
        _finalize_manifest(
            s3,
            _empty_sqs(),
            _submitter_config(),
            "run-1",
            generation,
            terminal_queue_counts=(0, 0, 0),
            expected_lease_owner="run-1",
            expected_lease_created_at=generation,
        )

    assert len(claimants) == 1
    assert claimants[0].startswith("finalize:")
    assert str(lease_state["owner"]).startswith("finalize:")
    dispatch.assert_not_called()


def test_finalize_manifest_returns_finalizer_after_read_proves_put_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aws_batch_scraper import orchestrate, recovery

    generation = datetime(2026, 8, 20, 20, 0, tzinfo=UTC)
    lease_state: dict[str, Any] = {
        "run_id": "run-1",
        "owner": "run-1",
        "created_at": generation,
    }
    claimants: list[str] = []

    def read_lease(*args):
        return MagicMock(**lease_state)

    def claim_lease(s3, config, run_id, claimant, **kwargs):
        assert lease_state["owner"] == kwargs["current_owner"]
        lease_state["owner"] = claimant
        claimants.append(claimant)
        return MagicMock(**lease_state)

    original_body = json.dumps({"run_id": "run-1", "timestamp": generation.isoformat()}).encode()

    def original_manifest():
        stream = MagicMock()
        stream.read.return_value = original_body
        return {"Body": stream, "ETag": '"manifest-etag"'}

    s3 = MagicMock()
    s3.get_object.side_effect = [original_manifest(), original_manifest()]
    s3.put_object.side_effect = TimeoutError("publication response lost")
    dispatch = MagicMock()
    monkeypatch.setattr(orchestrate, "read_run_lease", read_lease)
    monkeypatch.setattr(orchestrate, "claim_run_lease", claim_lease)
    monkeypatch.setattr(orchestrate, "dispatch_workflow", dispatch)
    monkeypatch.setattr(orchestrate, "_TERMINAL_QUEUE_QUIET_SECONDS", 0)
    monkeypatch.setattr(
        recovery,
        "require_exact_terminal_coverage",
        lambda *args: _one_item_terminal_inventory(),
    )

    with pytest.raises(TimeoutError, match="publication response lost"):
        _finalize_manifest(
            s3,
            _empty_sqs(),
            _submitter_config(),
            "run-1",
            generation,
            terminal_queue_counts=(0, 0, 0),
            expected_lease_owner="run-1",
            expected_lease_created_at=generation,
        )

    assert len(claimants) == 2
    assert claimants[0].startswith("finalize:")
    assert claimants[1] == "run-1"
    assert lease_state["owner"] == "run-1"
    dispatch.assert_not_called()
