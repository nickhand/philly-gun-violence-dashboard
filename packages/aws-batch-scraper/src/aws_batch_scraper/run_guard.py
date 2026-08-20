"""Read-only policy guard for suppressing duplicate full scraper runs."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from botocore.exceptions import ClientError
from loguru import logger
from mypy_boto3_s3.client import S3Client
from pydantic import ValidationError

from aws_batch_scraper.aggregate import read_run_manifest
from aws_batch_scraper.config import WorkerConfig
from aws_batch_scraper.lease import RunLease, RunTerminalRecord

_ACTIVE_GUARD_ATTEMPTS = 3


@dataclass(frozen=True)
class FullRunSuppression:
    """Evidence that a new full run should not be submitted."""

    run_id: str
    reason: Literal["active", "recent-success"]
    reference_at: datetime
    prior_candidate_count: int
    current_candidate_count: int

    @property
    def candidate_count_drift(self) -> int:
        """Return the current candidate-count change since the suppressed run."""
        return self.current_candidate_count - self.prior_candidate_count


def _error_code(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code", ""))


def _is_not_found(exc: ClientError) -> bool:
    return _error_code(exc) in {"404", "NoSuchKey", "NotFound"}


def _active_lease_key(config: WorkerConfig) -> str:
    return f"{config.s3_scraper_prefix}/active-run.json"


def _terminal_key(config: WorkerConfig, run_id: str) -> str:
    return f"{config.s3_scraper_prefix}/runs/{run_id}/lease-terminal.json"


def _read_active_lease(s3: S3Client, config: WorkerConfig) -> RunLease | None:
    try:
        response = s3.get_object(Bucket=config.s3_bucket, Key=_active_lease_key(config))
    except ClientError as exc:
        if _is_not_found(exc):
            return None
        raise
    return RunLease.model_validate_json(response["Body"].read())


def _read_terminal(
    s3: S3Client,
    config: WorkerConfig,
    run_id: str,
) -> RunTerminalRecord:
    response = s3.get_object(Bucket=config.s3_bucket, Key=_terminal_key(config, run_id))
    terminal = RunTerminalRecord.model_validate_json(response["Body"].read())
    if terminal.run_id != run_id:
        raise ValueError(
            f"Terminal record identity {terminal.run_id!r} does not match path run {run_id!r}"
        )
    return terminal


def _manifest_is_legacy_untyped(
    s3: S3Client,
    config: WorkerConfig,
    run_id: str,
) -> bool:
    """Return whether a manifest predates all typed selection provenance."""
    key = f"{config.s3_scraper_prefix}/runs/{run_id}/manifest.json"
    response = s3.get_object(Bucket=config.s3_bucket, Key=key)
    try:
        decoded: object = json.loads(response["Body"].read())
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return False
    return isinstance(decoded, dict) and not any(
        field in decoded for field in ("selection_mode", "candidate_count")
    )


def _suppression(
    *,
    run_id: str,
    reason: Literal["active", "recent-success"],
    reference_at: datetime,
    prior_candidate_count: int,
    current_candidate_count: int,
) -> FullRunSuppression:
    suppression = FullRunSuppression(
        run_id=run_id,
        reason=reason,
        reference_at=reference_at,
        prior_candidate_count=prior_candidate_count,
        current_candidate_count=current_candidate_count,
    )
    if suppression.candidate_count_drift:
        logger.warning(
            "Suppressing duplicate full run after candidate-count drift: "
            "run={}, previous={}, current={}, drift={:+d}",
            run_id,
            prior_candidate_count,
            current_candidate_count,
            suppression.candidate_count_drift,
        )
    return suppression


def _active_full_run(
    s3: S3Client,
    config: WorkerConfig,
    *,
    current_candidate_count: int,
    now: datetime,
) -> FullRunSuppression | None:
    """Return stable evidence for an active full run, retrying lease renewal races."""
    for _ in range(_ACTIVE_GUARD_ATTEMPTS):
        before = _read_active_lease(s3, config)
        if before is None or before.expires_at <= now:
            return None

        try:
            manifest = read_run_manifest(s3, config, before.run_id)
        except ClientError as exc:
            # A submitter writes the lease immediately before its manifest. Missing
            # provenance in that narrow window is not evidence that the active run
            # is full, so leave the overlap decision to the mandatory lease CAS.
            if _is_not_found(exc):
                return None
            raise
        except ValueError:
            # Legacy active runs have no typed selection provenance. They remain
            # protected by the lease but cannot cleanly suppress a full-mode run.
            return None

        after = _read_active_lease(s3, config)
        if after != before:
            continue
        if manifest.selection_mode != "full":
            return None
        return _suppression(
            run_id=before.run_id,
            reason="active",
            reference_at=before.created_at,
            prior_candidate_count=manifest.candidate_count,
            current_candidate_count=current_candidate_count,
        )

    raise RuntimeError("Active run lease changed repeatedly during full-run deduplication")


def _run_ids(s3: S3Client, config: WorkerConfig) -> list[str]:
    """List run directories without enumerating their per-item result objects."""
    prefix = f"{config.s3_scraper_prefix}/runs/"
    paginator = s3.get_paginator("list_objects_v2")
    run_ids: list[str] = []
    for page in paginator.paginate(
        Bucket=config.s3_bucket,
        Prefix=prefix,
        Delimiter="/",
    ):
        for common_prefix in page.get("CommonPrefixes", []):
            value = common_prefix.get("Prefix")
            if not isinstance(value, str) or not value.startswith(prefix):
                continue
            relative = value.removeprefix(prefix).rstrip("/")
            if relative and "/" not in relative:
                run_ids.append(relative)
    return run_ids


def _recent_successful_full_run(
    s3: S3Client,
    config: WorkerConfig,
    *,
    current_candidate_count: int,
    now: datetime,
    minimum_interval: timedelta,
) -> FullRunSuppression | None:
    threshold = now - minimum_interval
    eligible: list[tuple[datetime, str, int]] = []
    for run_id in _run_ids(s3, config):
        try:
            terminal = _read_terminal(s3, config, run_id)
        except ClientError as exc:
            if _is_not_found(exc):
                continue
            raise
        except (ValidationError, ValueError) as exc:
            # Historical terminal records may predate the typed full/sample
            # provenance contract. They cannot authorize suppression.
            logger.warning("Ignoring invalid terminal record for run {}: {}", run_id, exc)
            continue

        released_at = terminal.released_at
        if (
            terminal.terminal_status != "success"
            or released_at is None
            or not terminal.owner.startswith("process:")
        ):
            continue
        if released_at > now:
            raise ValueError(f"Terminal success for run {run_id} is future-dated")
        if released_at < threshold:
            continue

        try:
            manifest = read_run_manifest(s3, config, run_id, require_completed=True)
        except ValueError as exc:
            # Old manifests did not bind selection mode or candidate count. A
            # legacy/sample migration run must never suppress the required full run.
            if _manifest_is_legacy_untyped(s3, config, run_id):
                logger.warning("Ignoring untyped run manifest for run {}: {}", run_id, exc)
                continue
            raise
        if manifest.selection_mode != "full":
            continue
        if manifest.completed_at is None or manifest.completed_at > released_at:
            raise ValueError(f"Successful full run {run_id} has inconsistent completion timestamps")
        eligible.append((released_at, run_id, manifest.candidate_count))

    if not eligible:
        return None
    released_at, run_id, prior_candidate_count = max(eligible)
    return _suppression(
        run_id=run_id,
        reason="recent-success",
        reference_at=released_at,
        prior_candidate_count=prior_candidate_count,
        current_candidate_count=current_candidate_count,
    )


def find_full_run_suppression(
    s3: S3Client,
    config: WorkerConfig,
    *,
    current_candidate_count: int,
    minimum_interval: timedelta,
    now: datetime | None = None,
) -> FullRunSuppression | None:
    """Find durable evidence that a full submission would be a duplicate.

    An active run suppresses only when its immutable manifest identifies it as
    full. A completed run suppresses only after the processing owner wrote typed
    terminal success evidence. Candidate-count drift is reported but deliberately
    does not launch a second complete scrape inside the configured interval.
    """
    checked_at = now or datetime.now(UTC)
    if checked_at.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if current_candidate_count < 1:
        raise ValueError("current_candidate_count must be positive")
    if minimum_interval <= timedelta(0):
        raise ValueError("minimum_interval must be positive")

    active = _active_full_run(
        s3,
        config,
        current_candidate_count=current_candidate_count,
        now=checked_at,
    )
    if active is not None:
        return active
    return _recent_successful_full_run(
        s3,
        config,
        current_candidate_count=current_candidate_count,
        now=checked_at,
        minimum_interval=minimum_interval,
    )
