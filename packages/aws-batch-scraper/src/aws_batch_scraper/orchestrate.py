"""ECS task launch/monitor and run manifest lifecycle."""

import hashlib
import json
import re
import time
from datetime import UTC, datetime
from typing import Any, Literal

from botocore.exceptions import BotoCoreError, ClientError
from loguru import logger
from mypy_boto3_ecs.client import ECSClient
from mypy_boto3_ecs.type_defs import (
    KeyValuePairTypeDef,
    NetworkConfigurationTypeDef,
    TaskDefinitionTypeDef,
    TaskOverrideTypeDef,
    TaskTypeDef,
)
from mypy_boto3_s3.client import S3Client
from mypy_boto3_sqs.client import SQSClient

from aws_batch_scraper.config import (
    SubmitterConfig,
    WorkerConfig,
    require_exact_ecr_image_uri,
    require_exact_fargate_platform,
    require_exact_iam_role_arn,
    require_exact_secret_arn,
    require_github_repository,
    require_github_workflow_file,
    require_split_task_definitions,
)
from aws_batch_scraper.dispatch import (
    WorkflowDispatchDeliveryUnknownError,
    dispatch_workflow,
)
from aws_batch_scraper.ids import make_run_id
from aws_batch_scraper.lease import release_run_lease, renew_run_lease
from aws_batch_scraper.types import WorkItem

_ECS_TERMINAL = {"STOPPED"}
_RUN_TASK_ATTEMPTS = 4
_IMAGE_DIGEST = re.compile(r"^.+@sha256:[0-9a-f]{64}$")
_DISPATCH_TOKEN_NAME = "GITHUB_DISPATCH_TOKEN"
_MONITOR_SAFE_DEFAULT_COMMAND = ["/bin/false"]


class QueueTerminalEvidenceError(RuntimeError):
    """Raised when the main queue cannot be proven fully drained."""


class WorkerLaunchError(RuntimeError):
    """Raised when ECS launches fewer worker tasks than requested."""

    def __init__(
        self,
        launched_task_arns: list[str],
        requested_count: int,
        *,
        launch_ambiguous: bool = False,
    ) -> None:
        self.launched_task_arns = launched_task_arns
        self.requested_count = requested_count
        self.launch_ambiguous = launch_ambiguous
        qualifier = "Launch outcome is unknown; " if launch_ambiguous else ""
        super().__init__(
            f"{qualifier}only confirmed {len(launched_task_arns)}/{requested_count} "
            "requested worker task(s)"
        )


class MonitorLaunchError(RuntimeError):
    """Raised when a monitor launch cannot be proven to have one coordinator."""

    def __init__(self, *, launch_ambiguous: bool) -> None:
        self.launch_ambiguous = launch_ambiguous
        if launch_ambiguous:
            detail = "monitor launch outcome is unknown"
        else:
            detail = "ECS confirmed no monitor task"
        super().__init__(detail)


def write_run_manifest(
    s3: S3Client,
    config: SubmitterConfig,
    run_id: str,
    items: list[WorkItem],
    worker_count: int,
    *,
    selection_mode: Literal["sample", "incremental", "full"],
    candidate_count: int,
) -> None:
    """Write immutable selection provenance and inputs for one submitted run."""
    prefix = f"{config.s3_scraper_prefix}/runs/{run_id}"
    for item in items:
        item.validate()
    item_ids = [item.item_id for item in items]
    if len(set(item_ids)) != len(item_ids):
        raise ValueError("Run input contains duplicate item IDs")
    if selection_mode not in {"sample", "incremental", "full"}:
        raise ValueError(f"Unsupported run selection mode: {selection_mode!r}")
    if not isinstance(candidate_count, int) or isinstance(candidate_count, bool):
        raise ValueError("Run candidate count must be an integer")
    if not items:
        raise ValueError("Run input must contain at least one selected item")
    if candidate_count < len(items):
        raise ValueError("Run candidate count cannot be smaller than its selected input count")
    if selection_mode == "full" and candidate_count != len(items):
        raise ValueError("A full run must select every candidate input")

    manifest = {
        "run_id": run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "selection_mode": selection_mode,
        "candidate_count": candidate_count,
        "input_size": len(items),
        "queue_url": config.sqs_queue_url,
        "worker_count": worker_count,
    }
    s3.put_object(
        Bucket=config.s3_bucket,
        Key=f"{prefix}/manifest.json",
        Body=json.dumps(manifest, indent=2).encode(),
        ContentType="application/json",
    )

    input_jsonl = "\n".join(
        json.dumps(
            {"item_id": item.item_id, **item.extra},
            allow_nan=False,
            separators=(",", ":"),
        )
        for item in items
    )
    s3.put_object(
        Bucket=config.s3_bucket,
        Key=f"{prefix}/input.jsonl",
        Body=input_jsonl.encode(),
    )

    logger.info(f"Wrote run manifest to s3://{config.s3_bucket}/{prefix}/")


def write_task_arns(
    s3: S3Client,
    config: SubmitterConfig,
    run_id: str,
    task_arns: list[str],
) -> None:
    """Persist task ARNs for a run so monitor can poll ECS task status."""
    key = f"{config.s3_scraper_prefix}/runs/{run_id}/tasks.json"
    s3.put_object(
        Bucket=config.s3_bucket,
        Key=key,
        Body=json.dumps({"task_arns": task_arns}).encode(),
        ContentType="application/json",
    )


def get_task_arns(s3: S3Client, config: WorkerConfig, run_id: str) -> list[str]:
    """Read saved task ARNs, failing closed when run/task identity is unavailable."""
    key = f"{config.s3_scraper_prefix}/runs/{run_id}/tasks.json"
    try:
        body = s3.get_object(Bucket=config.s3_bucket, Key=key)["Body"].read()
    except ClientError as exc:
        error_code = str(exc.response.get("Error", {}).get("Code", ""))
        if error_code in {"404", "NoSuchKey", "NotFound"}:
            raise FileNotFoundError(f"Task manifest is missing for run {run_id}") from exc
        raise

    try:
        data: object = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Task manifest for run {run_id} is not valid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Task manifest for run {run_id} must be a JSON object")
    task_arns = data.get("task_arns")
    if not isinstance(task_arns, list) or not task_arns:
        raise ValueError(f"Task manifest for run {run_id} must contain a non-empty task_arns list")
    if any(
        not isinstance(arn, str) or not arn.strip() or not arn.startswith("arn:") or "/" not in arn
        for arn in task_arns
    ):
        raise ValueError(f"Task manifest for run {run_id} contains an invalid task ARN")
    return task_arns


def _network_config(config: SubmitterConfig) -> NetworkConfigurationTypeDef:
    return {
        "awsvpcConfiguration": {
            "assignPublicIp": "ENABLED",
            "subnets": config.ecs_subnet_ids,
            "securityGroups": config.ecs_security_group_ids,
        }
    }


def _ecs_client_token(run_id: str, role: str, index: int = 0) -> str:
    """Return a deterministic token so SDK/network retries cannot duplicate tasks."""
    digest = hashlib.sha256(f"{run_id}\0{role}\0{index}".encode()).hexdigest()
    return f"gv-{role}-{digest[:32]}"


def _retryable_run_task_error(error: Exception) -> bool:
    """Return whether an ECS error leaves the RunTask outcome uncertain."""
    if isinstance(error, ClientError):
        status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        code = str(error.response.get("Error", {}).get("Code", ""))
        return (
            status == 429
            or (isinstance(status, int) and status >= 500)
            or code
            in {
                "RequestLimitExceeded",
                "ServiceUnavailableException",
                "ThrottlingException",
            }
        )
    return isinstance(error, (BotoCoreError, ConnectionError, TimeoutError))


def _base_env_vars(config: SubmitterConfig, run_id: str) -> list[KeyValuePairTypeDef]:
    return [
        {"name": "ENV", "value": "prod"},
        {"name": "RUN_ID", "value": run_id},
        {"name": "AWS_ACCOUNT_ID", "value": config.aws_account_id},
        {"name": "AWS_REGION", "value": str(config.aws_region)},
        {"name": "S3_BUCKET", "value": config.s3_bucket},
        {"name": "S3_SCRAPER_PREFIX", "value": config.s3_scraper_prefix},
        {"name": "SQS_QUEUE_NAME", "value": config.sqs_queue_name},
        {"name": "SQS_DLQ_NAME", "value": config.sqs_dlq_name},
        {"name": "ECS_SUBNET_IDS", "value": ",".join(config.ecs_subnet_ids)},
        {"name": "ECS_SECURITY_GROUP_IDS", "value": ",".join(config.ecs_security_group_ids)},
    ]


def _monitor_env_vars(config: SubmitterConfig, run_id: str) -> list[KeyValuePairTypeDef]:
    """Build a complete submitter config for the clean monitor task definition."""
    expected_image = require_exact_ecr_image_uri(
        config.ecs_expected_image_uri,
        account_id=config.aws_account_id,
        region=config.aws_region,
    )
    expected_task_role = require_exact_iam_role_arn(
        config.ecs_expected_task_role_arn,
        account_id=config.aws_account_id,
        setting_name="ECS_EXPECTED_TASK_ROLE_ARN",
    )
    expected_execution_role = require_exact_iam_role_arn(
        config.ecs_expected_execution_role_arn,
        account_id=config.aws_account_id,
        setting_name="ECS_EXPECTED_EXECUTION_ROLE_ARN",
    )
    expected_monitor_secret = require_exact_secret_arn(
        config.ecs_expected_monitor_secret_arn,
        account_id=config.aws_account_id,
        region=config.aws_region,
        setting_name="ECS_EXPECTED_MONITOR_SECRET_ARN",
    )
    platform_version = require_exact_fargate_platform(config.ecs_platform_version)
    return [
        *_base_env_vars(config, run_id),
        {"name": "ECS_CLUSTER_NAME", "value": config.ecs_cluster_name},
        {"name": "ECS_TASK_DEFINITION", "value": config.ecs_task_definition},
        {
            "name": "ECS_MONITOR_TASK_DEFINITION",
            "value": config.ecs_monitor_task_definition,
        },
        {"name": "ECS_EXPECTED_IMAGE_URI", "value": expected_image},
        {"name": "ECS_EXPECTED_TASK_ROLE_ARN", "value": expected_task_role},
        {
            "name": "ECS_EXPECTED_EXECUTION_ROLE_ARN",
            "value": expected_execution_role,
        },
        {"name": "ECS_EXPECTED_MONITOR_SECRET_ARN", "value": expected_monitor_secret},
        {"name": "ECS_PLATFORM_VERSION", "value": platform_version},
        {"name": "ECS_CONTAINER_NAME", "value": config.ecs_container_name},
        {"name": "ECS_TASK_COUNT", "value": str(config.ecs_task_count)},
    ]


def _task_definition_arn(
    definition: TaskDefinitionTypeDef,
    *,
    requested: str,
    role: str,
) -> str:
    if definition.get("status") != "ACTIVE":
        raise ValueError(f"Resolved {role} task definition must be ACTIVE")
    if "FARGATE" not in definition.get("requiresCompatibilities", []):
        raise ValueError(f"Resolved {role} task definition must be FARGATE-compatible")
    arn = definition.get("taskDefinitionArn")
    if not isinstance(arn, str) or not arn.strip():
        raise ValueError(f"Resolved {role} task definition is missing taskDefinitionArn")
    requested_identity = requested.rsplit("task-definition/", maxsplit=1)[-1]
    resolved_identity = arn.rsplit("task-definition/", maxsplit=1)[-1]
    if requested_identity != resolved_identity:
        raise ValueError(f"ECS resolved {role} task definition {requested!r} as unexpected {arn!r}")
    return arn


def _task_definition_container(
    definition: TaskDefinitionTypeDef,
    *,
    container_name: str,
    role: str,
    temporary_volume_name: str,
) -> dict[str, Any]:
    containers = definition.get("containerDefinitions", [])
    matches = [container for container in containers if container.get("name") == container_name]
    if len(containers) != 1 or len(matches) != 1:
        raise ValueError(
            f"Resolved {role} task definition must contain only one {container_name!r} container"
        )
    for container in containers:
        image = container.get("image")
        if not isinstance(image, str) or not _IMAGE_DIGEST.fullmatch(image):
            raise ValueError(
                f"Every {role} task-definition container image must use an immutable "
                "repository@sha256 digest"
            )
        if container.get("user") != "app":
            raise ValueError(
                f"Every {role} task-definition container must run as the image's app user"
            )
        if container.get("readonlyRootFilesystem") is not True:
            raise ValueError(
                f"Every {role} task-definition container must use a read-only root filesystem"
            )
        if container.get("privileged") is True:
            raise ValueError(f"Every {role} task-definition container must remain unprivileged")
        if container.get("dockerSecurityOptions") not in (None, []):
            raise ValueError(
                f"Every {role} task-definition container must use "
                "Fargate's default security profile"
            )
        if container.get("systemControls") not in (None, []):
            raise ValueError(
                f"Every {role} task-definition container must not override kernel parameters"
            )
        if container.get("repositoryCredentials") not in (None, {}):
            raise ValueError(
                f"Every {role} task-definition container must not fetch repository credentials"
            )
        if container.get("credentialSpecs") not in (None, []):
            raise ValueError(
                f"Every {role} task-definition container must not load credential specs"
            )
        if container.get("firelensConfiguration") not in (None, {}):
            raise ValueError(
                f"Every {role} task-definition container must not configure a log router"
            )
        if container.get("dockerLabels") not in (None, {}):
            raise ValueError(
                f"Every {role} task-definition container must not include opaque labels"
            )
        if container.get("healthCheck") not in (None, {}):
            raise ValueError(
                f"Every {role} task-definition container must not run a static health command"
            )
        if container.get("portMappings") not in (None, []):
            raise ValueError(
                f"Every {role} task-definition container must not expose network ports"
            )
        if container.get("interactive") is True or container.get("pseudoTerminal") is True:
            raise ValueError(f"Every {role} task-definition container must remain noninteractive")
        log_configuration = container.get("logConfiguration")
        if log_configuration not in (None, {}) and (
            not isinstance(log_configuration, dict)
            or log_configuration.get("logDriver") != "awslogs"
            or log_configuration.get("secretOptions") not in (None, [])
        ):
            raise ValueError(
                f"Every {role} task-definition container must use awslogs without secret options"
            )
        if container.get("volumesFrom") not in (None, []):
            raise ValueError(
                f"Every {role} task-definition container must not inherit opaque volumes"
            )
        mount_points = container.get("mountPoints")
        if (
            not isinstance(mount_points, list)
            or len(mount_points) != 1
            or not isinstance(mount_points[0], dict)
            or mount_points[0].get("sourceVolume") != temporary_volume_name
            or mount_points[0].get("containerPath") != "/tmp"
            or mount_points[0].get("readOnly") is not False
        ):
            raise ValueError(
                f"Every {role} task-definition container must mount only a writable /tmp volume"
            )
        linux_parameters = container.get("linuxParameters")
        if not isinstance(linux_parameters, dict):
            raise ValueError(f"Every {role} task-definition linuxParameters value must be a map")
        capabilities = linux_parameters.get("capabilities")
        if not isinstance(capabilities, dict):
            raise ValueError(f"Every {role} task-definition capabilities value must be a map")
        if capabilities.get("add") not in (None, []):
            raise ValueError(
                f"Every {role} task-definition container must not add Linux capabilities"
            )
        if capabilities.get("drop") != ["ALL"]:
            raise ValueError(
                f"Every {role} task-definition container must drop every Linux capability"
            )
        for unsupported in ("devices", "tmpfs"):
            if linux_parameters.get(unsupported) not in (None, []):
                raise ValueError(
                    f"Every {role} task-definition container must not configure {unsupported}"
                )
    selected = matches[0]
    if selected.get("entryPoint"):
        raise ValueError(f"Resolved {role} container must not override the image entry point")
    command = selected.get("command")
    if role == "worker" and command:
        raise ValueError("Resolved worker container must use the image's default worker command")
    if role == "monitor" and command != _MONITOR_SAFE_DEFAULT_COMMAND:
        raise ValueError(
            "Resolved monitor container must default to ['/bin/false'] so a direct "
            "no-override launch cannot start the browser with the dispatch token"
        )
    # TypedDict is a structural mapping at runtime; a plain dict keeps the
    # contract helper independent of boto-stub input/output union variants.
    return dict(selected)


def _task_definition_temporary_volume(
    definition: TaskDefinitionTypeDef,
    *,
    role: str,
) -> str:
    """Require one ephemeral volume that cannot replace scanned image content."""
    if definition.get("networkMode") != "awsvpc":
        raise ValueError(f"Resolved {role} task definition must use awsvpc networking")
    runtime_platform = definition.get("runtimePlatform")
    if (
        not isinstance(runtime_platform, dict)
        or runtime_platform.get("operatingSystemFamily") != "LINUX"
        or runtime_platform.get("cpuArchitecture") != "X86_64"
    ):
        raise ValueError(
            f"Resolved {role} task definition must target the reviewed LINUX/X86_64 platform"
        )
    volumes = definition.get("volumes")
    if not isinstance(volumes, list) or len(volumes) != 1 or not isinstance(volumes[0], dict):
        raise ValueError(f"Resolved {role} task definition must declare one temporary volume")
    volume = volumes[0]
    name = volume.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"Resolved {role} task definition temporary volume must have a name")
    if volume.get("configuredAtLaunch") is True or any(
        volume.get(setting) not in (None, {})
        for setting in (
            "dockerVolumeConfiguration",
            "efsVolumeConfiguration",
            "fsxWindowsFileServerVolumeConfiguration",
            "host",
        )
    ):
        raise ValueError(
            f"Resolved {role} task definition /tmp volume must be ephemeral task storage"
        )
    return name


def _validate_cluster(ecs: ECSClient, config: SubmitterConfig) -> None:
    response = ecs.describe_clusters(clusters=[config.ecs_cluster_name])
    failures = response.get("failures", [])
    clusters = response.get("clusters", [])
    if failures or len(clusters) != 1:
        raise ValueError(f"ECS cluster {config.ecs_cluster_name!r} could not be resolved exactly")
    cluster = clusters[0]
    if cluster.get("status") != "ACTIVE":
        raise ValueError(f"ECS cluster {config.ecs_cluster_name!r} must be ACTIVE")
    if cluster.get("clusterArn") != config.ecs_cluster_arn:
        raise ValueError(f"ECS resolved an unexpected cluster for {config.ecs_cluster_name!r}")


def _container_setting_names(
    definition: TaskDefinitionTypeDef,
    setting: str,
) -> set[str]:
    names: set[str] = set()
    for container in definition.get("containerDefinitions", []):
        entries = container.get(setting, [])
        if not isinstance(entries, list):
            raise ValueError(f"ECS task-definition {setting} must be a list")
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance((name := entry.get("name")), str):
                raise ValueError(f"ECS task-definition {setting} contains a malformed entry")
            names.add(name)
    return names


def resolve_split_task_definitions(
    ecs: ECSClient,
    config: SubmitterConfig,
) -> tuple[str, str]:
    """Resolve and verify immutable, secret-separated worker/monitor definitions."""
    worker, monitor = require_split_task_definitions(
        config.ecs_task_definition,
        config.ecs_monitor_task_definition,
    )
    expected_image = require_exact_ecr_image_uri(
        config.ecs_expected_image_uri,
        account_id=config.aws_account_id,
        region=config.aws_region,
    )
    expected_task_role = require_exact_iam_role_arn(
        config.ecs_expected_task_role_arn,
        account_id=config.aws_account_id,
        setting_name="ECS_EXPECTED_TASK_ROLE_ARN",
    )
    expected_execution_role = require_exact_iam_role_arn(
        config.ecs_expected_execution_role_arn,
        account_id=config.aws_account_id,
        setting_name="ECS_EXPECTED_EXECUTION_ROLE_ARN",
    )
    expected_monitor_secret = require_exact_secret_arn(
        config.ecs_expected_monitor_secret_arn,
        account_id=config.aws_account_id,
        region=config.aws_region,
        setting_name="ECS_EXPECTED_MONITOR_SECRET_ARN",
    )
    require_exact_fargate_platform(config.ecs_platform_version)
    _validate_cluster(ecs, config)
    worker_definition = ecs.describe_task_definition(taskDefinition=worker)["taskDefinition"]
    monitor_definition = ecs.describe_task_definition(taskDefinition=monitor)["taskDefinition"]

    worker_arn = _task_definition_arn(
        worker_definition,
        requested=worker,
        role="worker",
    )
    monitor_arn = _task_definition_arn(
        monitor_definition,
        requested=monitor,
        role="monitor",
    )
    if worker_arn == monitor_arn:
        raise ValueError("ECS resolved worker and monitor to the same task definition")
    for definition, role in (
        (worker_definition, "worker"),
        (monitor_definition, "monitor"),
    ):
        if definition.get("taskRoleArn") != expected_task_role:
            raise ValueError(f"Resolved {role} task definition must use the reviewed task role")
        if definition.get("executionRoleArn") != expected_execution_role:
            raise ValueError(
                f"Resolved {role} task definition must use the reviewed execution role"
            )

    worker_temporary_volume = _task_definition_temporary_volume(
        worker_definition,
        role="worker",
    )
    monitor_temporary_volume = _task_definition_temporary_volume(
        monitor_definition,
        role="monitor",
    )
    worker_container = _task_definition_container(
        worker_definition,
        container_name=config.ecs_container_name,
        role="worker",
        temporary_volume_name=worker_temporary_volume,
    )
    monitor_container = _task_definition_container(
        monitor_definition,
        container_name=config.ecs_container_name,
        role="monitor",
        temporary_volume_name=monitor_temporary_volume,
    )
    if worker_container["image"] != monitor_container["image"]:
        raise ValueError("Worker and monitor task definitions must use the same image digest")
    if worker_container["image"] != expected_image:
        raise ValueError("Worker and monitor task definitions must use ECS_EXPECTED_IMAGE_URI")

    worker_secrets = _container_setting_names(worker_definition, "secrets")
    worker_environment = _container_setting_names(worker_definition, "environment")
    if any(
        container.get("environmentFiles") for container in worker_definition["containerDefinitions"]
    ):
        raise ValueError("Worker task definition must not use opaque environment files")
    if worker_secrets:
        raise ValueError("Worker task definition must not include any ECS secrets")
    if worker_environment:
        raise ValueError("Worker task definition must not include static environment values")

    monitor_environment = _container_setting_names(monitor_definition, "environment")
    if any(
        container.get("environmentFiles")
        for container in monitor_definition["containerDefinitions"]
    ):
        raise ValueError("Monitor task definition must not use opaque environment files")
    monitor_secrets = monitor_container.get("secrets")
    if monitor_environment:
        raise ValueError("Monitor task definition must not include static environment values")
    if (
        not isinstance(monitor_secrets, list)
        or len(monitor_secrets) != 1
        or not isinstance(monitor_secrets[0], dict)
        or set(monitor_secrets[0]) != {"name", "valueFrom"}
        or monitor_secrets[0].get("name") != _DISPATCH_TOKEN_NAME
        or monitor_secrets[0].get("valueFrom") != expected_monitor_secret
    ):
        raise ValueError(
            "Monitor task definition must inject only GITHUB_DISPATCH_TOKEN from the reviewed "
            "ECS secret"
        )

    return worker, monitor


def launch_workers(
    ecs: ECSClient,
    config: SubmitterConfig,
    run_id: str,
    worker_count: int | None = None,
    force_rescrape: bool = False,
    soft_blocked_delay_max: int | None = None,
) -> list[str]:
    """Start Fargate tasks. Returns task ARNs.

    All workers are requested in one idempotent ECS call. This avoids a series
    of individually successful calls becoming an untrackable partial launch.
    Each task runs the image's default CMD with no command override.
    Environment variables carry the run_id and queue/S3 coordinates.
    """
    n = worker_count if worker_count is not None else config.ecs_task_count
    if not 1 <= n <= 10:
        raise ValueError("ECS worker count must be between 1 and 10")
    task_definition, _ = resolve_split_task_definitions(ecs, config)
    platform_version = require_exact_fargate_platform(config.ecs_platform_version)
    logger.info(f"Using exact worker task definition revision: {task_definition}")

    env_vars = _base_env_vars(config, run_id)
    # Compatibility for an older worker image during a rolling deployment.
    # Current workers intentionally ignore this global value and trust the
    # message-scoped force_rescrape field instead.
    env_vars.append({"name": "FORCE_RESCRAPE", "value": "1" if force_rescrape else "0"})
    if soft_blocked_delay_max is not None:
        delay_min = min(60, soft_blocked_delay_max)
        env_vars += [
            {"name": "SOFT_BLOCKED_DELAY_MIN", "value": str(delay_min)},
            {"name": "SOFT_BLOCKED_DELAY_MAX", "value": str(soft_blocked_delay_max)},
        ]

    overrides: TaskOverrideTypeDef = {
        "containerOverrides": [
            {
                "name": config.ecs_container_name,
                "environment": env_vars,
            }
        ]
    }
    response = None
    for attempt in range(1, _RUN_TASK_ATTEMPTS + 1):
        logger.info(f"Launching {n} worker(s), attempt {attempt}/{_RUN_TASK_ATTEMPTS}")
        try:
            response = ecs.run_task(
                clientToken=_ecs_client_token(run_id, "worker"),
                count=n,
                taskDefinition=task_definition,
                cluster=config.ecs_cluster_arn,
                networkConfiguration=_network_config(config),
                launchType="FARGATE",
                platformVersion=platform_version,
                overrides=overrides,
            )
        except Exception as exc:
            if not _retryable_run_task_error(exc):
                raise WorkerLaunchError([], n) from exc
            if attempt == _RUN_TASK_ATTEMPTS:
                # Every retry used the same client token, so a task set may
                # exist even though no response reached us. Never release the
                # run lease based on an unprovable zero-task assumption.
                raise WorkerLaunchError([], n, launch_ambiguous=True) from exc
            logger.warning(f"ECS RunTask outcome is uncertain; retrying: {exc}")
            time.sleep(min(2 ** (attempt - 1), 4))
        else:
            break

    if response is None:  # defensive: the retry loop either returns or raises
        raise RuntimeError("ECS RunTask produced no response")

    tasks = response.get("tasks", [])
    task_arns = [
        task_arn
        for task in tasks
        if isinstance(task_arn := task.get("taskArn"), str)
        and task_arn.strip()
        and task_arn.startswith("arn:")
        and "/" in task_arn
    ]
    if len(task_arns) != len(tasks) or len(set(task_arns)) != len(task_arns):
        raise WorkerLaunchError(task_arns, n, launch_ambiguous=True)

    for failure in response.get("failures", []):
        logger.warning(f"Worker failed to launch: {failure.get('reason', 'unknown')}")

    if len(task_arns) != n:
        raise WorkerLaunchError(task_arns, n)

    logger.info(f"Launched {len(task_arns)}/{n} workers")
    return task_arns


def launch_monitor(
    ecs: ECSClient,
    config: SubmitterConfig,
    run_id: str,
    monitor_command: list[str],
) -> str:
    """Start one Fargate coordinator task that waits for a run and dispatches processing.

    Parameters
    ----------
    monitor_command
        Full command to override the container CMD, e.g.:
        ``["my-etl-tool", "scraper", "monitor", "--run-id", run_id]``
    """
    repository = require_github_repository(config.github_repository)
    workflow_file = require_github_workflow_file(config.github_workflow_file)
    _, task_definition = resolve_split_task_definitions(ecs, config)
    platform_version = require_exact_fargate_platform(config.ecs_platform_version)
    logger.info(f"Using exact monitor task definition revision: {task_definition}")
    env_vars = _monitor_env_vars(config, run_id)
    env_vars.append({"name": "GITHUB_REPOSITORY", "value": repository})
    env_vars.append({"name": "GITHUB_WORKFLOW_FILE", "value": workflow_file})

    overrides: TaskOverrideTypeDef = {
        "containerOverrides": [
            {
                "name": config.ecs_container_name,
                "command": monitor_command,
                "environment": env_vars,
            }
        ]
    }
    response = None
    for attempt in range(1, _RUN_TASK_ATTEMPTS + 1):
        logger.info(f"Launching monitor, attempt {attempt}/{_RUN_TASK_ATTEMPTS}")
        try:
            response = ecs.run_task(
                clientToken=_ecs_client_token(run_id, "monitor"),
                taskDefinition=task_definition,
                cluster=config.ecs_cluster_arn,
                networkConfiguration=_network_config(config),
                launchType="FARGATE",
                platformVersion=platform_version,
                overrides=overrides,
            )
        except Exception as exc:
            if not _retryable_run_task_error(exc):
                raise MonitorLaunchError(launch_ambiguous=False) from exc
            if attempt == _RUN_TASK_ATTEMPTS:
                raise MonitorLaunchError(launch_ambiguous=True) from exc
            logger.warning(f"ECS monitor RunTask outcome is uncertain; retrying: {exc}")
            time.sleep(min(2 ** (attempt - 1), 4))
        else:
            break

    if response is None:  # defensive: the retry loop either returns or raises
        raise RuntimeError("ECS monitor RunTask produced no response")

    tasks = response.get("tasks", [])
    failures = response.get("failures", [])
    if len(tasks) != 1 or failures:
        for failure in failures:
            logger.warning(f"Monitor failed to launch: {failure.get('reason', 'unknown')}")
        raise MonitorLaunchError(launch_ambiguous=bool(tasks))
    task_arn = tasks[0].get("taskArn")
    if (
        not isinstance(task_arn, str)
        or not task_arn.strip()
        or not task_arn.startswith("arn:")
        or "/" not in task_arn
    ):
        raise MonitorLaunchError(launch_ambiguous=True)
    logger.info(f"Launched monitor task for run {run_id}: {task_arn}")
    return task_arn


def monitor_run(
    ecs: ECSClient,
    sqs: SQSClient,
    s3: S3Client,
    config: SubmitterConfig,
    run_id: str,
    *,
    poll_interval: int = 30,
) -> None:
    """Block until all ECS tasks for run_id have stopped, then finalize the manifest."""
    _monitor_run(ecs, sqs, s3, config, run_id, poll_interval=poll_interval)


def _release_terminal_monitor_failure(
    s3: S3Client,
    config: SubmitterConfig,
    run_id: str,
    error: Exception,
) -> None:
    """Release after work is known terminal without masking its original error."""
    try:
        released = release_run_lease(
            s3,
            config,
            run_id,
            terminal_status="failure",
            detail=str(error),
        )
        if not released:
            logger.error(f"Terminal run {run_id} no longer owns its active-run lease")
    except Exception:
        logger.exception(f"Failed to release active-run lease for terminal run {run_id}")


def _record_unknown_dispatch_delivery(
    s3: S3Client,
    config: SubmitterConfig,
    run_id: str,
    error: WorkflowDispatchDeliveryUnknownError,
) -> None:
    """Retain the lease and evidence when GitHub may be processing the event."""
    key = f"{config.s3_scraper_prefix}/runs/{run_id}/dispatch-ambiguous.json"
    record = {
        "run_id": run_id,
        "recorded_at": datetime.now(UTC).isoformat(),
        "detail": str(error),
        "lease_action": "retained",
    }
    try:
        s3.put_object(
            Bucket=config.s3_bucket,
            Key=key,
            Body=json.dumps(record, indent=2).encode(),
            ContentType="application/json",
        )
    except Exception:
        logger.exception(f"Could not persist ambiguous workflow dispatch evidence for {run_id}")
    logger.error(f"Workflow dispatch delivery for {run_id} is unknown; retaining its active lease")


def _record_monitor_recovery(
    s3: S3Client,
    config: SubmitterConfig,
    run_id: str,
    error: Exception,
) -> None:
    """Persist fail-closed terminal-queue evidence while retaining the lease."""
    key = f"{config.s3_scraper_prefix}/runs/{run_id}/monitor-recovery.json"
    record = {
        "run_id": run_id,
        "recorded_at": datetime.now(UTC).isoformat(),
        "detail": str(error),
        "lease_action": "retained",
    }
    try:
        s3.put_object(
            Bucket=config.s3_bucket,
            Key=key,
            Body=json.dumps(record, indent=2).encode(),
            ContentType="application/json",
        )
    except Exception:
        logger.exception(f"Could not persist monitor recovery evidence for {run_id}")
    logger.error(f"Run {run_id} lacks terminal queue evidence; retaining its active lease")


def _monitor_run(
    ecs: ECSClient,
    sqs: SQSClient,
    s3: S3Client,
    config: SubmitterConfig,
    run_id: str,
    *,
    poll_interval: int,
) -> None:
    """Monitor implementation wrapped by terminal-failure lease handling."""
    task_arns = get_task_arns(s3, config, run_id)
    started_at = datetime.now(UTC)
    logger.info(f"Monitoring {len(task_arns)} task(s) for run {run_id}...")

    while True:
        renew_run_lease(s3, config, run_id)
        response = ecs.describe_tasks(cluster=config.ecs_cluster_arn, tasks=task_arns)
        failures = response.get("failures", [])
        if failures:
            raise RuntimeError(f"ECS failed to describe run tasks: {failures}")
        tasks = response.get("tasks", [])
        described_arns = {
            task_arn
            for task in tasks
            if isinstance(task_arn := task.get("taskArn"), str) and task_arn
        }
        missing_arns = set(task_arns).difference(described_arns)
        if missing_arns:
            missing = ", ".join(sorted(missing_arns))
            raise RuntimeError(f"ECS omitted {len(missing_arns)} run task(s): {missing}")
        statuses = {t["taskArn"].split("/")[-1]: t["lastStatus"] for t in tasks}
        running = [arn for arn, s in statuses.items() if s not in _ECS_TERMINAL]

        status_summary = ", ".join(
            f"{status}:{sum(1 for value in statuses.values() if value == status)}"
            for status in sorted(set(statuses.values()))
        )
        logger.info(f"Tasks: {status_summary} — {len(running)} still running")

        if not running:
            try:
                terminal_queue_counts = _require_empty_main_queue(sqs, config)
                _assert_tasks_succeeded(tasks)
                logger.info("All tasks stopped and queue is empty — run complete")
                _finalize_manifest(
                    s3,
                    sqs,
                    config,
                    run_id,
                    started_at,
                    terminal_queue_counts=terminal_queue_counts,
                )
                return
            except WorkflowDispatchDeliveryUnknownError as exc:
                _record_unknown_dispatch_delivery(s3, config, run_id, exc)
                raise
            except QueueTerminalEvidenceError as exc:
                _record_monitor_recovery(s3, config, run_id, exc)
                raise
            except Exception as exc:
                _release_terminal_monitor_failure(s3, config, run_id, exc)
                raise

        time.sleep(poll_interval)


def monitor_until_empty(
    sqs: SQSClient,
    config: WorkerConfig,
    *,
    poll_interval: int = 60,
    s3: S3Client | None = None,
    run_id: str | None = None,
) -> None:
    """Block until visible, in-flight, and delayed message counts reach zero."""
    started_at = datetime.now(UTC)
    logger.info("Monitoring queue until empty...")

    while True:
        if s3 is not None and run_id is not None and isinstance(config, SubmitterConfig):
            renew_run_lease(s3, config, run_id)
        visible, in_flight, delayed = _queue_depth(sqs, config)
        logger.info(f"Queue: {visible} visible, {in_flight} in-flight, {delayed} delayed")

        if visible == 0 and in_flight == 0 and delayed == 0:
            logger.info("Queue empty — run complete")
            if s3 is not None and run_id is not None and isinstance(config, SubmitterConfig):
                try:
                    _finalize_manifest(
                        s3,
                        sqs,
                        config,
                        run_id,
                        started_at,
                        terminal_queue_counts=(visible, in_flight, delayed),
                    )
                except WorkflowDispatchDeliveryUnknownError as exc:
                    _record_unknown_dispatch_delivery(s3, config, run_id, exc)
                    raise
                except QueueTerminalEvidenceError as exc:
                    _record_monitor_recovery(s3, config, run_id, exc)
                    raise
                except Exception as exc:
                    _release_terminal_monitor_failure(s3, config, run_id, exc)
                    raise
            return

        time.sleep(poll_interval)


def _queue_depth(sqs: SQSClient, config: WorkerConfig) -> tuple[int, int, int]:
    """Return visible, in-flight, and delayed counts for the main queue."""
    attrs = sqs.get_queue_attributes(
        QueueUrl=config.sqs_queue_url,
        AttributeNames=[
            "ApproximateNumberOfMessages",
            "ApproximateNumberOfMessagesNotVisible",
            "ApproximateNumberOfMessagesDelayed",
        ],
    )["Attributes"]
    return (
        int(attrs["ApproximateNumberOfMessages"]),
        int(attrs["ApproximateNumberOfMessagesNotVisible"]),
        int(attrs["ApproximateNumberOfMessagesDelayed"]),
    )


def _require_empty_main_queue(
    sqs: SQSClient,
    config: WorkerConfig,
) -> tuple[int, int, int]:
    """Return terminal counts only when all main-queue states are proven empty."""
    try:
        visible, in_flight, delayed = _queue_depth(sqs, config)
    except Exception as exc:
        raise QueueTerminalEvidenceError("Could not read all main-queue counts") from exc
    if visible or in_flight or delayed:
        raise QueueTerminalEvidenceError(
            f"Main queue is not empty: {visible} visible, {in_flight} in-flight, {delayed} delayed"
        )
    return visible, in_flight, delayed


def _assert_tasks_succeeded(tasks: list[TaskTypeDef]) -> None:
    """Raise if any stopped ECS task or essential container ended unsuccessfully."""
    failures: list[str] = []
    for task in tasks:
        task_id = str(task.get("taskArn", "unknown")).split("/")[-1]
        stop_code = task.get("stopCode")
        stopped_reason = task.get("stoppedReason")
        if stop_code and stop_code != "EssentialContainerExited":
            failures.append(f"{task_id}: stopCode={stop_code}, reason={stopped_reason}")

        essential_containers = [
            container
            for container in task.get("containers", [])
            if container.get("essential", True)
        ]
        if not essential_containers:
            failures.append(f"{task_id}: stopped task has no essential container status")

        for container in essential_containers:
            exit_code = container.get("exitCode")
            reason = container.get("reason")
            name = container.get("name", "container")
            if exit_code is None:
                failures.append(f"{task_id}/{name}: missing exitCode, reason={reason}")
            elif exit_code != 0:
                failures.append(f"{task_id}/{name}: exitCode={exit_code}, reason={reason}")

    if failures:
        details = "; ".join(failures)
        raise RuntimeError(f"One or more worker tasks failed: {details}")


def _finalize_manifest(
    s3: S3Client,
    sqs: SQSClient,
    config: SubmitterConfig,
    run_id: str,
    monitor_started_at: datetime,
    *,
    terminal_queue_counts: tuple[int, int, int] | None = None,
) -> None:
    """Append completion fields to the run manifest and fire workflow dispatch."""
    manifest_key = f"{config.s3_scraper_prefix}/runs/{run_id}/manifest.json"
    try:
        body = s3.get_object(Bucket=config.s3_bucket, Key=manifest_key)["Body"].read()
    except ClientError as exc:
        error_code = str(exc.response.get("Error", {}).get("Code", ""))
        if error_code not in {"404", "NoSuchKey", "NotFound"}:
            raise
        logger.warning(f"No manifest found for legacy run {run_id}; creating a minimal record")
        manifest: dict[str, Any] = {"run_id": run_id}
    else:
        try:
            decoded: object = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(f"Run manifest for {run_id} is not valid JSON") from exc
        if not isinstance(decoded, dict):
            raise ValueError(f"Run manifest for {run_id} must be a JSON object")
        manifest = decoded

    if terminal_queue_counts is None:
        terminal_queue_counts = _require_empty_main_queue(sqs, config)
    visible, in_flight, delayed = terminal_queue_counts
    if visible or in_flight or delayed:
        raise QueueTerminalEvidenceError(
            "Provided terminal queue counts are not empty: "
            f"{visible} visible, {in_flight} in-flight, {delayed} delayed"
        )

    completed_at = datetime.now(UTC)
    run_start_str = manifest.get("timestamp")
    if run_start_str:
        try:
            run_start = datetime.fromisoformat(run_start_str)
            total_runtime_seconds = round((completed_at - run_start).total_seconds(), 1)
        except ValueError:
            total_runtime_seconds = round((completed_at - monitor_started_at).total_seconds(), 1)
    else:
        total_runtime_seconds = round((completed_at - monitor_started_at).total_seconds(), 1)

    dlq_depth: int | None = None
    try:
        dlq_attrs = sqs.get_queue_attributes(
            QueueUrl=config.sqs_dlq_url,
            AttributeNames=["ApproximateNumberOfMessages"],
        )["Attributes"]
        dlq_depth = int(dlq_attrs["ApproximateNumberOfMessages"])
    except Exception:
        logger.warning("Could not read DLQ depth")

    manifest["completed_at"] = completed_at.isoformat()
    manifest["total_runtime_seconds"] = total_runtime_seconds
    manifest["terminal_queue_counts"] = {
        "visible": visible,
        "in_flight": in_flight,
        "delayed": delayed,
    }
    if dlq_depth is not None:
        manifest["dlq_depth"] = dlq_depth

    s3.put_object(
        Bucket=config.s3_bucket,
        Key=manifest_key,
        Body=json.dumps(manifest, indent=2).encode(),
        ContentType="application/json",
    )
    logger.info(f"Manifest finalized: runtime={total_runtime_seconds}s, dlq_depth={dlq_depth}")
    dispatch_workflow(
        run_id,
        repository=config.github_repository,
        workflow_file=config.github_workflow_file,
    )


__all__ = [
    "make_run_id",
    "WorkerLaunchError",
    "MonitorLaunchError",
    "write_run_manifest",
    "write_task_arns",
    "get_task_arns",
    "resolve_split_task_definitions",
    "launch_workers",
    "launch_monitor",
    "monitor_run",
    "monitor_until_empty",
]
