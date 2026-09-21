"""Explicit operator-reviewed retirement of historical, no-longer-describable tasks."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime, timedelta
from typing import Literal

from botocore.exceptions import ClientError
from mypy_boto3_ecs.client import ECSClient
from mypy_boto3_ecs.type_defs import TaskTypeDef
from mypy_boto3_s3.client import S3Client
from mypy_boto3_sqs.client import SQSClient
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aws_batch_scraper.aggregate import read_run_manifest
from aws_batch_scraper.config import SubmitterConfig
from aws_batch_scraper.lease import read_run_lease
from aws_batch_scraper.resolution_paths import TASK_RETIREMENT_RESOLUTION_PATH


class RetirementReview(BaseModel):
    """Human attestation of quiescence, never an attestation of successful exits."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal[1] = 1
    run_id: str
    cluster_arn: str
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    lease_created_at: datetime
    reviewed_at: datetime
    reviewer: str = Field(min_length=1)
    rationale: str = Field(min_length=20)
    # Retain the actual reviewed evidence, not only a URL that may expire.
    evidence: str = Field(min_length=40, max_length=128 * 1024)
    retired_task_arns: tuple[str, ...] = Field(min_length=1)
    conclusion: Literal["stopped-exit-status-unknown"]

    @field_validator("lease_created_at", "reviewed_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Review timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def _identities(self) -> RetirementReview:
        if not self.reviewer.strip() or not self.run_id.strip() or "/" in self.run_id:
            raise ValueError("Review needs a reviewer and a run path segment")
        if len(set(self.retired_task_arns)) != len(self.retired_task_arns):
            raise ValueError("Review contains duplicate task identities")
        return self


def _key(config: SubmitterConfig, run_id: str, arn: str) -> str:
    digest = hashlib.sha256(arn.encode()).hexdigest()
    return (
        f"{config.s3_scraper_prefix}/runs/{run_id}/{TASK_RETIREMENT_RESOLUTION_PATH}/{digest}.json"
    )


def read_retired_task(
    s3: S3Client, config: SubmitterConfig, run_id: str, arn: str
) -> TaskTypeDef | None:
    try:
        body = s3.get_object(Bucket=config.s3_bucket, Key=_key(config, run_id, arn))["Body"].read(
            256 * 1024
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise
    review = RetirementReview.model_validate_json(body)
    manifest = read_run_manifest(s3, config, run_id)
    input_sha = (manifest.model_extra or {}).get("input_sha256")
    if (
        review.run_id != run_id
        or review.cluster_arn != config.ecs_cluster_arn
        or arn not in review.retired_task_arns
        or review.input_sha256 != input_sha
        or review.reviewed_at > datetime.now(UTC)
    ):
        raise ValueError("Task retirement review does not match this run and immutable input")
    return {
        "taskArn": arn,
        "clusterArn": config.ecs_cluster_arn,
        "lastStatus": "STOPPED",
        "stopCode": "UserInitiated",
        "stoppedReason": "Operator reviewed retirement; original exit status is unknown",
        "containers": [],
    }


def reconcile_retired_tasks(
    s3: S3Client,
    sqs: SQSClient,
    ecs: ECSClient,
    config: SubmitterConfig,
    review: RetirementReview,
    *,
    execute: bool = False,
    settle_seconds: float = 60,
) -> None:
    """Validate the review twice before append-only, operator-authorized writes.

    Runtime roles must be denied writes to the resolution namespace. This command
    never stops tasks, changes the lease, publishes results, or infers an exit code.
    """
    from aws_batch_scraper.orchestrate import _ecs_started_by
    from aws_batch_scraper.recovery import (
        _recovery_attempt_ids,
        _require_no_live_started_by_set,
        read_prior_task_arns,
        read_queue_state,
    )

    if settle_seconds < 60:
        raise ValueError("Retirement reconciliation requires at least 60 seconds of quiet")

    def validate() -> object:
        now = datetime.now(UTC)
        if not timedelta(0) <= now - review.reviewed_at <= timedelta(hours=24):
            raise ValueError("Review must be from the past 24 hours")
        lease = read_run_lease(s3, config)
        if (
            lease.run_id != review.run_id
            or lease.owner != review.run_id
            or lease.created_at != review.lease_created_at
            or review.cluster_arn != config.ecs_cluster_arn
        ):
            raise ValueError("Review no longer matches the original run lease")
        manifest = read_run_manifest(s3, config, review.run_id)
        if manifest.completed_at is not None:
            raise ValueError("A completed run cannot be reconciled for scraper recovery")
        if (manifest.model_extra or {}).get("input_sha256") != review.input_sha256:
            raise ValueError("Review immutable-input digest changed")
        arns = read_prior_task_arns(s3, config, review.run_id)
        digest = hashlib.sha256(
            json.dumps(sorted(arns), separators=(",", ":")).encode()
        ).hexdigest()
        if digest != review.task_set_sha256:
            raise ValueError("Review task inventory changed")
        missing: set[str] = set()
        for offset in range(0, len(arns), 100):
            batch = arns[offset : offset + 100]
            response = ecs.describe_tasks(cluster=config.ecs_cluster_arn, tasks=list(batch))
            tasks = response.get("tasks", [])
            failures = response.get("failures", [])
            if any(failure.get("reason") != "MISSING" for failure in failures):
                raise ValueError("ECS returned an error other than retired task records")
            observed = [task.get("taskArn") for task in tasks]
            unavailable = [failure.get("arn") for failure in failures]
            if (
                set(observed + unavailable) != set(batch)
                or len(observed + unavailable) != len(batch)
                or any(task.get("lastStatus") != "STOPPED" for task in tasks)
            ):
                raise ValueError("Task inventory is incomplete, ambiguous, or still live")
            missing.update(str(arn) for arn in unavailable)
        if missing != set(review.retired_task_arns):
            raise ValueError("Review must name exactly the currently retired tasks")
        identities = [_ecs_started_by(review.run_id, role) for role in ("worker", "monitor")]
        for attempt in _recovery_attempt_ids(s3, config, review.run_id):
            identities.extend(
                _ecs_started_by(review.run_id, role, recovery_attempt_id=attempt)
                for role in ("worker", "monitor")
            )
        _require_no_live_started_by_set(ecs, config, tuple(identities))
        queue = read_queue_state(sqs, config)
        if queue.in_flight:
            raise ValueError("Messages remain in flight")
        return queue

    initial = validate()
    if not execute:
        return
    time.sleep(settle_seconds)
    if validate() != initial:
        raise ValueError("Queue changed during retirement reconciliation")
    body = review.model_dump_json().encode()
    for arn in review.retired_task_arns:
        key = _key(config, review.run_id, arn)
        try:
            s3.put_object(
                Bucket=config.s3_bucket,
                Key=key,
                Body=body,
                ContentType="application/json",
                IfNoneMatch="*",
            )
        except Exception:
            existing = s3.get_object(Bucket=config.s3_bucket, Key=key)["Body"].read()
            if existing != body:
                raise ValueError(
                    "Task retirement resolution conflicts with retained evidence"
                ) from None
