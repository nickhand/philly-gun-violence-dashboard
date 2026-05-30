"""ECS task launch/monitor and run manifest lifecycle."""

import json
import time
from datetime import UTC, datetime
from typing import Any

from loguru import logger
from mypy_boto3_ecs.client import ECSClient
from mypy_boto3_ecs.type_defs import (
    KeyValuePairTypeDef,
    NetworkConfigurationTypeDef,
    TaskOverrideTypeDef,
    TaskTypeDef,
)
from mypy_boto3_s3.client import S3Client
from mypy_boto3_sqs.client import SQSClient

from aws_batch_scraper.config import SubmitterConfig, WorkerConfig
from aws_batch_scraper.dispatch import dispatch_workflow
from aws_batch_scraper.ids import make_run_id
from aws_batch_scraper.types import WorkItem

_ECS_TERMINAL = {"STOPPED", "DEPROVISIONING"}


class WorkerLaunchError(RuntimeError):
    """Raised when ECS launches fewer worker tasks than requested."""

    def __init__(self, launched_task_arns: list[str], requested_count: int) -> None:
        self.launched_task_arns = launched_task_arns
        self.requested_count = requested_count
        super().__init__(
            f"Only launched {len(launched_task_arns)}/{requested_count} requested worker task(s)"
        )


def write_run_manifest(
    s3: S3Client,
    config: SubmitterConfig,
    run_id: str,
    items: list[WorkItem],
    worker_count: int,
) -> None:
    """Write manifest.json and input.jsonl to {s3_scraper_prefix}/runs/{run_id}/."""
    prefix = f"{config.s3_scraper_prefix}/runs/{run_id}"

    manifest = {
        "run_id": run_id,
        "timestamp": datetime.now(UTC).isoformat(),
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

    input_jsonl = "\n".join(json.dumps({"item_id": item.item_id, **item.extra}) for item in items)
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
    """Read task ARNs saved by write_task_arns. Returns [] if not found."""
    key = f"{config.s3_scraper_prefix}/runs/{run_id}/tasks.json"
    try:
        body = s3.get_object(Bucket=config.s3_bucket, Key=key)["Body"].read()
        data: dict[str, Any] = json.loads(body)
        task_arns = data.get("task_arns", [])
        if not isinstance(task_arns, list):
            return []
        return [arn for arn in task_arns if isinstance(arn, str)]
    except Exception:
        return []


def _network_config(config: SubmitterConfig) -> NetworkConfigurationTypeDef:
    return {
        "awsvpcConfiguration": {
            "assignPublicIp": "ENABLED",
            "subnets": config.ecs_subnet_ids,
            "securityGroups": config.ecs_security_group_ids,
        }
    }


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


def launch_workers(
    ecs: ECSClient,
    config: SubmitterConfig,
    run_id: str,
    worker_count: int | None = None,
    force_rescrape: bool = False,
    soft_blocked_delay_max: int | None = None,
) -> list[str]:
    """Start Fargate tasks. Returns task ARNs.

    Each task runs the image's default CMD with no command override.
    Environment variables carry the run_id and queue/S3 coordinates.
    """
    n = worker_count if worker_count is not None else config.ecs_task_count
    task_definition = config.ecs_task_definition
    logger.info(f"Using task definition (latest revision): {task_definition}")

    env_vars = _base_env_vars(config, run_id)
    env_vars.append({"name": "FORCE_RESCRAPE", "value": "1" if force_rescrape else "0"})
    if soft_blocked_delay_max is not None:
        delay_min = min(60, soft_blocked_delay_max)
        env_vars += [
            {"name": "SOFT_BLOCKED_DELAY_MIN", "value": str(delay_min)},
            {"name": "SOFT_BLOCKED_DELAY_MAX", "value": str(soft_blocked_delay_max)},
        ]

    task_arns: list[str] = []
    for i in range(n):
        logger.info(f"Launching worker {i + 1}/{n}")
        overrides: TaskOverrideTypeDef = {
            "containerOverrides": [
                {
                    "name": config.ecs_container_name,
                    "environment": env_vars,
                }
            ]
        }
        response = ecs.run_task(
            taskDefinition=task_definition,
            cluster=config.ecs_cluster_arn,
            networkConfiguration=_network_config(config),
            launchType="FARGATE",
            overrides=overrides,
        )
        if response["tasks"]:
            task_arns.append(response["tasks"][0]["taskArn"])
        elif response.get("failures"):
            reason = response["failures"][0].get("reason", "unknown")
            logger.warning(f"Worker {i + 1} failed to launch: {reason}")

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
        ``["uv", "run", "my-etl-tool", "scraper", "monitor", "--run-id", run_id]``
    """
    env_vars = _base_env_vars(config, run_id)
    if repository := config.github_repository:
        env_vars.append({"name": "GITHUB_REPOSITORY", "value": repository})

    overrides: TaskOverrideTypeDef = {
        "containerOverrides": [
            {
                "name": config.ecs_container_name,
                "command": monitor_command,
                "environment": env_vars,
            }
        ]
    }
    response = ecs.run_task(
        taskDefinition=config.ecs_task_definition,
        cluster=config.ecs_cluster_arn,
        networkConfiguration=_network_config(config),
        launchType="FARGATE",
        overrides=overrides,
    )
    if response["tasks"]:
        task_arn = response["tasks"][0]["taskArn"]
        logger.info(f"Launched monitor task for run {run_id}: {task_arn}")
        return task_arn
    failures = response.get("failures", [])
    raise RuntimeError(f"Failed to launch monitor task for run {run_id}: {failures}")


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
    task_arns = get_task_arns(s3, config, run_id)
    if not task_arns:
        logger.warning(f"No task ARNs found for run {run_id} — falling back to queue-depth monitor")
        monitor_until_empty(sqs, config, s3=s3, run_id=run_id, poll_interval=poll_interval)
        return

    started_at = datetime.now(UTC)
    logger.info(f"Monitoring {len(task_arns)} task(s) for run {run_id}...")

    while True:
        response = ecs.describe_tasks(cluster=config.ecs_cluster_arn, tasks=task_arns)
        failures = response.get("failures", [])
        if failures:
            raise RuntimeError(f"ECS failed to describe run tasks: {failures}")
        tasks = response.get("tasks", [])
        statuses = {t["taskArn"].split("/")[-1]: t["lastStatus"] for t in tasks}
        running = [arn for arn, s in statuses.items() if s not in _ECS_TERMINAL]

        status_summary = ", ".join(
            f"{status}:{sum(1 for value in statuses.values() if value == status)}"
            for status in sorted(set(statuses.values()))
        )
        logger.info(f"Tasks: {status_summary} — {len(running)} still running")

        if not running:
            _assert_tasks_succeeded(tasks)
            visible, in_flight = _queue_depth(sqs, config)
            if visible or in_flight:
                raise RuntimeError(
                    "All worker tasks stopped but queue is not empty: "
                    f"{visible} visible, {in_flight} in-flight"
                )
            logger.info("All tasks stopped and queue is empty — run complete")
            _finalize_manifest(s3, sqs, config, run_id, started_at)
            return

        time.sleep(poll_interval)


def monitor_until_empty(
    sqs: SQSClient,
    config: WorkerConfig,
    *,
    poll_interval: int = 60,
    s3: S3Client | None = None,
    run_id: str | None = None,
) -> None:
    """Block until both visible and in-flight message counts reach zero."""
    started_at = datetime.now(UTC)
    logger.info("Monitoring queue until empty...")

    while True:
        visible, in_flight = _queue_depth(sqs, config)
        logger.info(f"Queue: {visible} visible, {in_flight} in-flight")

        if visible == 0 and in_flight == 0:
            logger.info("Queue empty — run complete")
            if s3 is not None and run_id is not None and isinstance(config, SubmitterConfig):
                _finalize_manifest(s3, sqs, config, run_id, started_at)
            return

        time.sleep(poll_interval)


def _queue_depth(sqs: SQSClient, config: WorkerConfig) -> tuple[int, int]:
    """Return visible and in-flight message counts for the main queue."""
    attrs = sqs.get_queue_attributes(
        QueueUrl=config.sqs_queue_url,
        AttributeNames=[
            "ApproximateNumberOfMessages",
            "ApproximateNumberOfMessagesNotVisible",
        ],
    )["Attributes"]
    return int(attrs["ApproximateNumberOfMessages"]), int(
        attrs["ApproximateNumberOfMessagesNotVisible"]
    )


def _assert_tasks_succeeded(tasks: list[TaskTypeDef]) -> None:
    """Raise if any stopped ECS task or essential container ended unsuccessfully."""
    failures: list[str] = []
    for task in tasks:
        task_id = str(task.get("taskArn", "unknown")).split("/")[-1]
        stop_code = task.get("stopCode")
        stopped_reason = task.get("stoppedReason")
        if stop_code and stop_code != "EssentialContainerExited":
            failures.append(f"{task_id}: stopCode={stop_code}, reason={stopped_reason}")

        for container in task.get("containers", []):
            if not container.get("essential", True):
                continue
            exit_code = container.get("exitCode")
            reason = container.get("reason")
            if exit_code not in (None, 0):
                name = container.get("name", "container")
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
) -> None:
    """Append completion fields to the run manifest and fire workflow dispatch."""
    manifest_key = f"{config.s3_scraper_prefix}/runs/{run_id}/manifest.json"
    try:
        body = s3.get_object(Bucket=config.s3_bucket, Key=manifest_key)["Body"].read()
        manifest: dict[str, Any] = json.loads(body)
    except Exception:
        logger.warning(f"Could not read manifest for run {run_id}, creating minimal record")
        manifest = {"run_id": run_id}

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
    if dlq_depth is not None:
        manifest["dlq_depth"] = dlq_depth

    s3.put_object(
        Bucket=config.s3_bucket,
        Key=manifest_key,
        Body=json.dumps(manifest, indent=2).encode(),
        ContentType="application/json",
    )
    logger.info(f"Manifest finalized: runtime={total_runtime_seconds}s, dlq_depth={dlq_depth}")
    dispatch_workflow(run_id)


__all__ = [
    "make_run_id",
    "WorkerLaunchError",
    "write_run_manifest",
    "write_task_arns",
    "get_task_arns",
    "launch_workers",
    "launch_monitor",
    "monitor_run",
    "monitor_until_empty",
]
