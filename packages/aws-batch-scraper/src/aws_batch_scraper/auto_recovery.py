"""One automatic same-run recovery for proven image-pull startup failures."""

from __future__ import annotations

import json
from collections.abc import Callable

from mypy_boto3_ecs.client import ECSClient
from mypy_boto3_ecs.type_defs import TaskTypeDef
from mypy_boto3_s3.client import S3Client
from mypy_boto3_sqs.client import SQSClient

from aws_batch_scraper.aggregate import read_run_manifest
from aws_batch_scraper.config import SubmitterConfig
from aws_batch_scraper.health import check_run_health
from aws_batch_scraper.lease import read_run_lease
from aws_batch_scraper.orchestrate import _assert_tasks_succeeded
from aws_batch_scraper.recovery import (
    RecoveryInvariantError,
    build_recovery_plan,
    execute_recovery_plan,
)
from aws_batch_scraper.task_evidence import describe_tasks_with_evidence


def require_startup_failures(tasks: list[TaskTypeDef]) -> None:
    """Reject application failures, unknown exits, live tasks, and missing proof."""
    if not tasks:
        raise RecoveryInvariantError("No worker task evidence for automatic recovery")
    failures = 0
    for task in tasks:
        if task.get("lastStatus") != "STOPPED":
            raise RecoveryInvariantError("Automatic recovery requires stopped workers")
        if task.get("stopCode") == "TaskFailedToStart" and str(
            task.get("stoppedReason", "")
        ).startswith("CannotPullContainerError:"):
            # A container that ran is outside this narrowly scoped policy.
            if any(c.get("exitCode") is not None for c in task.get("containers", [])):
                raise RecoveryInvariantError("Startup failure contains a container exit")
            failures += 1
        else:
            _assert_tasks_succeeded([task])
    if not failures:
        raise RecoveryInvariantError("No eligible image-pull startup failure")


def auto_recover(
    s3: S3Client,
    sqs: SQSClient,
    ecs: ECSClient,
    config: SubmitterConfig,
    *,
    execute: bool = False,
    monitor_command: Callable[[str, str], list[str]],
) -> str:
    """Use the existing fenced recovery engine, with one durable attempt per run.

    An ambiguous write/launch consumes the attempt. Operators must inspect and
    reconcile it explicitly; subsequent watchdogs cannot silently retry it.
    """
    run_id, findings = check_run_health(s3, ecs, config)
    if not findings:
        return f"Run {run_id} is healthy; no recovery needed"
    lease = read_run_lease(s3, config)
    if lease.run_id != run_id or lease.owner != run_id:
        raise RecoveryInvariantError("Automatic recovery requires the original run lease")
    if read_run_manifest(s3, config, run_id).completed_at is not None:
        raise RecoveryInvariantError("Completed runs require publication recovery, not scraping")
    plan = build_recovery_plan(s3, sqs, ecs, config, run_id)
    tasks = describe_tasks_with_evidence(
        ecs,
        s3,
        config,
        run_id,
        list(plan.prior_task_arns),
        persist_observations=False,
    )
    require_startup_failures(tasks)
    if not execute:
        return f"Run {run_id} eligible for one automatic recovery: {plan.action.value}"
    # Reserve before any recovery mutation. IfNoneMatch prevents concurrent or
    # later invocations from exceeding the fixed one-attempt budget.
    s3.put_object(
        Bucket=config.s3_bucket,
        Key=f"{config.s3_scraper_prefix}/runs/{run_id}/auto-recovery/v1/attempt.json",
        Body=json.dumps(plan.as_dict()).encode(),
        ContentType="application/json",
        IfNoneMatch="*",
    )
    execute_recovery_plan(
        s3,
        sqs,
        ecs,
        config,
        plan,
        monitor_command=monitor_command(run_id, plan.attempt_id),
    )
    return f"Run {run_id}: automatic recovery {plan.attempt_id} accepted ({plan.action.value})"
