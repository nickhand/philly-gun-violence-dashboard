"""Submitter: seed SQS queue, write run manifest, and launch Fargate workers."""

import json
import time
import uuid
from datetime import UTC, datetime

from loguru import logger
from mypy_boto3_ecs.client import ECSClient
from mypy_boto3_s3.client import S3Client
from mypy_boto3_sqs.client import SQSClient

from etl.courts.config import ScraperConfig


def make_run_id() -> str:
    """Create a run ID like 2026-05-19T143022Z-a3f1."""
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")
    return f"{ts}-{uuid.uuid4().hex[:4]}"


def get_existing_incidents(s3: S3Client, config: ScraperConfig) -> set[str]:
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
    config: ScraperConfig,
    incident_numbers: list[str],
    run_id: str,
) -> int:
    """Send incident numbers to SQS in batches of 10. Returns count sent."""
    sent = 0
    batch: list[dict] = []

    for i, incident in enumerate(incident_numbers):
        batch.append(
            {
                "Id": str(i % 10),
                "MessageBody": json.dumps({"incident_number": incident, "run_id": run_id}),
            }
        )
        if len(batch) == 10:
            sqs.send_message_batch(QueueUrl=config.sqs_queue_url, Entries=batch)
            sent += len(batch)
            batch = []

    if batch:
        sqs.send_message_batch(QueueUrl=config.sqs_queue_url, Entries=batch)
        sent += len(batch)

    logger.info(f"Seeded {sent} messages to {config.sqs_queue_url}")
    return sent


def write_run_manifest(
    s3: S3Client,
    config: ScraperConfig,
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


def launch_workers(
    ecs: ECSClient,
    config: ScraperConfig,
    run_id: str,
) -> list[str]:
    """Start config.ecs_task_count Fargate tasks. Returns task ARNs.

    Each task runs the default CMD (courts worker) with no command override.
    Environment variables carry the run_id and queue coordinates.
    """
    task_definition = config.ecs_task_definition
    logger.info(f"Using task definition (latest revision): {task_definition}")

    network_config = {
        "awsvpcConfiguration": {
            "assignPublicIp": "ENABLED",
            "subnets": config.ecs_subnet_ids,
            "securityGroups": config.ecs_security_group_ids,
        }
    }

    env_vars = [
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

    task_arns: list[str] = []
    for i in range(config.ecs_task_count):
        logger.info(f"Launching worker {i + 1}/{config.ecs_task_count}")
        response = ecs.run_task(
            taskDefinition=task_definition,
            cluster=config.ecs_cluster_arn,
            networkConfiguration=network_config,
            launchType="FARGATE",
            overrides={
                "containerOverrides": [
                    {
                        "name": config.ecs_container_name,
                        "environment": env_vars,
                    }
                ]
            },
        )
        if response["tasks"]:
            task_arns.append(response["tasks"][0]["taskArn"])
        elif response.get("failures"):
            reason = response["failures"][0].get("reason", "unknown")
            logger.warning(f"Worker {i + 1} failed to launch: {reason}")

    logger.info(f"Launched {len(task_arns)}/{config.ecs_task_count} workers")
    return task_arns


def monitor_until_empty(
    sqs: SQSClient,
    config: ScraperConfig,
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
    config: ScraperConfig,
    run_id: str,
    monitor_started_at: datetime,
) -> None:
    """Append completion fields to the run manifest."""
    manifest_key = f"{config.s3_scraper_prefix}/runs/{run_id}/manifest.json"
    try:
        body = s3.get_object(Bucket=config.s3_bucket, Key=manifest_key)["Body"].read()
        manifest: dict = json.loads(body)
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
    logger.info(
        f"Manifest finalized: runtime={total_runtime_seconds}s, dlq_depth={dlq_depth}"
    )
