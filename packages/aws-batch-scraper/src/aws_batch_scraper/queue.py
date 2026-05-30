"""SQS queue seeding and item discovery."""

import json

from loguru import logger
from mypy_boto3_s3.client import S3Client
from mypy_boto3_sqs.client import SQSClient
from mypy_boto3_sqs.type_defs import (
    BatchResultErrorEntryTypeDef,
    SendMessageBatchRequestEntryTypeDef,
)

from aws_batch_scraper.config import WorkerConfig
from aws_batch_scraper.types import WorkItem

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

    failure_details = ", ".join(f"{f.get('Id', '?')}:{f.get('Code', 'unknown')}" for f in failures)
    raise RuntimeError(f"SQS batch send failed after retries: {failure_details}")


def seed_queue(
    sqs: SQSClient,
    config: WorkerConfig,
    items: list[WorkItem],
    run_id: str,
) -> int:
    """Send WorkItems to SQS in batches of 10. Returns count sent.

    Each SQS message body has the form:
    ``{"item_id": str, "run_id": str, **item.extra}``

    The worker reconstructs a ``WorkItem`` from this body.
    """
    sent = 0
    batch: list[SendMessageBatchRequestEntryTypeDef] = []

    for i, item in enumerate(items):
        body = {"item_id": item.item_id, "run_id": run_id, **item.extra}
        batch.append(
            {
                "Id": str(i % _SQS_BATCH_SIZE),
                "MessageBody": json.dumps(body),
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


def get_existing_items(s3: S3Client, config: WorkerConfig) -> set[str]:
    """Return the set of item_ids that already have results in S3.

    Used by the submitter to filter out already-processed items before seeding
    the queue, so reruns only process new work.
    """
    prefix = f"{config.s3_scraper_prefix}/results/"
    paginator = s3.get_paginator("list_objects_v2")
    existing: set[str] = set()
    for page in paginator.paginate(Bucket=config.s3_bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            item_id = key.removeprefix(prefix).removesuffix(".json")
            if item_id:
                existing.add(item_id)
    logger.info(f"Found {len(existing)} existing results in s3://{config.s3_bucket}/{prefix}")
    return existing
