"""Submitter: seed SQS queue, write run manifest, and launch Fargate workers."""

import json
import os
import time
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from loguru import logger
from mypy_boto3_ecs.client import ECSClient
from mypy_boto3_ecs.type_defs import (
    KeyValuePairTypeDef,
    NetworkConfigurationTypeDef,
    TaskOverrideTypeDef,
)
from mypy_boto3_s3.client import S3Client
from mypy_boto3_sqs.client import SQSClient
from mypy_boto3_sqs.type_defs import (
    BatchResultErrorEntryTypeDef,
    SendMessageBatchRequestEntryTypeDef,
)

from etl.courts.batch.dispatch import dispatch_process_workflow
from etl.courts.config import SubmitterConfig

_ECS_TERMINAL = {"STOPPED", "DEPROVISIONING"}
_SQS_BATCH_SIZE = 10
_SQS_BATCH_ATTEMPTS = 3


def _send_message_batch_checked(
    sqs: SQSClient,
    queue_url: str,
    entries: list[SendMessageBatchRequestEntryTypeDef],
) -> None:
    """Send one SQS batch and fail loudly if AWS reports per-entry failures."""
    pending = entries
    failures: list[BatchResultErrorEntryTypeDef] = []
    for _ in range(_SQS_BATCH_ATTEMPTS):
        response = sqs.send_message_batch(QueueUrl=queue_url, Entries=pending)
        failures = list(response.get("Failed", []))
        if not failures:
            return

        failed_ids = {failure["Id"] for failure in failures}
        pending = [entry for entry in pending if entry["Id"] in failed_ids]
        logger.warning(f"Retrying {len(pending)} failed SQS batch message(s)")

    failure_details = ", ".join(
        f"{failure.get('Id', '?')}:{failure.get('Code', 'unknown')}" for failure in failures
    )
    raise RuntimeError(f"SQS batch send failed after retries: {failure_details}")


def make_run_id() -> str:
    """Create a run ID like 2026-05-19T143022Z-a3f1."""
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")
    return f"{ts}-{uuid.uuid4().hex[:4]}"


def get_existing_incidents(s3: S3Client, config: SubmitterConfig) -> set[str]:
    """Return the set of incident numbers that already have results in S3.

    Used by the submitter to filter out already-scraped incidents before
    seeding the queue, so reruns only process new work.
    """
    prefix = f"{config.s3_scraper_prefix}/results/"
    paginator = s3.get_paginator("list_objects_v2")
    existing: set[str] = set()
    for page in paginator.paginate(Bucket=config.s3_bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            incident = key.removeprefix(prefix).removesuffix(".json")
            if incident:
                existing.add(incident)
    logger.info(f"Found {len(existing)} existing results in s3://{config.s3_bucket}/{prefix}")
    return existing


def seed_queue(
    sqs: SQSClient,
    config: SubmitterConfig,
    incident_numbers: list[str],
    run_id: str,
) -> int:
    """Send incident numbers to SQS in batches of 10. Returns count sent."""
    sent = 0
    batch: list[SendMessageBatchRequestEntryTypeDef] = []

    for i, incident in enumerate(incident_numbers):
        batch.append(
            {
                "Id": str(i % 10),
                "MessageBody": json.dumps({"incident_number": incident, "run_id": run_id}),
            }
        )
        if len(batch) == _SQS_BATCH_SIZE:
            _send_message_batch_checked(sqs, config.sqs_queue_url, batch)
            sent += len(batch)
            batch = []

    if batch:
        _send_message_batch_checked(sqs, config.sqs_queue_url, batch)
        sent += len(batch)

    logger.info(f"Seeded {sent} messages to {config.sqs_queue_url}")
    return sent


def write_run_manifest(
    s3: S3Client,
    config: SubmitterConfig,
    run_id: str,
    incident_numbers: list[str],
    worker_count: int,
) -> None:
    """Write manifest.json and input.jsonl to ujs-scraper/runs/{run_id}/."""
    prefix = f"{config.s3_scraper_prefix}/runs/{run_id}"

    manifest = {
        "run_id": run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "input_size": len(incident_numbers),
        "queue_url": config.sqs_queue_url,
        "worker_count": worker_count,
    }
    s3.put_object(
        Bucket=config.s3_bucket,
        Key=f"{prefix}/manifest.json",
        Body=json.dumps(manifest, indent=2).encode(),
        ContentType="application/json",
    )

    input_jsonl = "\n".join(json.dumps({"incident_number": inc}) for inc in incident_numbers)
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


def get_task_arns(s3: S3Client, config: SubmitterConfig, run_id: str) -> list[str]:
    """Read task ARNs saved by write_task_arns. Returns [] if not found."""
    key = f"{config.s3_scraper_prefix}/runs/{run_id}/tasks.json"
    try:
        body = s3.get_object(Bucket=config.s3_bucket, Key=key)["Body"].read()
        data = cast(dict[str, Any], json.loads(body))
        task_arns = data.get("task_arns", [])
        if not isinstance(task_arns, list):
            return []
        return [arn for arn in task_arns if isinstance(arn, str)]
    except Exception:
        return []


def launch_workers(
    ecs: ECSClient,
    config: SubmitterConfig,
    run_id: str,
    worker_count: int | None = None,
    force_rescrape: bool = False,
    soft_blocked_delay_max: int | None = None,
) -> list[str]:
    """Start Fargate tasks. Returns task ARNs.

    Each task runs the default CMD (courts worker) with no command override.
    Environment variables carry the run_id and queue coordinates.
    """
    n = worker_count if worker_count is not None else config.ecs_task_count
    task_definition = config.ecs_task_definition
    logger.info(f"Using task definition (latest revision): {task_definition}")

    network_config: NetworkConfigurationTypeDef = {
        "awsvpcConfiguration": {
            "assignPublicIp": "ENABLED",
            "subnets": config.ecs_subnet_ids,
            "securityGroups": config.ecs_security_group_ids,
        }
    }

    env_vars: list[KeyValuePairTypeDef] = [
        {"name": "ENV", "value": "prod"},
        {"name": "RUN_ID", "value": run_id},
        {"name": "AWS_ACCOUNT_ID", "value": config.aws_account_id},
        {"name": "AWS_REGION", "value": str(config.aws_region)},
        {"name": "S3_BUCKET", "value": config.s3_bucket},
        {"name": "FORCE_RESCRAPE", "value": "1" if force_rescrape else "0"},
        {"name": "SQS_QUEUE_NAME", "value": config.sqs_queue_name},
        {"name": "SQS_DLQ_NAME", "value": config.sqs_dlq_name},
        {"name": "ECS_SUBNET_IDS", "value": ",".join(config.ecs_subnet_ids)},
        {"name": "ECS_SECURITY_GROUP_IDS", "value": ",".join(config.ecs_security_group_ids)},
    ]
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
            networkConfiguration=network_config,
            launchType="FARGATE",
            overrides=overrides,
        )
        if response["tasks"]:
            task_arns.append(response["tasks"][0]["taskArn"])
        elif response.get("failures"):
            reason = response["failures"][0].get("reason", "unknown")
            logger.warning(f"Worker {i + 1} failed to launch: {reason}")

    if not task_arns:
        raise RuntimeError(f"Only launched {len(task_arns)}/{n} requested worker task(s)")
    if len(task_arns) != n:
        logger.warning(f"Only launched {len(task_arns)}/{n} requested worker task(s)")

    logger.info(f"Launched {len(task_arns)}/{n} workers")
    return task_arns


def launch_monitor(
    ecs: ECSClient,
    config: SubmitterConfig,
    run_id: str,
) -> str:
    """Start one Fargate coordinator task that waits for a run and dispatches processing.

    The monitor task uses the same image as workers but overrides the command to
    ``courts monitor --run-id``. Configure ``GITHUB_DISPATCH_TOKEN`` as an ECS
    task-definition secret; it may fire hours after the submitter exits, so a
    short-lived GitHub Actions token is the wrong credential for this task.
    """
    network_config: NetworkConfigurationTypeDef = {
        "awsvpcConfiguration": {
            "assignPublicIp": "ENABLED",
            "subnets": config.ecs_subnet_ids,
            "securityGroups": config.ecs_security_group_ids,
        }
    }

    env_vars: list[KeyValuePairTypeDef] = [
        {"name": "ENV", "value": "prod"},
        {"name": "RUN_ID", "value": run_id},
        {"name": "AWS_ACCOUNT_ID", "value": config.aws_account_id},
        {"name": "AWS_REGION", "value": str(config.aws_region)},
        {"name": "S3_BUCKET", "value": config.s3_bucket},
        {"name": "SQS_QUEUE_NAME", "value": config.sqs_queue_name},
        {"name": "SQS_DLQ_NAME", "value": config.sqs_dlq_name},
        {"name": "ECS_SUBNET_IDS", "value": ",".join(config.ecs_subnet_ids)},
        {"name": "ECS_SECURITY_GROUP_IDS", "value": ",".join(config.ecs_security_group_ids)},
    ]
    if repository := os.environ.get("GITHUB_REPOSITORY"):
        env_vars.append({"name": "GITHUB_REPOSITORY", "value": repository})

    overrides: TaskOverrideTypeDef = {
        "containerOverrides": [
            {
                "name": config.ecs_container_name,
                "command": [
                    "uv",
                    "run",
                    "gv-dashboard-etl",
                    "courts",
                    "monitor",
                    "--run-id",
                    run_id,
                ],
                "environment": env_vars,
            }
        ]
    }
    response = ecs.run_task(
        taskDefinition=config.ecs_task_definition,
        cluster=config.ecs_cluster_arn,
        networkConfiguration=network_config,
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
    """Block until all ECS tasks for run_id have stopped, then finalize the manifest.

    Uses ECS task status as the primary signal (accurate per-run), with a final
    SQS queue-depth check to confirm nothing was left in-flight.
    """
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
            logger.info("All tasks stopped — run complete")
            _finalize_manifest(s3, sqs, config, run_id, started_at)
            return

        time.sleep(poll_interval)


def monitor_until_empty(
    sqs: SQSClient,
    config: SubmitterConfig,
    *,
    poll_interval: int = 60,
    s3: S3Client | None = None,
    run_id: str | None = None,
) -> None:
    """Block until both visible and in-flight message counts reach zero.

    If ``s3`` and ``run_id`` are provided, appends completion metadata
    (completed_at, total_runtime_seconds, dlq_depth) to the run manifest.
    """
    started_at = datetime.now(UTC)
    logger.info("Monitoring queue until empty...")

    while True:
        attrs = sqs.get_queue_attributes(
            QueueUrl=config.sqs_queue_url,
            AttributeNames=[
                "ApproximateNumberOfMessages",
                "ApproximateNumberOfMessagesNotVisible",
            ],
        )["Attributes"]
        visible = int(attrs["ApproximateNumberOfMessages"])
        in_flight = int(attrs["ApproximateNumberOfMessagesNotVisible"])
        logger.info(f"Queue: {visible} visible, {in_flight} in-flight")

        if visible == 0 and in_flight == 0:
            logger.info("Queue empty — run complete")
            if s3 is not None and run_id is not None:
                _finalize_manifest(s3, sqs, config, run_id, started_at)
            return

        time.sleep(poll_interval)


def _finalize_manifest(
    s3: S3Client,
    sqs: SQSClient,
    config: SubmitterConfig,
    run_id: str,
    monitor_started_at: datetime,
) -> None:
    """Append completion fields to the run manifest."""
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
    dispatch_process_workflow(run_id)
