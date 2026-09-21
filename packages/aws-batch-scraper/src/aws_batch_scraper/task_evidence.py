"""Durable, minimal ECS terminal observations; never infer success from MISSING."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Literal, cast

from botocore.exceptions import ClientError
from mypy_boto3_ecs.client import ECSClient
from mypy_boto3_ecs.literals import TaskStopCodeType
from mypy_boto3_ecs.type_defs import ContainerTypeDef, TaskTypeDef
from mypy_boto3_s3.client import S3Client
from pydantic import BaseModel, ConfigDict, Field, field_validator

from aws_batch_scraper.config import SubmitterConfig


class TaskEvidenceError(RuntimeError):
    """Task evidence is missing, inconsistent, or cannot prove quiescence."""


class ContainerExit(BaseModel):
    """Only terminal container fields, without environment variables or secrets."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    name: str = Field(min_length=1)
    exit_code: int | None = None
    reason: str | None = None


class TerminalTask(BaseModel):
    """An ECS STOPPED observation tied to one immutable task identity."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal[1] = 1
    run_id: str
    cluster_arn: str
    task_arn: str
    observed_at: datetime
    stopped_at: datetime | None = None
    stop_code: str | None = None
    stopped_reason: str | None = None
    containers: tuple[ContainerExit, ...]

    @field_validator("observed_at", "stopped_at")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Task evidence timestamps must include a timezone")
        return value

    def as_task(self) -> TaskTypeDef:
        task: TaskTypeDef = {
            "taskArn": self.task_arn,
            "clusterArn": self.cluster_arn,
            "lastStatus": "STOPPED",
            "containers": [],
        }
        if self.stop_code is not None:
            task["stopCode"] = cast(TaskStopCodeType, self.stop_code)
        if self.stopped_reason is not None:
            task["stoppedReason"] = self.stopped_reason
        for container in self.containers:
            entry: ContainerTypeDef = {"name": container.name}
            if container.exit_code is not None:
                entry["exitCode"] = container.exit_code
            if container.reason is not None:
                entry["reason"] = container.reason
            task["containers"].append(entry)
        return task


def terminal_task_key(config: SubmitterConfig, run_id: str, task_arn: str) -> str:
    if not run_id.strip() or "/" in run_id:
        raise ValueError("Run ID must be one nonblank path segment")
    digest = hashlib.sha256(task_arn.encode()).hexdigest()
    return f"{config.s3_scraper_prefix}/runs/{run_id}/task-terminal/v1/{digest}.json"


def read_terminal_task(
    s3: S3Client, config: SubmitterConfig, run_id: str, task_arn: str
) -> TerminalTask | None:
    try:
        response = s3.get_object(
            Bucket=config.s3_bucket, Key=terminal_task_key(config, run_id, task_arn)
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404", "NotFound"}:
            return None
        raise
    record = TerminalTask.model_validate_json(response["Body"].read(256 * 1024))
    if (record.run_id, record.cluster_arn, record.task_arn) != (
        run_id,
        config.ecs_cluster_arn,
        task_arn,
    ):
        raise TaskEvidenceError("Terminal task evidence has a different run, cluster, or task")
    if record.observed_at > datetime.now(UTC):
        raise TaskEvidenceError("Terminal task observation is future-dated")
    return record


def _terminal_observation(config: SubmitterConfig, run_id: str, task: TaskTypeDef) -> TerminalTask:
    arn = task.get("taskArn")
    if not arn or task.get("lastStatus") != "STOPPED":
        raise TaskEvidenceError("Only an identified STOPPED task can be persisted")
    if task.get("clusterArn", config.ecs_cluster_arn) != config.ecs_cluster_arn:
        raise TaskEvidenceError("ECS task belongs to another cluster")
    containers = tuple(
        ContainerExit(
            name=container.get("name", "unknown"),
            exit_code=container.get("exitCode"),
            reason=container.get("reason"),
        )
        for container in task.get("containers", [])
    )
    return TerminalTask(
        run_id=run_id,
        cluster_arn=config.ecs_cluster_arn,
        task_arn=arn,
        observed_at=datetime.now(UTC),
        stopped_at=task.get("stoppedAt"),
        stop_code=task.get("stopCode"),
        stopped_reason=task.get("stoppedReason"),
        containers=containers,
    )


def persist_terminal_task(
    s3: S3Client, config: SubmitterConfig, run_id: str, task: TaskTypeDef
) -> TerminalTask:
    record = _terminal_observation(config, run_id, task)
    arn = record.task_arn
    body = record.model_dump_json().encode()
    try:
        s3.put_object(
            Bucket=config.s3_bucket,
            Key=terminal_task_key(config, run_id, arn),
            Body=body,
            ContentType="application/json",
            IfNoneMatch="*",
        )
    except Exception:
        # Also reconcile an ambiguous PUT. Never replace conflicting evidence.
        existing = read_terminal_task(s3, config, run_id, arn)
        if existing is None or existing.model_dump(exclude={"observed_at"}) != record.model_dump(
            exclude={"observed_at"}
        ):
            raise TaskEvidenceError("Terminal task write could not be reconciled") from None
        return existing
    return record


def describe_tasks_with_evidence(
    ecs: ECSClient,
    s3: S3Client,
    config: SubmitterConfig,
    run_id: str,
    task_arns: tuple[str, ...] | list[str],
    cache: dict[str, TaskTypeDef] | None = None,
    *,
    allow_reviewed_retirement: bool = False,
    persist_observations: bool = True,
) -> list[TaskTypeDef]:
    """Poll only unfinished tasks, durably retaining every STOPPED observation."""
    if len(set(task_arns)) != len(task_arns):
        raise TaskEvidenceError("Task inventory contains duplicate identities")
    terminal = {} if cache is None else cache
    pending = []
    for arn in task_arns:
        if arn not in terminal:
            record = read_terminal_task(s3, config, run_id, arn)
            if record is not None:
                terminal[arn] = record.as_task()
        if arn not in terminal and allow_reviewed_retirement:
            from aws_batch_scraper.task_reconciliation import read_retired_task

            retired = read_retired_task(s3, config, run_id, arn)
            if retired is not None:
                terminal[arn] = retired
        if arn not in terminal:
            pending.append(arn)
    observed = dict(terminal)
    for offset in range(0, len(pending), 100):
        batch = pending[offset : offset + 100]
        response = ecs.describe_tasks(cluster=config.ecs_cluster_arn, tasks=batch)
        tasks = response.get("tasks", [])
        arns = [task.get("taskArn") for task in tasks]
        if len(arns) != len(set(arns)) or not set(arns).issubset(batch):
            raise TaskEvidenceError("ECS omitted or substituted tasks without terminal evidence")
        for task in tasks:
            arn = str(task["taskArn"])
            if task.get("lastStatus") == "STOPPED":
                record = (
                    persist_terminal_task(s3, config, run_id, task)
                    if persist_observations
                    else _terminal_observation(config, run_id, task)
                )
                terminal[arn] = record.as_task()
                observed[arn] = terminal[arn]
            else:
                if not task.get("lastStatus"):
                    raise TaskEvidenceError("ECS task has no status")
                observed[arn] = task
        # Preserve every valid terminal observation even when another task is
        # missing. The unresolved response still prevents completion.
        if response.get("failures") or set(arns) != set(batch):
            raise TaskEvidenceError("ECS could not resolve tasks without terminal evidence")
    return [observed[arn] for arn in task_arns]
