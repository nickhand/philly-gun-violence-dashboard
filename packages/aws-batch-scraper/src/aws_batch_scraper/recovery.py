"""Fail-closed, same-run recovery planning for interrupted scraper runs.

The inventory in this module deliberately treats exact-run S3 objects as the
checkpoint.  A recovery never reconstructs progress from worker counters and
never creates a new run ID: valid conclusive results and permanent failures are
reused, while only input IDs without either terminal object may be seeded.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from botocore.exceptions import ClientError
from loguru import logger
from mypy_boto3_ecs.client import ECSClient
from mypy_boto3_ecs.type_defs import TaskTypeDef
from mypy_boto3_s3.client import S3Client
from mypy_boto3_sqs.client import SQSClient
from mypy_boto3_sqs.literals import QueueAttributeNameType

from aws_batch_scraper.config import SubmitterConfig, WorkerConfig
from aws_batch_scraper.result_semantics import semantic_observation
from aws_batch_scraper.strict_json import decode_strict_json_object
from aws_batch_scraper.types import ScrapeResult, ScrapeStatus, WorkItem

_RECOVERY_SCHEMA_VERSION = 1
_QUEUE_ATTRIBUTES: tuple[QueueAttributeNameType, ...] = (
    "ApproximateNumberOfMessages",
    "ApproximateNumberOfMessagesNotVisible",
    "ApproximateNumberOfMessagesDelayed",
)


class RecoveryInvariantError(RuntimeError):
    """Raised when an interrupted run cannot be resumed safely."""


class _AmbiguousInitialLaunch(RecoveryInvariantError):
    """Carries durable evidence for an initial RunTask outcome with no ARN."""

    def __init__(self, recorded_at: datetime, task_arns: tuple[str, ...]) -> None:
        self.recorded_at = recorded_at
        self.task_arns = task_arns
        super().__init__("Initial worker launch outcome is ambiguous")


class RecoveryAction(StrEnum):
    """One mutation strategy selected by a read-only recovery plan."""

    COMPLETE = "complete"
    LAUNCH_EXISTING_QUEUE = "launch-existing-queue"
    SEED_MISSING = "seed-missing"


@dataclass(frozen=True)
class QueueState:
    """All observable message states for the shared main queue."""

    visible: int
    in_flight: int
    delayed: int

    @property
    def total(self) -> int:
        return self.visible + self.in_flight + self.delayed

    def as_dict(self) -> dict[str, int]:
        return {
            "visible": self.visible,
            "in_flight": self.in_flight,
            "delayed": self.delayed,
        }


@dataclass(frozen=True)
class RecoveryInventory:
    """Validated immutable inputs and exact-run terminal artifacts."""

    run_id: str
    items: tuple[WorkItem, ...]
    input_sha256: str
    input_etag: str
    input_version_id: str | None
    force_rescrape: bool
    terminal_candidate_journal_schema_version: int | None
    manifest_completed_at: datetime | None
    result_ids: frozenset[str]
    failure_ids: frozenset[str]
    missing_ids: tuple[str, ...]
    terminal_evidence_sha256: str
    candidate_count: int
    candidate_evidence_sha256: str
    conflict_policy_version: int
    conflict_evidence_sha256: str
    resolved_conflict_count: int
    invalid_resolution_count: int

    @property
    def input_ids(self) -> frozenset[str]:
        return frozenset(item.item_id for item in self.items)

    @property
    def completed_ids(self) -> frozenset[str]:
        return self.result_ids | self.failure_ids

    @property
    def missing_items(self) -> tuple[WorkItem, ...]:
        missing = set(self.missing_ids)
        return tuple(item for item in self.items if item.item_id in missing)


@dataclass(frozen=True)
class _FailureConflictEvidence:
    """One strictly validated failure-conflict snapshot used by inventory CAS."""

    key: str
    item_id: str
    candidate_sha256: str
    body_sha256: str


@dataclass(frozen=True)
class RecoveryPlan:
    """Read-only decision record written before any recovery side effect."""

    run_id: str
    attempt_id: str
    created_at: datetime
    action: RecoveryAction
    inventory: RecoveryInventory
    queue: QueueState
    prior_task_arns: tuple[str, ...]
    prior_task_discovery: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": _RECOVERY_SCHEMA_VERSION,
            "run_id": self.run_id,
            "attempt_id": self.attempt_id,
            "created_at": self.created_at.isoformat(),
            "action": self.action.value,
            "input": {
                "sha256": self.inventory.input_sha256,
                "etag": self.inventory.input_etag,
                "version_id": self.inventory.input_version_id,
                "count": len(self.inventory.items),
                "force_rescrape": self.inventory.force_rescrape,
                "terminal_candidate_journal_schema_version": (
                    self.inventory.terminal_candidate_journal_schema_version
                ),
                "manifest_completed_at": (
                    self.inventory.manifest_completed_at.isoformat()
                    if self.inventory.manifest_completed_at is not None
                    else None
                ),
            },
            "terminal_artifacts": {
                "result_count": len(self.inventory.result_ids),
                "failure_count": len(self.inventory.failure_ids),
                "completed_count": len(self.inventory.completed_ids),
                "missing_count": len(self.inventory.missing_ids),
                "missing_ids": list(self.inventory.missing_ids),
                "evidence_sha256": self.inventory.terminal_evidence_sha256,
                "candidate_count": self.inventory.candidate_count,
                "candidate_evidence_sha256": self.inventory.candidate_evidence_sha256,
            },
            "conflicts": {
                "policy_version": self.inventory.conflict_policy_version,
                "evidence_sha256": self.inventory.conflict_evidence_sha256,
                "resolved_count": self.inventory.resolved_conflict_count,
                "unresolved_count": 0,
                "invalid_resolution_count": self.inventory.invalid_resolution_count,
            },
            "queue": self.queue.as_dict(),
            "prior_task_arns": list(self.prior_task_arns),
            "prior_task_discovery": list(self.prior_task_discovery),
        }


@dataclass(frozen=True)
class RecoveryReconciliation:
    """Fail-closed observations authorizing one same-run lease handback."""

    run_id: str
    attempt_id: str
    observed_at: datetime
    plan_created_at: datetime
    lease_created_at: datetime
    queue: QueueState
    terminal_evidence_sha256: str
    candidate_evidence_sha256: str
    conflict_evidence_sha256: str
    missing_ids: tuple[str, ...]
    known_task_arns: tuple[str, ...]
    worker_started_by: str
    monitor_started_by: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": _RECOVERY_SCHEMA_VERSION,
            "run_id": self.run_id,
            "attempt_id": self.attempt_id,
            "observed_at": self.observed_at.isoformat(),
            "plan_created_at": self.plan_created_at.isoformat(),
            "lease_created_at": self.lease_created_at.isoformat(),
            "queue": self.queue.as_dict(),
            "terminal_evidence_sha256": self.terminal_evidence_sha256,
            "candidate_evidence_sha256": self.candidate_evidence_sha256,
            "conflict_evidence_sha256": self.conflict_evidence_sha256,
            "missing_ids": list(self.missing_ids),
            "known_task_arns": list(self.known_task_arns),
            "ecs_started_by": {
                "worker": self.worker_started_by,
                "monitor": self.monitor_started_by,
            },
            "live_task_arns": [],
            "lease_action": "return-authorized",
        }


def make_recovery_attempt_id(now: datetime | None = None) -> str:
    """Return a collision-resistant ID suitable for S3 keys and ECS tokens."""
    created_at = now or datetime.now(UTC)
    if created_at.tzinfo is None:
        raise ValueError("recovery attempt time must be timezone-aware")
    timestamp = created_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{timestamp}-{secrets.token_hex(8)}"


def _strict_json_object(body: bytes, *, label: str) -> dict[str, object]:
    try:
        return decode_strict_json_object(body, label=label)
    except ValueError as exc:
        raise RecoveryInvariantError(str(exc)) from exc


def _read_immutable_input(
    s3: S3Client,
    config: WorkerConfig,
    run_id: str,
) -> tuple[
    tuple[WorkItem, ...],
    str,
    str,
    str | None,
    bool,
    int | None,
    datetime | None,
]:
    """Read and hash the exact input object, retaining its S3 CAS identity."""
    from aws_batch_scraper.aggregate import read_run_manifest

    manifest = read_run_manifest(s3, config, run_id)
    key = f"{config.s3_scraper_prefix}/runs/{run_id}/input.jsonl"
    response = s3.get_object(Bucket=config.s3_bucket, Key=key)
    etag = response.get("ETag")
    if not isinstance(etag, str) or not etag:
        raise RecoveryInvariantError(f"Run input for {run_id} is missing its S3 ETag")
    body = response["Body"].read()
    digest = hashlib.sha256(body).hexdigest()
    version_id = response.get("VersionId")
    if version_id is not None and not isinstance(version_id, str):
        raise RecoveryInvariantError(f"Run input for {run_id} has an invalid S3 VersionId")

    manifest_input_sha = (manifest.model_extra or {}).get("input_sha256")
    if manifest_input_sha is not None and (
        not isinstance(manifest_input_sha, str) or manifest_input_sha != digest
    ):
        raise RecoveryInvariantError(f"Run input for {run_id} does not match manifest input_sha256")
    manifest_force_rescrape = (manifest.model_extra or {}).get("force_rescrape")
    if manifest_force_rescrape is None:
        # Before this field was explicit, full runs always used --force and
        # incremental runs never did. Legacy samples are ambiguous because the
        # CLI allowed --sample together with --force; silently guessing would
        # change same-run queue semantics.
        if manifest.selection_mode == "sample":
            raise RecoveryInvariantError(
                f"Legacy sample run {run_id} does not record force_rescrape; "
                "automatic recovery is unsafe"
            )
        force_rescrape = manifest.selection_mode == "full"
    elif isinstance(manifest_force_rescrape, bool):
        force_rescrape = manifest_force_rescrape
    else:
        raise RecoveryInvariantError(
            f"Run manifest for {run_id} has an invalid force_rescrape value"
        )
    if manifest.selection_mode == "full" and not force_rescrape:
        raise RecoveryInvariantError(f"Full run {run_id} does not preserve force_rescrape=true")
    journal_schema_version = (manifest.model_extra or {}).get(
        "terminal_candidate_journal_schema_version"
    )
    if journal_schema_version is not None and (
        not isinstance(journal_schema_version, int)
        or isinstance(journal_schema_version, bool)
        or journal_schema_version != 1
    ):
        raise RecoveryInvariantError(
            f"Run manifest for {run_id} has an unsupported terminal candidate journal schema"
        )

    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RecoveryInvariantError(f"Run input for {run_id} is not UTF-8") from exc

    items: list[WorkItem] = []
    seen: set[str] = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        decoded = _strict_json_object(
            line.encode(),
            label=f"Run input for {run_id} line {line_number}",
        )
        fields: dict[str, Any] = dict(decoded)
        item_id = fields.pop("item_id", None)
        if not isinstance(item_id, str):
            raise RecoveryInvariantError(
                f"Run input for {run_id} line {line_number} needs a string item_id"
            )
        try:
            item = WorkItem(item_id=item_id, extra=fields)
        except (TypeError, ValueError) as exc:
            raise RecoveryInvariantError(
                f"Run input for {run_id} line {line_number} is invalid"
            ) from exc
        if item.item_id in seen:
            raise RecoveryInvariantError(
                f"Run input for {run_id} contains duplicate item {item.item_id}"
            )
        seen.add(item.item_id)
        items.append(item)

    if not items:
        raise RecoveryInvariantError(f"Run input for {run_id} contains no work items")
    if len(items) != manifest.input_size:
        raise RecoveryInvariantError(
            f"Run input for {run_id} contains {len(items)} items, "
            f"but its manifest declares {manifest.input_size}"
        )
    return (
        tuple(items),
        digest,
        etag,
        version_id,
        force_rescrape,
        journal_schema_version,
        manifest.completed_at,
    )


def inventory_run(
    s3: S3Client,
    config: WorkerConfig,
    run_id: str,
) -> RecoveryInventory:
    """Build a strict, read-only checkpoint inventory for one exact run."""
    from aws_batch_scraper.aggregate import (
        RunResultConflictError,
        aggregate_failures,
        aggregate_results,
        require_no_result_conflicts,
    )
    from aws_batch_scraper.terminal_journal import (
        CandidateJournalError,
        read_terminal_candidate_resolutions,
        read_terminal_candidates,
        read_terminal_decision_conflicts,
        read_terminal_decisions,
    )

    (
        items,
        input_sha256,
        input_etag,
        version_id,
        force_rescrape,
        journal_schema_version,
        manifest_completed_at,
    ) = _read_immutable_input(s3, config, run_id)
    input_ids = frozenset(item.item_id for item in items)
    try:
        conflict_report = require_no_result_conflicts(s3, config, run_id)
    except RunResultConflictError as exc:
        raise RecoveryInvariantError(
            f"Run {run_id} has blocking result-conflict evidence; recovery is blocked"
        ) from exc
    results = aggregate_results(s3, config, run_id=run_id)
    failures = aggregate_failures(s3, config, run_id)
    result_ids = frozenset(results)
    failure_ids = frozenset(failures)

    invalid_result_statuses = sorted(
        item_id
        for item_id, result in results.items()
        if result.status not in {ScrapeStatus.SUCCESS, ScrapeStatus.NO_RESULTS}
    )
    if invalid_result_statuses:
        raise RecoveryInvariantError(
            f"Run {run_id} has non-conclusive objects under results/: "
            f"{', '.join(invalid_result_statuses[:10])}"
        )
    invalid_failure_statuses = sorted(
        item_id
        for item_id, result in failures.items()
        if result.status not in {ScrapeStatus.FAILED, ScrapeStatus.INVALID_INPUT}
    )
    if invalid_failure_statuses:
        raise RecoveryInvariantError(
            f"Run {run_id} has non-failure objects under failures/: "
            f"{', '.join(invalid_failure_statuses[:10])}"
        )

    overlap = result_ids & failure_ids
    if overlap:
        raise RecoveryInvariantError(
            f"Run {run_id} has overlapping result/failure IDs: {', '.join(sorted(overlap)[:10])}"
        )
    extras = (result_ids | failure_ids) - input_ids
    if extras:
        raise RecoveryInvariantError(
            f"Run {run_id} has terminal IDs absent from immutable input: "
            f"{', '.join(sorted(extras)[:10])}"
        )

    try:
        candidates = read_terminal_candidates(s3, config, run_id)
        decisions = read_terminal_decisions(s3, config, run_id)
        decision_conflicts = read_terminal_decision_conflicts(s3, config, run_id)
        candidate_resolutions = read_terminal_candidate_resolutions(s3, config, run_id)
    except CandidateJournalError as exc:
        raise RecoveryInvariantError(
            f"Run {run_id} has invalid terminal-candidate evidence; recovery is blocked"
        ) from exc
    candidate_extras = sorted({candidate.item_id for candidate in candidates}.difference(input_ids))
    if candidate_extras:
        raise RecoveryInvariantError(
            f"Run {run_id} has candidate IDs absent from immutable input: "
            f"{', '.join(candidate_extras[:10])}"
        )
    decision_by_item = {decision.item_id: decision for decision in decisions}
    if len(decision_by_item) != len(decisions):
        raise RecoveryInvariantError(f"Run {run_id} repeats a terminal decision item")
    decision_extras = sorted(set(decision_by_item).difference(input_ids))
    if decision_extras:
        raise RecoveryInvariantError(
            f"Run {run_id} has terminal decision IDs absent from immutable input: "
            f"{', '.join(decision_extras[:10])}"
        )
    decision_conflict_candidates = {
        (conflict.item_id, conflict.candidate_key) for conflict in decision_conflicts
    }
    if len(decision_conflict_candidates) != len(decision_conflicts):
        raise RecoveryInvariantError(f"Run {run_id} repeats terminal decision conflicts")
    resolved_candidate_keys = {resolution.candidate_key for resolution in candidate_resolutions}
    candidate_keys = {candidate.key for candidate in candidates}
    orphan_resolution_candidates = sorted(resolved_candidate_keys.difference(candidate_keys))
    if orphan_resolution_candidates:
        raise RecoveryInvariantError(
            f"Run {run_id} has terminal candidate resolutions without candidate evidence"
        )
    failure_conflicts = _read_failure_conflicts(s3, config, run_id)
    failure_conflict_keys = {conflict.key for conflict in failure_conflicts}
    resolved_failure_conflict_keys = {
        f"{config.s3_scraper_prefix}/runs/{run_id}/failure-conflicts/v1/"
        f"{resolution.item_id}/{resolution.candidate_sha256}.json"
        for resolution in candidate_resolutions
        if resolution.decision_kind == resolution.candidate_kind == "failure"
    }
    unresolved_failure_conflicts = tuple(
        sorted(failure_conflict_keys.difference(resolved_failure_conflict_keys))
    )
    if unresolved_failure_conflicts:
        raise RecoveryInvariantError(
            f"Run {run_id} has {len(unresolved_failure_conflicts)} unresolved "
            "failure-conflict artifact(s); recovery is blocked"
        )
    for item_id, decision in decision_by_item.items():
        if item_id in results:
            canonical_kind = "result"
            canonical = results[item_id]
        elif item_id in failures:
            canonical_kind = "failure"
            canonical = failures[item_id]
        else:
            # Candidate and decision precede compatibility CAS. The missing ID
            # remains safely resumable from the retained winning candidate.
            continue
        canonical_body = s3.get_object(
            Bucket=config.s3_bucket,
            Key=decision.canonical_key,
        )["Body"].read()
        if (
            decision.kind != canonical_kind
            or decision.candidate.result != canonical
            or hashlib.sha256(canonical_body).hexdigest() != decision.candidate.candidate_sha256
        ):
            raise RecoveryInvariantError(
                f"Run {run_id} terminal decision for {item_id} does not match canonical state"
            )
    if journal_schema_version == 1:
        missing_decisions = sorted((result_ids | failure_ids).difference(decision_by_item))
        if missing_decisions:
            raise RecoveryInvariantError(
                f"Run {run_id} has canonical terminal objects without required "
                "terminal decisions: "
                f"{', '.join(missing_decisions[:10])}"
            )
    candidate_conflicts: list[str] = []
    for candidate in candidates:
        if candidate.item_id in results:
            canonical_kind = "result"
            canonical = results[candidate.item_id]
        elif candidate.item_id in failures:
            canonical_kind = "failure"
            canonical = failures[candidate.item_id]
        else:
            # Candidate-before-CAS is intentionally non-terminal. A recovery
            # may seed that still-missing ID and preserve this observation.
            continue
        disagrees = candidate.kind != canonical_kind or semantic_observation(
            candidate.result
        ) != semantic_observation(canonical)
        exact_conflict_key = (
            f"{config.s3_scraper_prefix}/runs/{run_id}/result-conflicts/v2/"
            f"{candidate.item_id}/{candidate.candidate_sha256}.json"
        )
        reviewed_accept_canonical = (
            candidate.kind == canonical_kind == "result"
            and exact_conflict_key in conflict_report.resolved_keys
        )
        reviewed_accept_decision = candidate.key in resolved_candidate_keys
        if disagrees and not (reviewed_accept_canonical or reviewed_accept_decision):
            candidate_conflicts.append(
                f"{candidate.item_id}:{candidate.kind}:{candidate.candidate_sha256[:12]}"
            )
    if candidate_conflicts:
        raise RecoveryInvariantError(
            f"Run {run_id} has {len(candidate_conflicts)} terminal candidate(s) "
            "that disagree with canonical state: "
            f"{', '.join(candidate_conflicts[:10])}"
        )
    if journal_schema_version == 1:
        journaled_canonicals = {(candidate.item_id, candidate.kind) for candidate in candidates}
        missing_candidate_evidence = sorted(
            item_id for item_id in result_ids if (item_id, "result") not in journaled_canonicals
        ) + sorted(
            item_id for item_id in failure_ids if (item_id, "failure") not in journaled_canonicals
        )
        if missing_candidate_evidence:
            raise RecoveryInvariantError(
                f"Run {run_id} has canonical terminal objects without required "
                "candidate-journal evidence: "
                f"{', '.join(missing_candidate_evidence[:10])}"
            )

    candidate_entries: list[dict[str, object]] = [
        {
            "key": candidate.key,
            "item_id": candidate.item_id,
            "kind": candidate.kind,
            "candidate_sha256": candidate.candidate_sha256,
            "observation_sha256": candidate.observation_sha256,
        }
        for candidate in candidates
    ]
    candidate_entries.extend(
        {
            "key": decision.key,
            "item_id": decision.item_id,
            "kind": "terminal-decision",
            "candidate_sha256": decision.candidate.candidate_sha256,
            "observation_sha256": decision.candidate.observation_sha256,
        }
        for decision in decisions
    )
    candidate_entries.extend(
        {
            "key": conflict.key,
            "item_id": conflict.item_id,
            "kind": "terminal-decision-conflict",
            "candidate_sha256": conflict.candidate_sha256,
            "observation_sha256": conflict.decision_candidate_sha256,
        }
        for conflict in decision_conflicts
    )
    candidate_entries.extend(
        {
            "key": resolution.key,
            "item_id": resolution.item_id,
            "kind": "terminal-candidate-resolution",
            "candidate_sha256": resolution.candidate_sha256,
            "observation_sha256": resolution.decision_sha256,
        }
        for resolution in candidate_resolutions
    )
    for failure_conflict in failure_conflicts:
        candidate_entries.append(
            {
                "key": failure_conflict.key,
                "item_id": failure_conflict.item_id,
                "kind": "failure-conflict",
                "candidate_sha256": failure_conflict.candidate_sha256,
                "observation_sha256": failure_conflict.body_sha256,
            }
        )
    candidate_entries.sort(key=lambda entry: str(entry["key"]))
    candidate_evidence_body = json.dumps(
        candidate_entries,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()

    terminal_entries: list[dict[str, object]] = []
    for kind, observations in (("result", results), ("failure", failures)):
        for item_id, observation in sorted(observations.items()):
            terminal_entries.append(
                {
                    "kind": kind,
                    "item_id": item_id,
                    "observation": observation.model_dump(mode="json"),
                }
            )
    terminal_evidence_body = json.dumps(
        terminal_entries,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    completed = result_ids | failure_ids
    missing_ids = tuple(item.item_id for item in items if item.item_id not in completed)
    return RecoveryInventory(
        run_id=run_id,
        items=items,
        input_sha256=input_sha256,
        input_etag=input_etag,
        input_version_id=version_id,
        force_rescrape=force_rescrape,
        terminal_candidate_journal_schema_version=journal_schema_version,
        manifest_completed_at=manifest_completed_at,
        result_ids=result_ids,
        failure_ids=failure_ids,
        missing_ids=missing_ids,
        terminal_evidence_sha256=hashlib.sha256(terminal_evidence_body).hexdigest(),
        candidate_count=len(candidates),
        candidate_evidence_sha256=hashlib.sha256(candidate_evidence_body).hexdigest(),
        conflict_policy_version=conflict_report.conflict_policy_version,
        conflict_evidence_sha256=conflict_report.evidence_sha256,
        resolved_conflict_count=conflict_report.resolved_count,
        invalid_resolution_count=conflict_report.invalid_resolution_count,
    )


def _read_failure_conflicts(
    s3: S3Client,
    config: WorkerConfig,
    run_id: str,
) -> tuple[_FailureConflictEvidence, ...]:
    prefix = f"{config.s3_scraper_prefix}/runs/{run_id}/failure-conflicts/"
    paginator = s3.get_paginator("list_objects_v2")
    keys: set[str] = set()
    for page in paginator.paginate(Bucket=config.s3_bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj.get("Key")
            if isinstance(key, str) and key.startswith(prefix) and key != prefix:
                keys.add(key)
    required_fields = {
        "schema_version",
        "terminal_status",
        "run_id",
        "item_id",
        "detected_at",
        "reason",
        "canonical_failure_key",
        "existing_sha256",
        "candidate_sha256",
        "existing_observation",
        "candidate_observation",
        "candidate_body_base64",
    }
    conflicts: list[_FailureConflictEvidence] = []
    for key in sorted(keys):
        if not key.endswith(".json"):
            raise RecoveryInvariantError(f"Unexpected non-JSON failure conflict object {key}")
        body = s3.get_object(Bucket=config.s3_bucket, Key=key)["Body"].read()
        record = _strict_json_object(body, label=f"Failure conflict {key}")
        if set(record) != required_fields:
            raise RecoveryInvariantError(
                f"Failure conflict {key} fields are incomplete or unexpected"
            )
        if (
            type(record.get("schema_version")) is not int
            or record.get("schema_version") != 1
            or record.get("terminal_status") != "failure-conflict"
            or record.get("run_id") != run_id
        ):
            raise RecoveryInvariantError(f"Failure conflict {key} has invalid identity")
        item_id = record.get("item_id")
        candidate_sha256 = record.get("candidate_sha256")
        existing_sha256 = record.get("existing_sha256")
        if not isinstance(item_id, str) or not item_id:
            raise RecoveryInvariantError(f"Failure conflict {key} has an invalid item ID")
        for label, digest in (
            ("candidate", candidate_sha256),
            ("canonical", existing_sha256),
        ):
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise RecoveryInvariantError(
                    f"Failure conflict {key} has an invalid {label} digest"
                )
        expected_key = f"{prefix}v1/{item_id}/{candidate_sha256}.json"
        if key != expected_key:
            raise RecoveryInvariantError(f"Failure conflict {key} does not match its key identity")
        detected_at = record.get("detected_at")
        try:
            parsed_detected_at = (
                datetime.fromisoformat(detected_at) if isinstance(detected_at, str) else None
            )
        except ValueError as exc:
            raise RecoveryInvariantError(
                f"Failure conflict {key} has an invalid detected_at"
            ) from exc
        if (
            parsed_detected_at is None
            or parsed_detected_at.tzinfo is None
            or parsed_detected_at.utcoffset() is None
        ):
            raise RecoveryInvariantError(
                f"Failure conflict {key} detected_at must include a timezone"
            )
        reason = record.get("reason")
        encoded_candidate = record.get("candidate_body_base64")
        if not isinstance(reason, str) or not reason.strip():
            raise RecoveryInvariantError(f"Failure conflict {key} has an invalid reason")
        if not isinstance(encoded_candidate, str):
            raise RecoveryInvariantError(
                f"Failure conflict {key} lacks retained candidate evidence"
            )
        try:
            candidate_body = base64.b64decode(encoded_candidate, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise RecoveryInvariantError(
                f"Failure conflict {key} candidate evidence is not strict base64"
            ) from exc
        if hashlib.sha256(candidate_body).hexdigest() != candidate_sha256:
            raise RecoveryInvariantError(f"Failure conflict {key} candidate digest does not match")
        candidate_object = _strict_json_object(
            candidate_body,
            label=f"Failure conflict candidate {key}",
        )
        if set(candidate_object) != set(ScrapeResult.model_fields) | {"failed_at"}:
            raise RecoveryInvariantError(
                f"Failure conflict {key} candidate fields are incomplete or unexpected"
            )
        candidate = ScrapeResult.model_validate(candidate_object)
        if (
            candidate.run_id != run_id
            or candidate.item_id != item_id
            or candidate.status not in {ScrapeStatus.FAILED, ScrapeStatus.INVALID_INPUT}
            or candidate.is_soft_blocked
            or candidate.is_network_error
            or record.get("candidate_observation") != semantic_observation(candidate)
        ):
            raise RecoveryInvariantError(f"Failure conflict {key} candidate evidence is invalid")
        canonical_key = f"{config.s3_scraper_prefix}/runs/{run_id}/failures/{item_id}.json"
        if record.get("canonical_failure_key") != canonical_key:
            raise RecoveryInvariantError(f"Failure conflict {key} has an invalid canonical key")
        canonical_body = s3.get_object(
            Bucket=config.s3_bucket,
            Key=canonical_key,
        )["Body"].read()
        if hashlib.sha256(canonical_body).hexdigest() != existing_sha256:
            raise RecoveryInvariantError(f"Failure conflict {key} canonical digest does not match")
        canonical_object = _strict_json_object(
            canonical_body,
            label=f"Failure conflict canonical {key}",
        )
        if set(canonical_object) != set(ScrapeResult.model_fields) | {"failed_at"}:
            raise RecoveryInvariantError(
                f"Failure conflict {key} canonical fields are incomplete or unexpected"
            )
        canonical = ScrapeResult.model_validate(canonical_object)
        canonical_observation = semantic_observation(canonical)
        if (
            canonical.run_id != run_id
            or canonical.item_id != item_id
            or canonical.status not in {ScrapeStatus.FAILED, ScrapeStatus.INVALID_INPUT}
            or canonical.is_soft_blocked
            or canonical.is_network_error
            or record.get("existing_observation") != canonical_observation
            or record.get("candidate_observation") == canonical_observation
        ):
            raise RecoveryInvariantError(f"Failure conflict {key} canonical evidence is invalid")
        conflicts.append(
            _FailureConflictEvidence(
                key=key,
                item_id=item_id,
                candidate_sha256=str(candidate_sha256),
                body_sha256=hashlib.sha256(body).hexdigest(),
            )
        )
    return tuple(conflicts)


def require_exact_terminal_coverage(
    s3: S3Client,
    config: WorkerConfig,
    run_id: str,
) -> RecoveryInventory:
    """Prove each immutable input has exactly one trusted terminal artifact."""
    inventory = inventory_run(s3, config, run_id)
    if inventory.missing_ids:
        raise RecoveryInvariantError(
            f"Run {run_id} is missing {len(inventory.missing_ids)} terminal artifact(s): "
            f"{', '.join(inventory.missing_ids[:10])}"
        )
    return inventory


def _task_record_keys(s3: S3Client, config: WorkerConfig, run_id: str) -> list[str]:
    prefix = f"{config.s3_scraper_prefix}/runs/{run_id}/recovery-attempts/"
    paginator = s3.get_paginator("list_objects_v2")
    keys: set[str] = set()
    for page in paginator.paginate(Bucket=config.s3_bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj.get("Key")
            if isinstance(key, str) and key.startswith(prefix) and key.endswith("/tasks.json"):
                keys.add(key)
    return sorted(keys)


def _recovery_attempt_ids(
    s3: S3Client,
    config: WorkerConfig,
    run_id: str,
) -> tuple[str, ...]:
    """List attempt identities backed by append-only recovery plans."""
    prefix = f"{config.s3_scraper_prefix}/runs/{run_id}/recovery-attempts/"
    paginator = s3.get_paginator("list_objects_v2")
    attempt_ids: set[str] = set()
    for page in paginator.paginate(Bucket=config.s3_bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj.get("Key")
            if not isinstance(key, str) or not key.startswith(prefix):
                continue
            parts = key.removeprefix(prefix).split("/")
            if len(parts) == 2 and parts[0] and parts[1] == "plan.json":
                attempt_ids.add(parts[0])
    return tuple(sorted(attempt_ids))


def read_prior_task_arns(
    s3: S3Client,
    config: WorkerConfig,
    run_id: str,
) -> tuple[str, ...]:
    """Read initial and append-only recovery worker task identities."""
    from aws_batch_scraper.orchestrate import get_task_arns

    ambiguous_recorded_at: datetime | None = None
    try:
        arns = list(get_task_arns(s3, config, run_id))
    except FileNotFoundError:
        arns = []
        key = f"{config.s3_scraper_prefix}/runs/{run_id}/submission-recovery.json"
        try:
            response = s3.get_object(Bucket=config.s3_bucket, Key=key)
        except ClientError as exc:
            if _is_not_found(exc):
                raise RecoveryInvariantError(
                    f"Run {run_id} has neither task identities nor submission recovery evidence"
                ) from exc
            raise
        record = _strict_json_object(
            response["Body"].read(),
            label=f"Submission recovery record {key}",
        )
        if record.get("run_id") != run_id:
            raise RecoveryInvariantError(
                "Submission recovery record has the wrong run ID"
            ) from None
        phase = record.get("phase")
        values = record.get("task_arns")
        if not isinstance(phase, str) or not isinstance(values, list):
            raise RecoveryInvariantError("Submission recovery record is incomplete") from None
        for value in values:
            if not isinstance(value, str) or not value.startswith("arn:") or "/" not in value:
                raise RecoveryInvariantError(
                    "Submission recovery record has an invalid task ARN"
                ) from None
            arns.append(value)
        if phase in {"workers-started", "workers-partially-started", "monitor-started"}:
            if not arns:
                raise RecoveryInvariantError(
                    f"Submission recovery phase {phase} requires known worker tasks"
                ) from None
        elif phase == "worker-launch-unknown":
            if arns:
                raise RecoveryInvariantError(
                    "Ambiguous zero-task submission evidence unexpectedly contains task ARNs"
                ) from None
            recorded_value = record.get("recorded_at")
            if not isinstance(recorded_value, str):
                raise RecoveryInvariantError(
                    "Ambiguous submission recovery evidence lacks recorded_at"
                ) from None
            try:
                recorded_at = datetime.fromisoformat(recorded_value)
            except ValueError as exc:
                raise RecoveryInvariantError(
                    "Ambiguous submission recovery evidence has invalid recorded_at"
                ) from exc
            if recorded_at.tzinfo is None:
                raise RecoveryInvariantError(
                    "Ambiguous submission recovery recorded_at must be timezone-aware"
                ) from None
            ambiguous_recorded_at = recorded_at
        elif arns:
            raise RecoveryInvariantError(
                f"Pre-launch submission recovery phase {phase} cannot contain task ARNs"
            ) from None
    for key in _task_record_keys(s3, config, run_id):
        record = _strict_json_object(
            s3.get_object(Bucket=config.s3_bucket, Key=key)["Body"].read(),
            label=f"Recovery task record {key}",
        )
        if record.get("run_id") != run_id:
            raise RecoveryInvariantError(f"Recovery task record {key} has the wrong run ID")
        task_arns = record.get("task_arns")
        if not isinstance(task_arns, list) or not task_arns:
            raise RecoveryInvariantError(
                f"Recovery task record {key} needs a non-empty task_arns list"
            )
        for task_arn in task_arns:
            if (
                not isinstance(task_arn, str)
                or not task_arn.startswith("arn:")
                or "/" not in task_arn
            ):
                raise RecoveryInvariantError(f"Recovery task record {key} has an invalid ARN")
            arns.append(task_arn)
    if len(set(arns)) != len(arns):
        raise RecoveryInvariantError(f"Run {run_id} repeats a worker task ARN in its evidence")
    if ambiguous_recorded_at is not None:
        raise _AmbiguousInitialLaunch(ambiguous_recorded_at, tuple(arns))
    return tuple(arns)


def require_prior_tasks_stopped(
    ecs: ECSClient,
    config: SubmitterConfig,
    task_arns: tuple[str, ...],
) -> None:
    """Prove every previously recorded worker task is terminal in ECS."""
    if not task_arns:
        return
    for offset in range(0, len(task_arns), 100):
        batch = task_arns[offset : offset + 100]
        response = ecs.describe_tasks(cluster=config.ecs_cluster_arn, tasks=list(batch))
        if response.get("failures"):
            raise RecoveryInvariantError(
                f"ECS could not resolve all prior worker tasks: {response['failures']}"
            )
        tasks = response.get("tasks", [])
        described = {task.get("taskArn") for task in tasks if isinstance(task.get("taskArn"), str)}
        missing = set(batch) - described
        if missing:
            raise RecoveryInvariantError(
                f"ECS omitted {len(missing)} prior worker task(s): "
                f"{', '.join(sorted(missing)[:10])}"
            )
        live = sorted(str(task["taskArn"]) for task in tasks if task.get("lastStatus") != "STOPPED")
        if live:
            raise RecoveryInvariantError(
                f"Recovery is blocked while {len(live)} prior worker task(s) are live: "
                f"{', '.join(live[:10])}"
            )


def read_queue_state(sqs: SQSClient, config: WorkerConfig) -> QueueState:
    """Read visible, in-flight, and delayed counts without treating any as zero."""
    response = sqs.get_queue_attributes(
        QueueUrl=config.sqs_queue_url,
        AttributeNames=list(_QUEUE_ATTRIBUTES),
    )
    attrs = response.get("Attributes")
    if not isinstance(attrs, dict):
        raise RecoveryInvariantError("Main queue response is missing Attributes")
    try:
        values = (
            int(attrs["ApproximateNumberOfMessages"]),
            int(attrs["ApproximateNumberOfMessagesNotVisible"]),
            int(attrs["ApproximateNumberOfMessagesDelayed"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RecoveryInvariantError("Main queue response lacks complete numeric counts") from exc
    if any(value < 0 for value in values):
        raise RecoveryInvariantError("Main queue returned a negative message count")
    return QueueState(*values)


def require_stable_queue_state(
    sqs: SQSClient,
    config: WorkerConfig,
    *,
    settle_seconds: float = 60.0,
) -> QueueState:
    """Require a documented quiet window across approximate SQS observations."""
    if settle_seconds < 0:
        raise ValueError("queue settle interval must not be negative")
    first = read_queue_state(sqs, config)
    if settle_seconds:
        time.sleep(settle_seconds)
    second = read_queue_state(sqs, config)
    if first != second:
        raise RecoveryInvariantError(
            f"Main queue counts changed during recovery preflight: {first} -> {second}"
        )
    if second.in_flight:
        raise RecoveryInvariantError(
            "Main queue still reports in-flight work after every prior task stopped"
        )
    return second


def build_recovery_plan(
    s3: S3Client,
    sqs: SQSClient,
    ecs: ECSClient,
    config: SubmitterConfig,
    run_id: str,
    *,
    attempt_id: str | None = None,
    now: datetime | None = None,
) -> RecoveryPlan:
    """Perform the complete read-only preflight and select one safe action."""
    if not run_id.strip() or "/" in run_id:
        raise ValueError("run ID must be a non-blank path segment")
    if now is not None and now.tzinfo is None:
        raise ValueError("recovery plan time must be timezone-aware")
    if attempt_id is not None and (not attempt_id.strip() or "/" in attempt_id):
        raise ValueError("recovery attempt ID must be a non-blank path segment")
    inventory = inventory_run(s3, config, run_id)
    prior_task_discovery: tuple[str, ...] = ()
    try:
        prior_task_arns = read_prior_task_arns(s3, config, run_id)
    except _AmbiguousInitialLaunch as exc:
        observed_at = now or datetime.now(UTC)
        if (observed_at - exc.recorded_at).total_seconds() < 60:
            raise RecoveryInvariantError(
                "Ambiguous initial launch is too recent for safe ECS discovery"
            ) from exc
        from aws_batch_scraper.orchestrate import _ecs_started_by

        started_by = _ecs_started_by(run_id, "worker")
        prior_task_arns = exc.task_arns
        prior_task_discovery = (started_by,)
    from aws_batch_scraper.orchestrate import _ecs_started_by

    normal_monitor_started_by = _ecs_started_by(run_id, "monitor")
    recovery_identities: list[str] = []
    for prior_attempt_id in _recovery_attempt_ids(s3, config, run_id):
        recovery_identities.extend(
            (
                _ecs_started_by(
                    run_id,
                    "worker",
                    recovery_attempt_id=prior_attempt_id,
                ),
                _ecs_started_by(
                    run_id,
                    "monitor",
                    recovery_attempt_id=prior_attempt_id,
                ),
            )
        )
    prior_task_discovery = tuple(
        dict.fromkeys((*prior_task_discovery, normal_monitor_started_by, *recovery_identities))
    )
    require_prior_tasks_stopped(ecs, config, prior_task_arns)
    _require_no_live_started_by_set(ecs, config, prior_task_discovery)
    queue = require_stable_queue_state(sqs, config)

    if inventory.manifest_completed_at is not None:
        if inventory.missing_ids:
            raise RecoveryInvariantError(
                f"Completed run {run_id} no longer has exact terminal coverage"
            )
        if queue.total:
            raise RecoveryInvariantError(
                f"Completed run {run_id} has a nonempty main queue; scraper recovery "
                "cannot safely re-enter after downstream dispatch"
            )
        action = RecoveryAction.COMPLETE
    elif queue.total:
        # Standard SQS may redeliver a message after its exact-run checkpoint
        # exists. Attempt workers drain each queued delivery through one fresh
        # lookup and the full candidate/decision/conflict evidence protocol.
        action = RecoveryAction.LAUNCH_EXISTING_QUEUE
    elif not inventory.missing_ids:
        action = RecoveryAction.COMPLETE
    else:
        action = RecoveryAction.SEED_MISSING

    created_at = now or datetime.now(UTC)
    if created_at.tzinfo is None:
        raise ValueError("recovery plan time must be timezone-aware")
    resolved_attempt_id = attempt_id or make_recovery_attempt_id(created_at)
    return RecoveryPlan(
        run_id=run_id,
        attempt_id=resolved_attempt_id,
        created_at=created_at,
        action=action,
        inventory=inventory,
        queue=queue,
        prior_task_arns=prior_task_arns,
        prior_task_discovery=prior_task_discovery,
    )


def _attempt_key(config: WorkerConfig, plan: RecoveryPlan, filename: str) -> str:
    return (
        f"{config.s3_scraper_prefix}/runs/{plan.run_id}/recovery-attempts/"
        f"{plan.attempt_id}/{filename}"
    )


def _put_append_only_json(
    s3: S3Client,
    config: WorkerConfig,
    *,
    key: str,
    value: dict[str, object],
) -> None:
    s3.put_object(
        Bucket=config.s3_bucket,
        Key=key,
        Body=json.dumps(value, indent=2, allow_nan=False).encode(),
        ContentType="application/json",
        IfNoneMatch="*",
    )


def verify_plan_is_current(
    s3: S3Client,
    config: WorkerConfig,
    plan: RecoveryPlan,
) -> RecoveryInventory:
    """Re-inventory immediately before mutation and reject stale plans."""
    key = f"{config.s3_scraper_prefix}/runs/{plan.run_id}/input.jsonl"
    response = s3.get_object(
        Bucket=config.s3_bucket,
        Key=key,
        IfMatch=plan.inventory.input_etag,
    )
    current_input_sha256 = hashlib.sha256(response["Body"].read()).hexdigest()
    if current_input_sha256 != plan.inventory.input_sha256:
        raise RecoveryInvariantError("Immutable run input changed after recovery planning")

    current = inventory_run(s3, config, plan.run_id)
    comparable = (
        current.input_sha256,
        current.force_rescrape,
        current.terminal_candidate_journal_schema_version,
        current.manifest_completed_at,
        current.result_ids,
        current.failure_ids,
        current.missing_ids,
        current.terminal_evidence_sha256,
        current.candidate_count,
        current.candidate_evidence_sha256,
        current.conflict_policy_version,
        current.conflict_evidence_sha256,
    )
    planned = (
        plan.inventory.input_sha256,
        plan.inventory.force_rescrape,
        plan.inventory.terminal_candidate_journal_schema_version,
        plan.inventory.manifest_completed_at,
        plan.inventory.result_ids,
        plan.inventory.failure_ids,
        plan.inventory.missing_ids,
        plan.inventory.terminal_evidence_sha256,
        plan.inventory.candidate_count,
        plan.inventory.candidate_evidence_sha256,
        plan.inventory.conflict_policy_version,
        plan.inventory.conflict_evidence_sha256,
    )
    if comparable != planned:
        raise RecoveryInvariantError("Run artifacts changed after recovery planning")
    return current


def write_recovery_plan(
    s3: S3Client,
    config: WorkerConfig,
    plan: RecoveryPlan,
) -> str:
    """Persist a CAS-created plan before queue or ECS mutations."""
    verify_plan_is_current(s3, config, plan)
    key = _attempt_key(config, plan, "plan.json")
    _put_append_only_json(s3, config, key=key, value=plan.as_dict())
    logger.info(f"Persisted append-only recovery plan: s3://{config.s3_bucket}/{key}")
    return key


def write_recovery_tasks(
    s3: S3Client,
    config: WorkerConfig,
    plan: RecoveryPlan,
    task_arns: list[str],
) -> str:
    """Persist the exact tasks launched with one recovery attempt token."""
    from aws_batch_scraper.orchestrate import _ecs_started_by

    if not task_arns or len(set(task_arns)) != len(task_arns):
        raise ValueError("Recovery task evidence requires distinct task ARNs")
    key = _attempt_key(config, plan, "tasks.json")
    record: dict[str, object] = {
        "schema_version": _RECOVERY_SCHEMA_VERSION,
        "run_id": plan.run_id,
        "attempt_id": plan.attempt_id,
        "recorded_at": datetime.now(UTC).isoformat(),
        "ecs_client_token_scope": f"{plan.run_id}:recovery-worker:{plan.attempt_id}",
        "ecs_started_by": _ecs_started_by(
            plan.run_id,
            "worker",
            recovery_attempt_id=plan.attempt_id,
        ),
        "task_arns": task_arns,
    }
    _put_append_only_json(s3, config, key=key, value=record)
    return key


def read_recovery_task_arns(
    s3: S3Client,
    config: WorkerConfig,
    run_id: str,
    attempt_id: str,
) -> tuple[str, ...]:
    """Read the immutable task set for one exact recovery attempt."""
    key = f"{config.s3_scraper_prefix}/runs/{run_id}/recovery-attempts/{attempt_id}/tasks.json"
    record = _strict_json_object(
        s3.get_object(Bucket=config.s3_bucket, Key=key)["Body"].read(),
        label=f"Recovery task record {key}",
    )
    if record.get("run_id") != run_id or record.get("attempt_id") != attempt_id:
        raise RecoveryInvariantError(f"Recovery task record {key} has the wrong identity")
    values = record.get("task_arns")
    if not isinstance(values, list) or not values:
        raise RecoveryInvariantError(f"Recovery task record {key} has no task ARNs")
    task_arns: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.startswith("arn:") or "/" not in value:
            raise RecoveryInvariantError(f"Recovery task record {key} has an invalid ARN")
        task_arns.append(value)
    if len(set(task_arns)) != len(task_arns):
        raise RecoveryInvariantError(f"Recovery task record {key} repeats a task ARN")
    return tuple(task_arns)


def write_recovery_monitor_task(
    s3: S3Client,
    config: WorkerConfig,
    plan: RecoveryPlan,
    monitor_task_arn: str,
) -> str:
    """Persist the separately tokened recovery coordinator identity."""
    from aws_batch_scraper.orchestrate import _ecs_started_by

    if not monitor_task_arn.startswith("arn:") or "/" not in monitor_task_arn:
        raise ValueError("Recovery monitor evidence requires a valid task ARN")
    key = _attempt_key(config, plan, "monitor-task.json")
    record: dict[str, object] = {
        "schema_version": _RECOVERY_SCHEMA_VERSION,
        "run_id": plan.run_id,
        "attempt_id": plan.attempt_id,
        "recorded_at": datetime.now(UTC).isoformat(),
        "ecs_client_token_scope": f"{plan.run_id}:recovery-monitor:{plan.attempt_id}",
        "ecs_started_by": _ecs_started_by(
            plan.run_id,
            "monitor",
            recovery_attempt_id=plan.attempt_id,
        ),
        "task_arn": monitor_task_arn,
    }
    _put_append_only_json(s3, config, key=key, value=record)
    return key


def write_recovery_launch_failure(
    s3: S3Client,
    config: WorkerConfig,
    plan: RecoveryPlan,
    *,
    role: Literal["worker", "monitor"],
    detail: str,
    launch_ambiguous: bool,
    confirmed_task_arns: list[str] | None = None,
) -> str:
    """Persist fail-closed launch evidence even when no task response is usable."""
    from aws_batch_scraper.orchestrate import _ecs_started_by

    task_arns = confirmed_task_arns or []
    if len(set(task_arns)) != len(task_arns):
        raise ValueError("Recovery launch-failure evidence repeats a task ARN")
    key = _attempt_key(config, plan, f"{role}-launch-failure.json")
    record: dict[str, object] = {
        "schema_version": _RECOVERY_SCHEMA_VERSION,
        "run_id": plan.run_id,
        "attempt_id": plan.attempt_id,
        "recorded_at": datetime.now(UTC).isoformat(),
        "role": role,
        "detail": detail,
        "launch_ambiguous": launch_ambiguous,
        "confirmed_task_arns": task_arns,
        "ecs_client_token_scope": f"{plan.run_id}:recovery-{role}:{plan.attempt_id}",
        "ecs_started_by": _ecs_started_by(
            plan.run_id,
            role,
            recovery_attempt_id=plan.attempt_id,
        ),
        "lease_action": "retain-required" if launch_ambiguous or task_arns else "release-requested",
    }
    _put_append_only_json(s3, config, key=key, value=record)
    return key


def _is_not_found(exc: ClientError) -> bool:
    return str(exc.response.get("Error", {}).get("Code", "")) in {
        "404",
        "NoSuchKey",
        "NotFound",
    }


def _read_optional_attempt_record(
    s3: S3Client,
    config: WorkerConfig,
    run_id: str,
    attempt_id: str,
    filename: str,
) -> dict[str, object] | None:
    key = f"{config.s3_scraper_prefix}/runs/{run_id}/recovery-attempts/{attempt_id}/{filename}"
    try:
        response = s3.get_object(Bucket=config.s3_bucket, Key=key)
    except ClientError as exc:
        if _is_not_found(exc):
            return None
        raise
    record = _strict_json_object(
        response["Body"].read(),
        label=f"Recovery attempt record {key}",
    )
    if record.get("run_id") != run_id or record.get("attempt_id") != attempt_id:
        raise RecoveryInvariantError(f"Recovery attempt record {key} has the wrong identity")
    return record


def _read_recovery_plan_created_at(
    s3: S3Client,
    config: WorkerConfig,
    run_id: str,
    attempt_id: str,
) -> datetime:
    record = _read_optional_attempt_record(
        s3,
        config,
        run_id,
        attempt_id,
        "plan.json",
    )
    if record is None:
        raise RecoveryInvariantError(
            f"Recovery attempt {attempt_id} has no append-only plan evidence"
        )
    value = record.get("created_at")
    if not isinstance(value, str):
        raise RecoveryInvariantError("Recovery plan has an invalid created_at timestamp")
    try:
        created_at = datetime.fromisoformat(value)
    except ValueError as exc:
        raise RecoveryInvariantError("Recovery plan has an invalid created_at timestamp") from exc
    if created_at.tzinfo is None:
        raise RecoveryInvariantError("Recovery plan created_at must be timezone-aware")
    return created_at


def _record_task_arns(
    record: dict[str, object],
    *,
    field: str,
    label: str,
) -> tuple[str, ...]:
    values = record.get(field)
    if not isinstance(values, list):
        raise RecoveryInvariantError(f"{label} must contain a {field} list")
    arns: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.startswith("arn:") or "/" not in value:
            raise RecoveryInvariantError(f"{label} contains an invalid task ARN")
        arns.append(value)
    if len(set(arns)) != len(arns):
        raise RecoveryInvariantError(f"{label} repeats a task ARN")
    return tuple(arns)


def read_recovery_attempt_task_arns(
    s3: S3Client,
    config: WorkerConfig,
    run_id: str,
    attempt_id: str,
) -> tuple[str, ...]:
    """Collect every task ARN durably known for one interrupted attempt."""
    arns: set[str] = set()
    tasks = _read_optional_attempt_record(s3, config, run_id, attempt_id, "tasks.json")
    if tasks is not None:
        arns.update(_record_task_arns(tasks, field="task_arns", label="Recovery task record"))
    monitor = _read_optional_attempt_record(
        s3,
        config,
        run_id,
        attempt_id,
        "monitor-task.json",
    )
    if monitor is not None:
        task_arn = monitor.get("task_arn")
        if not isinstance(task_arn, str) or not task_arn.startswith("arn:") or "/" not in task_arn:
            raise RecoveryInvariantError("Recovery monitor record contains an invalid task ARN")
        arns.add(task_arn)
    for role in ("worker", "monitor"):
        failure = _read_optional_attempt_record(
            s3,
            config,
            run_id,
            attempt_id,
            f"{role}-launch-failure.json",
        )
        if failure is not None:
            arns.update(
                _record_task_arns(
                    failure,
                    field="confirmed_task_arns",
                    label=f"Recovery {role} launch-failure record",
                )
            )
    return tuple(sorted(arns))


def _list_tasks_started_by(
    ecs: ECSClient,
    config: SubmitterConfig,
    started_by: str,
) -> tuple[str, ...]:
    """List running or not-yet-stopped tasks for one ECS launch identity."""
    arns: set[str] = set()
    next_token: str | None = None
    seen_tokens: set[str] = set()
    while True:
        if next_token is None:
            response = ecs.list_tasks(
                cluster=config.ecs_cluster_arn,
                startedBy=started_by,
            )
        else:
            response = ecs.list_tasks(
                cluster=config.ecs_cluster_arn,
                startedBy=started_by,
                nextToken=next_token,
            )
        for task_arn in response.get("taskArns", []):
            if (
                not isinstance(task_arn, str)
                or not task_arn.startswith("arn:")
                or "/" not in task_arn
            ):
                raise RecoveryInvariantError("ECS ListTasks returned an invalid task ARN")
            arns.add(task_arn)
        value = response.get("nextToken")
        if value is None:
            break
        if not isinstance(value, str) or not value or value in seen_tokens:
            raise RecoveryInvariantError("ECS ListTasks returned an invalid pagination token")
        seen_tokens.add(value)
        next_token = value

    # ECS does not allow ``startedBy`` together with another ListTasks filter.
    # A task whose desiredStatus already changed to STOPPED can therefore be
    # omitted from the query above while its lastStatus is still STOPPING. List
    # that topology separately, then filter typed DescribeTasks responses.
    stopped_candidates: list[str] = []
    next_token = None
    seen_tokens.clear()
    while True:
        if next_token is None:
            response = ecs.list_tasks(
                cluster=config.ecs_cluster_arn,
                desiredStatus="STOPPED",
            )
        else:
            response = ecs.list_tasks(
                cluster=config.ecs_cluster_arn,
                desiredStatus="STOPPED",
                nextToken=next_token,
            )
        for task_arn in response.get("taskArns", []):
            if (
                not isinstance(task_arn, str)
                or not task_arn.startswith("arn:")
                or "/" not in task_arn
            ):
                raise RecoveryInvariantError("ECS ListTasks returned an invalid task ARN")
            stopped_candidates.append(task_arn)
        value = response.get("nextToken")
        if value is None:
            break
        if not isinstance(value, str) or not value or value in seen_tokens:
            raise RecoveryInvariantError("ECS ListTasks returned an invalid pagination token")
        seen_tokens.add(value)
        next_token = value

    for offset in range(0, len(stopped_candidates), 100):
        batch = stopped_candidates[offset : offset + 100]
        response = ecs.describe_tasks(cluster=config.ecs_cluster_arn, tasks=batch)
        if response.get("failures"):
            raise RecoveryInvariantError(
                f"ECS could not resolve STOPPED-desired tasks: {response['failures']}"
            )
        tasks = response.get("tasks", [])
        described = {task.get("taskArn") for task in tasks if isinstance(task.get("taskArn"), str)}
        missing = set(batch) - described
        if missing:
            raise RecoveryInvariantError(
                f"ECS omitted {len(missing)} STOPPED-desired task(s) during discovery"
            )
        for task in tasks:
            task_arn = task.get("taskArn")
            if (
                task.get("startedBy") == started_by
                and task.get("lastStatus") != "STOPPED"
                and isinstance(task_arn, str)
            ):
                arns.add(task_arn)
    return tuple(sorted(arns))


def _require_no_live_started_by(
    ecs: ECSClient,
    config: SubmitterConfig,
    started_by: str,
    *,
    settle_seconds: float = 30.0,
) -> None:
    """Require two empty ECS discovery reads across an eventual-consistency window."""
    _require_no_live_started_by_set(
        ecs,
        config,
        (started_by,),
        settle_seconds=settle_seconds,
    )


def _require_no_live_started_by_set(
    ecs: ECSClient,
    config: SubmitterConfig,
    started_by_values: tuple[str, ...],
    *,
    settle_seconds: float = 30.0,
) -> None:
    """Prove several deterministic ECS identities are quiet in one window."""
    if settle_seconds < 0:
        raise ValueError("ECS discovery settle interval must not be negative")
    if not started_by_values:
        return
    for started_by in started_by_values:
        first = _list_tasks_started_by(ecs, config, started_by)
        if first:
            raise RecoveryInvariantError(
                f"ECS launch identity {started_by} still has live task(s): {', '.join(first[:10])}"
            )
    if settle_seconds:
        time.sleep(settle_seconds)
    for started_by in started_by_values:
        second = _list_tasks_started_by(ecs, config, started_by)
        if second:
            raise RecoveryInvariantError(
                f"ECS task appeared for launch identity {started_by}: {', '.join(second[:10])}"
            )


def _reconciliation_inventory_identity(inventory: RecoveryInventory) -> tuple[object, ...]:
    return (
        inventory.input_sha256,
        inventory.force_rescrape,
        inventory.terminal_candidate_journal_schema_version,
        inventory.manifest_completed_at,
        inventory.result_ids,
        inventory.failure_ids,
        inventory.missing_ids,
        inventory.terminal_evidence_sha256,
        inventory.candidate_count,
        inventory.candidate_evidence_sha256,
        inventory.conflict_policy_version,
        inventory.conflict_evidence_sha256,
        inventory.invalid_resolution_count,
    )


def reconcile_recovery_attempt(
    ecs: ECSClient,
    sqs: SQSClient,
    s3: S3Client,
    config: SubmitterConfig,
    run_id: str,
    attempt_id: str,
    *,
    execute: bool = False,
    now: datetime | None = None,
    minimum_attempt_age_seconds: float = 60.0,
    quiet_seconds: float = 30.0,
) -> RecoveryReconciliation:
    """Prove an interrupted attempt is quiescent and optionally return its fence.

    The default is read-only. Execution writes append-only reconciliation
    evidence and CAS-hands only the exact ``recovery:<attempt-id>`` owner back
    to the same run. It never authorizes a different run to use the shared queue.
    """
    if not run_id.strip() or "/" in run_id:
        raise ValueError("run ID must be a non-blank path segment")
    if not attempt_id.strip() or "/" in attempt_id:
        raise ValueError("recovery attempt ID must be a non-blank path segment")
    if minimum_attempt_age_seconds < 0 or quiet_seconds < 0:
        raise ValueError("reconciliation timing intervals must not be negative")
    observed_at = now or datetime.now(UTC)
    if observed_at.tzinfo is None:
        raise ValueError("reconciliation time must be timezone-aware")

    from aws_batch_scraper.lease import (
        read_run_lease,
        reconcile_run_lease_from_recovery,
    )
    from aws_batch_scraper.orchestrate import _ecs_started_by

    plan_created_at = _read_recovery_plan_created_at(
        s3,
        config,
        run_id,
        attempt_id,
    )
    age_seconds = (observed_at - plan_created_at).total_seconds()
    if age_seconds < minimum_attempt_age_seconds:
        raise RecoveryInvariantError(
            f"Recovery attempt is only {age_seconds:.1f}s old; wait until ECS launch "
            "discovery is no longer eventually consistent"
        )
    expected_owner = f"recovery:{attempt_id}"
    first_lease = read_run_lease(s3, config)
    if first_lease.run_id != run_id or first_lease.owner != expected_owner:
        raise RecoveryInvariantError(
            f"Active lease is owned by run={first_lease.run_id}, owner={first_lease.owner}; "
            f"expected run={run_id}, owner={expected_owner}"
        )

    known_task_arns = read_recovery_attempt_task_arns(s3, config, run_id, attempt_id)
    if known_task_arns:
        tasks = _describe_recovery_tasks(ecs, config, known_task_arns)
        live_known = sorted(
            str(task["taskArn"]) for task in tasks if task.get("lastStatus") != "STOPPED"
        )
        if live_known:
            raise RecoveryInvariantError(
                f"Recovery attempt still has live known task(s): {', '.join(live_known[:10])}"
            )

    worker_started_by = _ecs_started_by(
        run_id,
        "worker",
        recovery_attempt_id=attempt_id,
    )
    monitor_started_by = _ecs_started_by(
        run_id,
        "monitor",
        recovery_attempt_id=attempt_id,
    )

    first_live = set(_list_tasks_started_by(ecs, config, worker_started_by)) | set(
        _list_tasks_started_by(ecs, config, monitor_started_by)
    )
    if first_live:
        raise RecoveryInvariantError(
            f"Recovery attempt still has discoverable live task(s): "
            f"{', '.join(sorted(first_live)[:10])}"
        )
    first_queue = read_queue_state(sqs, config)
    if first_queue.in_flight:
        raise RecoveryInvariantError("Recovery queue still has in-flight messages")
    first_inventory = inventory_run(s3, config, run_id)

    if quiet_seconds:
        time.sleep(quiet_seconds)

    second_lease = read_run_lease(s3, config)
    if second_lease != first_lease:
        raise RecoveryInvariantError("Active recovery lease changed during reconciliation")
    second_live = set(_list_tasks_started_by(ecs, config, worker_started_by)) | set(
        _list_tasks_started_by(ecs, config, monitor_started_by)
    )
    if second_live:
        raise RecoveryInvariantError(
            f"Recovery task appeared during the quiet window: {', '.join(sorted(second_live)[:10])}"
        )
    second_queue = read_queue_state(sqs, config)
    if second_queue != first_queue or second_queue.in_flight:
        raise RecoveryInvariantError(
            f"Main queue changed during reconciliation: {first_queue} -> {second_queue}"
        )
    second_inventory = inventory_run(s3, config, run_id)
    if _reconciliation_inventory_identity(second_inventory) != _reconciliation_inventory_identity(
        first_inventory
    ):
        raise RecoveryInvariantError("Run terminal inventory changed during reconciliation")

    reconciliation = RecoveryReconciliation(
        run_id=run_id,
        attempt_id=attempt_id,
        observed_at=observed_at,
        plan_created_at=plan_created_at,
        lease_created_at=first_lease.created_at,
        queue=second_queue,
        terminal_evidence_sha256=second_inventory.terminal_evidence_sha256,
        candidate_evidence_sha256=second_inventory.candidate_evidence_sha256,
        conflict_evidence_sha256=second_inventory.conflict_evidence_sha256,
        missing_ids=second_inventory.missing_ids,
        known_task_arns=known_task_arns,
        worker_started_by=worker_started_by,
        monitor_started_by=monitor_started_by,
    )
    if not execute:
        return reconciliation

    reconciliation_id = make_recovery_attempt_id(observed_at)
    authorization_key = (
        f"{config.s3_scraper_prefix}/runs/{run_id}/recovery-attempts/{attempt_id}/"
        f"reconciliations/{reconciliation_id}-authorized.json"
    )
    _put_append_only_json(
        s3,
        config,
        key=authorization_key,
        value=reconciliation.as_dict(),
    )
    returned_lease = reconcile_run_lease_from_recovery(
        s3,
        config,
        run_id,
        attempt_id,
        expected_created_at=first_lease.created_at,
        now=observed_at,
    )
    completion_key = (
        f"{config.s3_scraper_prefix}/runs/{run_id}/recovery-attempts/{attempt_id}/"
        f"reconciliations/{reconciliation_id}-returned.json"
    )
    _put_append_only_json(
        s3,
        config,
        key=completion_key,
        value={
            "schema_version": _RECOVERY_SCHEMA_VERSION,
            "run_id": run_id,
            "attempt_id": attempt_id,
            "completed_at": observed_at.isoformat(),
            "authorization_key": authorization_key,
            "previous_lease_created_at": first_lease.created_at.isoformat(),
            "returned_lease": returned_lease.model_dump(mode="json"),
            "lease_action": "returned-to-run",
        },
    )
    return reconciliation


def execute_recovery_plan(
    s3: S3Client,
    sqs: SQSClient,
    ecs: ECSClient,
    config: SubmitterConfig,
    plan: RecoveryPlan,
    *,
    worker_count: int | None = None,
    soft_blocked_delay_max: int | None = None,
    monitor_command: list[str] | None = None,
    wait: bool = False,
    poll_interval: int = 30,
) -> list[str]:
    """Execute one already-reviewed plan without ever reseeding completed IDs."""
    if wait and monitor_command is not None:
        raise ValueError("Use either synchronous wait or a recovery monitor command")
    if not wait and monitor_command is None and plan.action is not RecoveryAction.COMPLETE:
        raise ValueError("A recovery launch requires synchronous wait or a monitor command")

    from aws_batch_scraper.lease import (
        claim_run_lease_for_recovery,
        return_run_lease_from_recovery,
    )
    from aws_batch_scraper.orchestrate import (
        WorkerLaunchError,
        _finalize_manifest,
        launch_monitor,
        launch_workers,
        resolve_split_task_definitions,
    )
    from aws_batch_scraper.queue import seed_queue

    # Repeat every volatile preflight immediately before the first write.  The
    # S3 inventory comparison includes conflict evidence and the input CAS.
    verify_plan_is_current(s3, config, plan)
    require_prior_tasks_stopped(ecs, config, plan.prior_task_arns)
    _require_no_live_started_by_set(ecs, config, plan.prior_task_discovery)
    if (current_queue := require_stable_queue_state(sqs, config)) != plan.queue:
        raise RecoveryInvariantError(
            f"Main queue changed after recovery planning: {plan.queue} -> {current_queue}"
        )
    if plan.action is not RecoveryAction.COMPLETE:
        resolve_split_task_definitions(ecs, config)
    write_recovery_plan(s3, config, plan)
    if plan.action is RecoveryAction.COMPLETE:
        from aws_batch_scraper.aggregate import read_run_manifest
        from aws_batch_scraper.lease import finalizing_run_owner, read_run_lease

        manifest = read_run_manifest(s3, config, plan.run_id)
        if manifest.completed_at is not None:
            logger.info(
                f"Run {plan.run_id} is already monitor-complete; no scraper dispatch repeated"
            )
            return []
        active_lease = read_run_lease(s3, config)
        expected_finalizer = finalizing_run_owner(
            plan.run_id,
            active_lease.created_at,
        )
        if active_lease.run_id == plan.run_id and active_lease.owner == expected_finalizer:
            _finalize_manifest(
                s3,
                sqs,
                config,
                plan.run_id,
                plan.created_at,
                terminal_queue_counts=(
                    plan.queue.visible,
                    plan.queue.in_flight,
                    plan.queue.delayed,
                ),
                expected_lease_owner=active_lease.owner,
                expected_lease_created_at=active_lease.created_at,
            )
            return []
        claim_run_lease_for_recovery(
            s3,
            config,
            plan.run_id,
            plan.attempt_id,
        )
        returned_lease = return_run_lease_from_recovery(
            s3,
            config,
            plan.run_id,
            plan.attempt_id,
        )
        _finalize_manifest(
            s3,
            sqs,
            config,
            plan.run_id,
            plan.created_at,
            terminal_queue_counts=(
                plan.queue.visible,
                plan.queue.in_flight,
                plan.queue.delayed,
            ),
            expected_lease_owner=plan.run_id,
            expected_lease_created_at=returned_lease.created_at,
        )
        return []

    claim_run_lease_for_recovery(
        s3,
        config,
        plan.run_id,
        plan.attempt_id,
    )
    launched_task_arns: list[str] = []
    try:
        if plan.action is RecoveryAction.SEED_MISSING:
            missing_items = list(plan.inventory.missing_items)
            if not missing_items or any(
                item.item_id in plan.inventory.completed_ids for item in missing_items
            ):
                raise RecoveryInvariantError(
                    "Recovery seed set is empty or includes an already completed item"
                )
            seeded_count = seed_queue(
                sqs,
                config,
                missing_items,
                plan.run_id,
                force_rescrape=plan.inventory.force_rescrape,
            )
            if seeded_count != len(missing_items):
                raise RuntimeError(
                    f"SQS accepted only {seeded_count}/{len(missing_items)} recovery messages"
                )

        launched_task_arns = launch_workers(
            ecs,
            config,
            plan.run_id,
            worker_count=worker_count,
            force_rescrape=plan.inventory.force_rescrape,
            soft_blocked_delay_max=soft_blocked_delay_max,
            recovery_attempt_id=plan.attempt_id,
        )
        write_recovery_tasks(s3, config, plan, launched_task_arns)
    except WorkerLaunchError as exc:
        # An ambiguous or partial RunTask outcome may already have live tasks;
        # retaining the fenced lease is safer than authorizing another attempt.
        try:
            if exc.launched_task_arns:
                write_recovery_tasks(s3, config, plan, list(exc.launched_task_arns))
            write_recovery_launch_failure(
                s3,
                config,
                plan,
                role="worker",
                detail=str(exc),
                launch_ambiguous=exc.launch_ambiguous,
                confirmed_task_arns=list(exc.launched_task_arns),
            )
        except Exception:
            logger.exception(
                f"Could not persist complete worker launch-failure evidence for {plan.run_id}"
            )
        if exc.launch_ambiguous or exc.launched_task_arns:
            raise
        return_run_lease_from_recovery(
            s3,
            config,
            plan.run_id,
            plan.attempt_id,
        )
        raise
    except Exception as exc:
        # Before a task ARN is confirmed, a failed seed/validation is safely
        # recoverable from the queue's next observed state. Once workers may be
        # live, retain the fenced lease for explicit reconciliation.
        if launched_task_arns:
            try:
                write_recovery_launch_failure(
                    s3,
                    config,
                    plan,
                    role="worker",
                    detail=f"worker task evidence write failed: {exc}",
                    launch_ambiguous=False,
                    confirmed_task_arns=launched_task_arns,
                )
            except Exception:
                logger.exception(
                    f"Could not persist worker evidence-write failure for {plan.run_id}"
                )
            raise
        return_run_lease_from_recovery(
            s3,
            config,
            plan.run_id,
            plan.attempt_id,
        )
        raise

    if wait:
        monitor_recovery_attempt(
            ecs,
            sqs,
            s3,
            config,
            plan.run_id,
            plan.attempt_id,
            poll_interval=poll_interval,
        )
    else:
        if monitor_command is None:  # narrowed by the validation above
            raise RuntimeError("Recovery monitor command is missing")
        monitor_task_arn: str | None = None
        try:
            monitor_task_arn = launch_monitor(
                ecs,
                config,
                plan.run_id,
                monitor_command,
                recovery_attempt_id=plan.attempt_id,
            )
            write_recovery_monitor_task(s3, config, plan, monitor_task_arn)
        except Exception as exc:
            launch_ambiguous = bool(getattr(exc, "launch_ambiguous", monitor_task_arn is None))
            try:
                write_recovery_launch_failure(
                    s3,
                    config,
                    plan,
                    role="monitor",
                    detail=str(exc),
                    launch_ambiguous=launch_ambiguous,
                    confirmed_task_arns=[monitor_task_arn] if monitor_task_arn else None,
                )
            except Exception:
                logger.exception(
                    f"Could not persist monitor launch-failure evidence for {plan.run_id}"
                )
            raise
    return launched_task_arns


def _describe_recovery_tasks(
    ecs: ECSClient,
    config: SubmitterConfig,
    task_arns: tuple[str, ...],
) -> list[TaskTypeDef]:
    response = ecs.describe_tasks(cluster=config.ecs_cluster_arn, tasks=list(task_arns))
    if response.get("failures"):
        raise RecoveryInvariantError(
            f"ECS could not resolve recovery worker tasks: {response['failures']}"
        )
    tasks = list(response.get("tasks", []))
    described = {task.get("taskArn") for task in tasks if isinstance(task.get("taskArn"), str)}
    missing = set(task_arns) - described
    if missing:
        raise RecoveryInvariantError(
            f"ECS omitted {len(missing)} recovery task(s): {', '.join(sorted(missing)[:10])}"
        )
    return tasks


def monitor_recovery_attempt(
    ecs: ECSClient,
    sqs: SQSClient,
    s3: S3Client,
    config: SubmitterConfig,
    run_id: str,
    attempt_id: str,
    *,
    poll_interval: int = 30,
) -> None:
    """Monitor one recovery task set and finalize only after exact coverage."""
    from aws_batch_scraper.dispatch import WorkflowDispatchError
    from aws_batch_scraper.lease import (
        renew_run_lease,
        return_run_lease_from_recovery,
    )
    from aws_batch_scraper.orchestrate import (
        ManifestPublicationDeliveryUnknownError,
        _assert_tasks_succeeded,
        _finalize_manifest,
    )

    if poll_interval < 0:
        raise ValueError("poll interval must not be negative")
    task_arns = read_recovery_task_arns(s3, config, run_id, attempt_id)
    recovery_owner = f"recovery:{attempt_id}"
    monitor_started_at = datetime.now(UTC)

    while True:
        renew_run_lease(
            s3,
            config,
            run_id,
            owner=recovery_owner,
        )
        tasks = _describe_recovery_tasks(ecs, config, task_arns)
        live = [task for task in tasks if task.get("lastStatus") != "STOPPED"]
        logger.info(
            f"Recovery {attempt_id}: {len(live)}/{len(task_arns)} worker task(s) still live"
        )
        if live:
            time.sleep(poll_interval)
            continue

        handed_back = False
        try:
            queue = require_stable_queue_state(sqs, config)
            if queue.total:
                raise RecoveryInvariantError(
                    f"Recovery tasks stopped with a nonempty main queue: {queue}"
                )
            _assert_tasks_succeeded(tasks)
            require_exact_terminal_coverage(s3, config, run_id)
            # The inventory walk can be lengthy. Require a second quiet window
            # before transferring the ownership fence to finalization.
            post_inventory_queue = require_stable_queue_state(sqs, config)
            if post_inventory_queue.total:
                raise RecoveryInvariantError(
                    "Main queue became nonempty during recovery terminal audit: "
                    f"{post_inventory_queue}"
                )
            returned_lease = return_run_lease_from_recovery(
                s3,
                config,
                run_id,
                attempt_id,
            )
            handed_back = True
            _finalize_manifest(
                s3,
                sqs,
                config,
                run_id,
                monitor_started_at,
                terminal_queue_counts=(
                    post_inventory_queue.visible,
                    post_inventory_queue.in_flight,
                    post_inventory_queue.delayed,
                ),
                expected_lease_owner=run_id,
                expected_lease_created_at=returned_lease.created_at,
            )
            return
        except (
            WorkflowDispatchError,
            ManifestPublicationDeliveryUnknownError,
        ):
            # The manifest or GitHub dispatch may already be committed. Retain
            # the finalizer so an operator can correlate without retrying.
            raise
        except Exception:
            if not handed_back:
                try:
                    return_run_lease_from_recovery(
                        s3,
                        config,
                        run_id,
                        attempt_id,
                    )
                except Exception:
                    logger.exception(
                        f"Could not return failed recovery lease for {run_id}; retaining fence"
                    )
            raise


__all__ = [
    "QueueState",
    "RecoveryAction",
    "RecoveryInventory",
    "RecoveryInvariantError",
    "RecoveryPlan",
    "build_recovery_plan",
    "execute_recovery_plan",
    "inventory_run",
    "make_recovery_attempt_id",
    "monitor_recovery_attempt",
    "read_prior_task_arns",
    "read_queue_state",
    "read_recovery_task_arns",
    "require_exact_terminal_coverage",
    "require_prior_tasks_stopped",
    "require_stable_queue_state",
    "verify_plan_is_current",
    "write_recovery_plan",
    "write_recovery_monitor_task",
    "write_recovery_launch_failure",
    "write_recovery_tasks",
]
