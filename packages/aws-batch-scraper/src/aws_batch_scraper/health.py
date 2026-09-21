"""Run diagnostics and a read-only watchdog independent of the ECS monitor."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from botocore.exceptions import ClientError
from mypy_boto3_ecs.client import ECSClient
from mypy_boto3_s3.client import S3Client
from pydantic import BaseModel, ConfigDict, field_validator

from aws_batch_scraper.aggregate import read_run_manifest
from aws_batch_scraper.config import SubmitterConfig, WorkerConfig
from aws_batch_scraper.lease import (
    RunLease,
    RunTerminalRecord,
    _is_completed_release_for_lease,
    read_run_lease,
)
from aws_batch_scraper.task_evidence import read_terminal_task


class Diagnostic(BaseModel):
    """Allowlisted status fields; never serialize exceptions or settings objects."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    run_id: str
    identity: str
    observed_at: datetime
    status: Literal["running", "stopped", "failed"]
    error_type: str | None = None
    lease_created_at: datetime | None = None

    @field_validator("observed_at", "lease_created_at")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Diagnostic timestamp must include a timezone")
        return value


def monitor_state_key(config: WorkerConfig, lease: RunLease) -> str:
    identity = f"{lease.owner}:{lease.created_at.isoformat()}"
    digest = hashlib.sha256(identity.encode()).hexdigest()
    return f"{config.s3_scraper_prefix}/runs/{lease.run_id}/monitor-state/v1/{digest}.json"


def record_monitor_state(
    s3: S3Client,
    config: WorkerConfig,
    lease: RunLease,
    *,
    error: Exception | None = None,
) -> None:
    record = Diagnostic(
        run_id=lease.run_id,
        identity=lease.owner,
        lease_created_at=lease.created_at,
        observed_at=datetime.now(UTC),
        status="failed" if error is not None else "running",
        error_type=type(error).__name__ if error is not None else None,
    )
    s3.put_object(
        Bucket=config.s3_bucket,
        Key=monitor_state_key(config, lease),
        Body=record.model_dump_json().encode(),
        ContentType="application/json",
    )


@dataclass
class WorkerProgress:
    """Write at most one progress observation per minute, plus terminal status."""

    s3: S3Client
    config: WorkerConfig
    run_id: str
    identity: str
    _written_at: float = field(default=float("-inf"), init=False)

    def write(self, *, stopped: bool = False) -> None:
        now = time.monotonic()
        if not stopped and now - self._written_at < 60:
            return
        record = Diagnostic(
            run_id=self.run_id,
            identity=self.identity,
            observed_at=datetime.now(UTC),
            status="stopped" if stopped else "running",
        )
        digest = hashlib.sha256(self.identity.encode()).hexdigest()
        self.s3.put_object(
            Bucket=self.config.s3_bucket,
            Key=f"{self.config.s3_scraper_prefix}/runs/{self.run_id}/worker-progress/v1/{digest}.json",
            Body=record.model_dump_json().encode(),
            ContentType="application/json",
        )
        self._written_at = now


def _optional_json(s3: S3Client, config: WorkerConfig, key: str) -> bytes | None:
    try:
        return s3.get_object(Bucket=config.s3_bucket, Key=key)["Body"].read(256 * 1024)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise


def check_run_health(
    s3: S3Client,
    ecs: ECSClient,
    config: SubmitterConfig,
    *,
    now: datetime | None = None,
    max_runtime: timedelta = timedelta(hours=12),
    max_silence: timedelta = timedelta(minutes=10),
) -> tuple[str, list[str]]:
    """Check the current run without renewing leases, writing evidence, or dispatching."""
    if (now is not None and now.tzinfo is None) or min(max_runtime, max_silence) <= timedelta(0):
        raise ValueError("Watchdog requires an aware clock and positive thresholds")

    def elapsed_since(timestamp: datetime) -> timedelta:
        # A monitor may write a fresh heartbeat while this probe is reading S3.
        # Compare against the current clock, not a time captured before the GET.
        return (now or datetime.now(UTC)) - timestamp

    lease = read_run_lease(s3, config)
    prefix = f"{config.s3_scraper_prefix}/runs/{lease.run_id}/"
    manifest = read_run_manifest(s3, config, lease.run_id)
    findings: list[str] = []
    terminal_body = _optional_json(s3, config, prefix + "lease-terminal.json")
    if terminal_body is not None:
        terminal = RunTerminalRecord.model_validate_json(terminal_body)
        if _is_completed_release_for_lease(lease, terminal):
            if terminal.terminal_status == "failure":
                findings.append(
                    "run ended in failure; inspect run and processing recovery evidence"
                )
            if elapsed_since(terminal.release_requested_at) < timedelta(0):
                findings.append("terminal release is future-dated")
            if terminal.terminal_status == "success" and manifest.completed_at is None:
                findings.append("successful release has no completed run manifest")
            return lease.run_id, findings
    if elapsed_since(lease.created_at) < timedelta(0):
        findings.append("active lease is future-dated")
    if elapsed_since(lease.expires_at) >= timedelta(0):
        findings.append("lease expired without a terminal release")
    timestamp = manifest.model_extra.get("timestamp") if manifest.model_extra else None
    if not isinstance(timestamp, str):
        raise ValueError("Run manifest has no submission timestamp")
    started_at = datetime.fromisoformat(timestamp)
    if started_at.tzinfo is None:
        raise ValueError("Run submission timestamp must include a timezone")
    age = elapsed_since(started_at)
    if age < timedelta(0) or age > max_runtime:
        findings.append(f"run age {age} exceeds the allowed 0–{max_runtime}")
    scraping = lease.owner == lease.run_id or lease.owner.startswith("recovery:")
    requires_heartbeat = (
        (manifest.model_extra or {}).get("monitoring_contract_version") == 1
        and scraping
        and elapsed_since(lease.created_at) > max_silence
    )
    body = _optional_json(s3, config, monitor_state_key(config, lease))
    if body is None and requires_heartbeat:
        findings.append("monitor has not reported its required heartbeat")
    if body is not None:
        state = Diagnostic.model_validate_json(body)
        if (state.run_id, state.identity, state.lease_created_at) != (
            lease.run_id,
            lease.owner,
            lease.created_at,
        ):
            raise ValueError("Monitor diagnostic identity does not match active lease")
        if state.status == "failed":
            findings.append(f"monitor failed ({state.error_type})")
        elif not timedelta(0) <= elapsed_since(state.observed_at) <= max_silence:
            findings.append("monitor heartbeat is stale or future-dated")

    # Processing/finalizing owners no longer run scraper workers. Runtime and
    # lease checks above still detect a failed downstream dispatch or processor.
    if not scraping:
        return lease.run_id, findings

    from aws_batch_scraper.recovery import read_prior_task_arns

    arns = read_prior_task_arns(s3, config, lease.run_id)
    pending = []
    for arn in arns:
        record = read_terminal_task(s3, config, lease.run_id, arn)
        if record is None:
            pending.append(arn)
        elif not record.containers or any(
            container.exit_code != 0 for container in record.containers
        ):
            findings.append(f"worker {arn} stopped unsuccessfully")
    monitor_body = _optional_json(s3, config, prefix + "monitor-task.json")
    if monitor_body is not None and lease.owner == lease.run_id:
        monitor = json.loads(monitor_body)
        if monitor.get("run_id") != lease.run_id or not isinstance(monitor.get("task_arn"), str):
            raise ValueError("Monitor task record is malformed")
        response = ecs.describe_tasks(cluster=config.ecs_cluster_arn, tasks=[monitor["task_arn"]])
        monitor_tasks = response.get("tasks", [])
        if (
            response.get("failures")
            or len(monitor_tasks) != 1
            or monitor_tasks[0].get("taskArn") != monitor["task_arn"]
        ):
            findings.append("monitor task is missing before run completion")
        elif monitor_tasks[0].get("lastStatus") == "STOPPED":
            findings.append("monitor task stopped before run completion")
    for offset in range(0, len(pending), 100):
        response = ecs.describe_tasks(
            cluster=config.ecs_cluster_arn, tasks=pending[offset : offset + 100]
        )
        tasks = response.get("tasks", [])
        requested = set(pending[offset : offset + 100])
        if response.get("failures") or {task.get("taskArn") for task in tasks} != requested:
            findings.append("worker task records are unavailable without saved terminal evidence")
        for task in tasks:
            if task.get("lastStatus") == "STOPPED" and (
                not task.get("containers")
                or any(container.get("exitCode") != 0 for container in task["containers"])
            ):
                findings.append(f"worker {task.get('taskArn')} stopped unsuccessfully")

    progress_seen = False
    progress_prefix = prefix + "worker-progress/v1/"
    for page in s3.get_paginator("list_objects_v2").paginate(
        Bucket=config.s3_bucket, Prefix=progress_prefix
    ):
        for entry in page.get("Contents", []):
            key = entry.get("Key")
            if not key:
                raise ValueError("Worker diagnostic listing lacks a key")
            data = _optional_json(s3, config, key)
            if data is None:
                raise ValueError("Worker diagnostic disappeared during health check")
            progress = Diagnostic.model_validate_json(data)
            if progress.run_id != lease.run_id:
                raise ValueError("Worker progress belongs to another run")
            if progress.observed_at < lease.created_at:
                continue  # superseded worker from an earlier recovery generation
            progress_seen = True
            if (
                progress.status != "stopped"
                and not timedelta(0) <= elapsed_since(progress.observed_at) <= max_silence
            ):
                findings.append(f"worker {progress.identity} stopped reporting progress")
    if requires_heartbeat and pending and not progress_seen:
        findings.append("workers have not reported required progress")
    return lease.run_id, findings
