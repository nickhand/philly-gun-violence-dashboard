"""S3-backed lease preventing overlapping scraper runs."""

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from botocore.exceptions import ClientError
from loguru import logger
from mypy_boto3_s3.client import S3Client
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from aws_batch_scraper.config import WorkerConfig

_DEFAULT_LEASE_TTL = timedelta(hours=24)
_CAS_ATTEMPTS = 3


class RunLease(BaseModel):
    """Ownership record stored at the scraper's stable active-run key."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    run_id: str
    owner: str
    created_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def _valid_window(self) -> "RunLease":
        if not self.run_id.strip() or not self.owner.strip():
            raise ValueError("run lease identifiers must not be blank")
        if self.created_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("run lease timestamps must be timezone-aware")
        if self.expires_at <= self.created_at:
            raise ValueError("run lease must expire after it is created")
        return self


class RunTerminalRecord(RunLease):
    """Typed terminal evidence for one exact lease owner and generation."""

    terminal_status: Literal["success", "failure"]
    detail: str | None = None
    release_requested_at: datetime
    released_at: datetime | None = None

    @model_validator(mode="after")
    def _valid_release(self) -> "RunTerminalRecord":
        if self.release_requested_at.tzinfo is None:
            raise ValueError("terminal release timestamp must be timezone-aware")
        if self.release_requested_at < self.created_at:
            raise ValueError("terminal release cannot precede lease creation")
        if self.released_at is not None:
            if self.released_at.tzinfo is None:
                raise ValueError("terminal released timestamp must be timezone-aware")
            if self.released_at != self.release_requested_at:
                raise ValueError("terminal release timestamps must match")
        return self


class RunLeaseConflict(RuntimeError):
    """Raised when another owner holds the active run lease."""


def _lease_key(config: WorkerConfig) -> str:
    return f"{config.s3_scraper_prefix}/active-run.json"


def _terminal_key(config: WorkerConfig, run_id: str) -> str:
    return f"{config.s3_scraper_prefix}/runs/{run_id}/lease-terminal.json"


def _error_code(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code", ""))


def _is_precondition_failed(exc: ClientError) -> bool:
    return _error_code(exc) in {"412", "PreconditionFailed", "ConditionalRequestConflict"}


def _is_not_found(exc: ClientError) -> bool:
    return _error_code(exc) in {"404", "NoSuchKey", "NotFound"}


def _read_lease(
    s3: S3Client,
    config: WorkerConfig,
) -> tuple[RunLease, str]:
    response = s3.get_object(Bucket=config.s3_bucket, Key=_lease_key(config))
    body = response["Body"].read()
    etag = response.get("ETag")
    if not isinstance(etag, str) or not etag:
        raise RuntimeError("Active run lease is missing its S3 ETag")
    return RunLease.model_validate_json(body), etag


def _read_terminal_record(
    s3: S3Client,
    config: WorkerConfig,
    run_id: str,
) -> RunTerminalRecord:
    response = s3.get_object(Bucket=config.s3_bucket, Key=_terminal_key(config, run_id))
    return RunTerminalRecord.model_validate_json(response["Body"].read())


def _read_terminal_state(
    s3: S3Client,
    config: WorkerConfig,
    run_id: str,
) -> tuple[RunTerminalRecord | None, str | None]:
    """Read a terminal record plus ETag, preserving invalid state for CAS repair."""
    try:
        response = s3.get_object(Bucket=config.s3_bucket, Key=_terminal_key(config, run_id))
    except ClientError as exc:
        if _is_not_found(exc):
            return None, None
        raise
    etag = response.get("ETag")
    if not isinstance(etag, str) or not etag:
        raise RuntimeError(f"Terminal record for run {run_id} is missing its S3 ETag")
    try:
        terminal = RunTerminalRecord.model_validate_json(response["Body"].read())
    except (ValidationError, ValueError):
        terminal = None
    return terminal, etag


def _put_lease(
    s3: S3Client,
    config: WorkerConfig,
    lease: RunLease,
    *,
    if_none_match: str | None = None,
    if_match: str | None = None,
) -> None:
    request: dict[str, Any] = {
        "Bucket": config.s3_bucket,
        "Key": _lease_key(config),
        "Body": lease.model_dump_json(indent=2).encode(),
        "ContentType": "application/json",
    }
    if if_none_match is not None:
        request["IfNoneMatch"] = if_none_match
    if if_match is not None:
        request["IfMatch"] = if_match
    s3.put_object(**request)


def _put_terminal_record(
    s3: S3Client,
    config: WorkerConfig,
    terminal: RunTerminalRecord,
    *,
    if_none_match: str | None = None,
    if_match: str | None = None,
) -> None:
    request: dict[str, Any] = {
        "Bucket": config.s3_bucket,
        "Key": _terminal_key(config, terminal.run_id),
        "Body": terminal.model_dump_json(indent=2).encode(),
        "ContentType": "application/json",
    }
    if if_none_match is not None:
        request["IfNoneMatch"] = if_none_match
    if if_match is not None:
        request["IfMatch"] = if_match
    s3.put_object(**request)


def _is_completed_release_for_lease(
    lease: RunLease,
    terminal: RunTerminalRecord,
) -> bool:
    expected_expiry = max(
        terminal.release_requested_at,
        terminal.created_at + timedelta(microseconds=1),
    )
    return (
        terminal.run_id == lease.run_id
        and terminal.owner == lease.owner
        and terminal.created_at == lease.created_at
        and lease.expires_at == expected_expiry
        and terminal.released_at is not None
    )


def _require_completed_terminal_release(
    s3: S3Client,
    config: WorkerConfig,
    lease: RunLease,
    *,
    action: str,
) -> RunTerminalRecord:
    """Prove that one exact lease generation completed its release protocol."""
    try:
        terminal = _read_terminal_record(s3, config, lease.run_id)
    except ClientError as exc:
        if _is_not_found(exc):
            raise RunLeaseConflict(
                f"Cannot {action}; expired lease for run {lease.run_id} has no completed "
                "terminal evidence. Reconcile its ECS tasks and all queue states, then "
                "explicitly release that exact lease owner before retrying."
            ) from exc
        raise
    except (ValidationError, ValueError) as exc:
        raise RunLeaseConflict(
            f"Cannot {action}; expired lease for run {lease.run_id} has invalid terminal "
            "evidence. Reconcile its ECS tasks and all queue states before manual recovery."
        ) from exc

    same_generation = (
        terminal.run_id == lease.run_id
        and terminal.owner == lease.owner
        and terminal.created_at == lease.created_at
    )
    if not same_generation:
        raise RunLeaseConflict(
            f"Cannot {action}; terminal evidence does not match the expired lease for "
            f"run={lease.run_id}, owner={lease.owner}. Reconcile its ECS tasks and all "
            "queue states before manual recovery."
        )
    if not _is_completed_release_for_lease(lease, terminal):
        raise RunLeaseConflict(
            f"Cannot {action}; release of expired lease for run {lease.run_id} did not "
            "complete. Reconcile its ECS tasks and all queue states before manual recovery."
        )
    return terminal


def acquire_run_lease(
    s3: S3Client,
    config: WorkerConfig,
    run_id: str,
    *,
    owner: str | None = None,
    now: datetime | None = None,
    ttl: timedelta = _DEFAULT_LEASE_TTL,
) -> RunLease:
    """Atomically acquire the lease after its prior owner completed release.

    Time-to-live is a liveness alarm, not proof that ECS tasks stopped or that the
    shared queues were reconciled. An expired object is therefore replaceable only
    when typed terminal evidence matches the exact owner and lease generation.
    """
    acquired_at = now or datetime.now(UTC)
    if acquired_at.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if ttl <= timedelta(0):
        raise ValueError("ttl must be positive")
    lease = RunLease(
        run_id=run_id,
        owner=owner or run_id,
        created_at=acquired_at,
        expires_at=acquired_at + ttl,
    )

    for _ in range(_CAS_ATTEMPTS):
        try:
            _put_lease(s3, config, lease, if_none_match="*")
            logger.info(f"Acquired active-run lease for {run_id} until {lease.expires_at}")
            return lease
        except ClientError as exc:
            if not _is_precondition_failed(exc):
                raise

        try:
            current, etag = _read_lease(s3, config)
        except ClientError as exc:
            if _is_not_found(exc):
                continue
            raise

        if current.expires_at > acquired_at:
            raise RunLeaseConflict(
                f"Run {current.run_id} owns the active-run lease until "
                f"{current.expires_at.isoformat()}"
            )

        _require_completed_terminal_release(
            s3,
            config,
            current,
            action=f"acquire run {run_id}",
        )

        try:
            _put_lease(s3, config, lease, if_match=etag)
            logger.info(
                f"Replaced terminally released active-run lease from {current.run_id} with {run_id}"
            )
            return lease
        except ClientError as exc:
            if _is_precondition_failed(exc):
                continue
            raise

    raise RunLeaseConflict("Active-run lease changed repeatedly during acquisition")


def renew_run_lease(
    s3: S3Client,
    config: WorkerConfig,
    run_id: str,
    *,
    owner: str | None = None,
    now: datetime | None = None,
    ttl: timedelta = _DEFAULT_LEASE_TTL,
) -> RunLease:
    """Extend a lease only when the caller still owns the exact S3 object."""
    renewed_at = now or datetime.now(UTC)
    if renewed_at.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if ttl <= timedelta(0):
        raise ValueError("ttl must be positive")
    current, etag = _read_lease(s3, config)
    expected_owner = owner or run_id
    if current.run_id != run_id or current.owner != expected_owner:
        raise RunLeaseConflict(
            f"Cannot renew lease owned by run={current.run_id}, owner={current.owner}"
        )
    if current.expires_at <= renewed_at:
        raise RunLeaseConflict(
            f"Cannot renew expired lease for run {run_id}; it expired at "
            f"{current.expires_at.isoformat()}"
        )
    renewed = current.model_copy(update={"expires_at": renewed_at + ttl})
    try:
        _put_lease(s3, config, renewed, if_match=etag)
    except ClientError as exc:
        if _is_precondition_failed(exc):
            raise RunLeaseConflict("Active-run lease changed during renewal") from exc
        raise
    return renewed


def claim_run_lease(
    s3: S3Client,
    config: WorkerConfig,
    run_id: str,
    claimant: str,
    *,
    current_owner: str | None = None,
    now: datetime | None = None,
    ttl: timedelta = _DEFAULT_LEASE_TTL,
) -> RunLease:
    """Atomically hand an active run from its coordinator to one claimant.

    Unlike renewal, this changes the owner. A second processor using the same
    run ID therefore cannot prove exclusive ownership after the first claim.
    Expired-owner recovery is intentionally handled by
    :func:`claim_run_lease_for_processing`, where terminal evidence is checked.
    """
    claimed_at = now or datetime.now(UTC)
    if claimed_at.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if ttl <= timedelta(0):
        raise ValueError("ttl must be positive")
    if not claimant.strip():
        raise ValueError("claimant must not be blank")

    expected_owner = current_owner or run_id
    if claimant == expected_owner:
        raise ValueError("claimant must differ from the current lease owner")
    current, etag = _read_lease(s3, config)
    if current.run_id != run_id or current.owner != expected_owner:
        raise RunLeaseConflict(
            f"Cannot claim lease owned by run={current.run_id}, owner={current.owner}"
        )
    if current.expires_at <= claimed_at:
        raise RunLeaseConflict(
            f"Cannot claim expired lease for run {run_id}; it expired at "
            f"{current.expires_at.isoformat()}"
        )

    claimed = current.model_copy(update={"owner": claimant, "expires_at": claimed_at + ttl})
    try:
        _put_lease(s3, config, claimed, if_match=etag)
    except ClientError as exc:
        if _is_precondition_failed(exc):
            raise RunLeaseConflict("Active-run lease changed during claim") from exc
        raise
    logger.info(f"Transferred active-run lease for {run_id} to {claimant}")
    return claimed


def claim_run_lease_for_processing(
    s3: S3Client,
    config: WorkerConfig,
    run_id: str,
    claimant: str,
    *,
    now: datetime | None = None,
    ttl: timedelta = _DEFAULT_LEASE_TTL,
) -> RunLease:
    """Claim a completed run for processing, including a proven failed retry.

    A completed coordinator lease may be claimed even after expiry because the
    caller has already verified the completed-run manifest. An expired lease
    owned by a prior processor is recoverable only when its typed terminal
    record proves that the same lease generation and owner ended in failure.
    """
    claimed_at = now or datetime.now(UTC)
    if claimed_at.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if ttl <= timedelta(0):
        raise ValueError("ttl must be positive")
    if not claimant.startswith("process:") or not claimant.removeprefix("process:").strip():
        raise ValueError("processing claimant must use a non-blank process: identifier")

    current, etag = _read_lease(s3, config)
    if current.run_id != run_id:
        raise RunLeaseConflict(
            f"Cannot claim lease owned by run={current.run_id}, owner={current.owner}"
        )
    if claimant == current.owner:
        raise ValueError("claimant must differ from the current lease owner")

    if current.owner != run_id:
        if not current.owner.startswith("process:"):
            raise RunLeaseConflict(
                f"Cannot claim lease owned by run={current.run_id}, owner={current.owner}"
            )
        if current.expires_at > claimed_at:
            raise RunLeaseConflict(
                f"Cannot retry active processing lease owned by {current.owner} until "
                f"{current.expires_at.isoformat()}"
            )
        terminal = _require_completed_terminal_release(
            s3,
            config,
            current,
            action=f"retry run {run_id}",
        )
        if terminal.terminal_status != "failure":
            raise RunLeaseConflict(f"Cannot retry successfully processed run {run_id}")

    claimed = current.model_copy(update={"owner": claimant, "expires_at": claimed_at + ttl})
    try:
        _put_lease(s3, config, claimed, if_match=etag)
    except ClientError as exc:
        if _is_precondition_failed(exc):
            raise RunLeaseConflict("Active-run lease changed during processing claim") from exc
        raise
    logger.info(f"Transferred active-run lease for {run_id} to {claimant}")
    return claimed


def release_run_lease(
    s3: S3Client,
    config: WorkerConfig,
    run_id: str,
    *,
    owner: str | None = None,
    terminal_status: Literal["success", "failure"],
    detail: str | None = None,
    now: datetime | None = None,
) -> bool:
    """Release an owned lease and retain a durable run-level terminal record."""
    try:
        current, etag = _read_lease(s3, config)
    except ClientError as exc:
        if _is_not_found(exc):
            return False
        raise

    expected_owner = owner or run_id
    if current.run_id != run_id or current.owner != expected_owner:
        logger.warning(
            "Refusing to release active-run lease owned by run={}, owner={}",
            current.run_id,
            current.owner,
        )
        return False

    release_requested_at = now or datetime.now(UTC)
    if release_requested_at.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    existing_terminal, terminal_etag = _read_terminal_state(s3, config, run_id)
    if existing_terminal is not None and _is_completed_release_for_lease(
        current,
        existing_terminal,
    ):
        if (
            existing_terminal.terminal_status != terminal_status
            or existing_terminal.detail != detail
        ):
            raise RunLeaseConflict(
                f"Lease for run {run_id} was already released with "
                f"status={existing_terminal.terminal_status}; refusing to replace its "
                "terminal evidence"
            )
        logger.info(f"Lease for run {run_id} was already released with status={terminal_status}")
        return True

    expires_at = max(
        release_requested_at,
        current.created_at + timedelta(microseconds=1),
    )
    released_lease = current.model_copy(update={"expires_at": expires_at})
    released_record = RunTerminalRecord(
        **current.model_dump(),
        terminal_status=terminal_status,
        detail=detail,
        release_requested_at=release_requested_at,
        released_at=release_requested_at,
    )

    # Win ownership of the release first. A concurrent stale releaser that loses
    # this CAS must never touch terminal evidence. The terminal write is then
    # conditional on the exact state observed before the active-lease CAS.
    try:
        _put_lease(s3, config, released_lease, if_match=etag)
    except ClientError as exc:
        if _is_precondition_failed(exc):
            raise RunLeaseConflict("Active-run lease changed during release") from exc
        raise

    try:
        if terminal_etag is None:
            _put_terminal_record(
                s3,
                config,
                released_record,
                if_none_match="*",
            )
        else:
            _put_terminal_record(
                s3,
                config,
                released_record,
                if_match=terminal_etag,
            )
    except ClientError as exc:
        if _is_precondition_failed(exc):
            raise RunLeaseConflict(
                f"Terminal evidence changed while releasing run {run_id}; the lease "
                "remains fail-closed for explicit reconciliation"
            ) from exc
        raise
    logger.info(f"Released active-run lease for {run_id} with status={terminal_status}")
    return True
