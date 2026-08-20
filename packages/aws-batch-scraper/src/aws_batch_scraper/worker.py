"""Generic SQS worker: long-poll the queue and scrape one item per message."""

import base64
import contextlib
import hashlib
import json
import random
import signal
import socket
import threading
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from types import FrameType
from typing import Literal

from botocore.exceptions import ClientError
from loguru import logger
from mypy_boto3_s3.client import S3Client
from mypy_boto3_sqs.client import SQSClient
from mypy_boto3_sqs.type_defs import MessageTypeDef

from aws_batch_scraper.aws import make_boto3_session
from aws_batch_scraper.config import WorkerConfig
from aws_batch_scraper.result_semantics import (
    SEMANTIC_OBSERVATION_FIELDS,
    semantic_observation,
)
from aws_batch_scraper.strict_json import decode_strict_json_object
from aws_batch_scraper.terminal_journal import (
    CandidateJournalError,
    TerminalCandidate,
    claim_terminal_decision,
    write_terminal_candidate,
    write_terminal_decision_conflict,
    write_terminal_disposition,
)
from aws_batch_scraper.types import (
    FailureArtifact,
    Scraper,
    ScrapeResult,
    ScrapeStatus,
    WorkerStats,
    WorkMessage,
)

# Hard cap on a single scrape attempt. Fires SIGALRM if the scraper deadlocks
# at the subprocess/browser level.
_SCRAPE_TIMEOUT_S = 300
_MESSAGE_VISIBILITY_TIMEOUT_S = _SCRAPE_TIMEOUT_S + 120
_MAX_MESSAGE_NESTING = 100

_CONCLUSIVE_STATUSES = frozenset({ScrapeStatus.SUCCESS, ScrapeStatus.NO_RESULTS})
# Only fields that can change the meaning or trustworthiness of a conclusive
# scrape belong here.  Attempt telemetry (``extra``, timing, and retry counts)
# is intentionally excluded: Standard SQS can redeliver a message, and a second
# browser attempt need not produce byte-identical diagnostics to prove the same
# court-search conclusion.
_SQS_DELIVERY_ATTRIBUTES = frozenset(
    {
        "ApproximateFirstReceiveTimestamp",
        "ApproximateReceiveCount",
        "SenderId",
        "SentTimestamp",
        "SequenceNumber",
    }
)


class ResultPublicationConflict(RuntimeError):
    """Raised after durable evidence proves two run results disagree."""


class FailurePublicationConflict(RuntimeError):
    """Raised after durable evidence proves two permanent failures disagree."""


def _sigalrm_handler(signum: int, frame: FrameType | None) -> None:
    """Raise TimeoutError when SIGALRM fires so blocking operations unwind."""
    raise TimeoutError(f"scrape exceeded {_SCRAPE_TIMEOUT_S}s")


def _result_exists(s3: S3Client, bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] in {"404", "NoSuchKey"}:
            return False
        raise


def _proves_object_already_exists(exc: ClientError) -> bool:
    code = str(exc.response.get("Error", {}).get("Code", ""))
    return code in {"412", "PreconditionFailed"}


def _observation(result: ScrapeResult) -> dict[str, object]:
    """Return the explicit semantic projection used for duplicate comparison."""
    return semantic_observation(result)


def _sqs_delivery_metadata(message: MessageTypeDef) -> dict[str, object]:
    """Return a non-secret allowlist of delivery evidence for conflict records.

    Receipt handles are capabilities and are deliberately never persisted.  The
    message body is represented only by its digest because the validated work
    identity is already present in the result-conflict record.
    """
    metadata: dict[str, object] = {}
    for source, target in (
        ("MessageId", "message_id"),
        ("MD5OfBody", "md5_of_body"),
    ):
        value = message.get(source)
        if isinstance(value, str) and value:
            metadata[target] = value

    body = message.get("Body")
    if isinstance(body, str):
        metadata["body_sha256"] = hashlib.sha256(body.encode()).hexdigest()

    attributes = message.get("Attributes")
    if isinstance(attributes, dict):
        allowed_attributes = {
            key: value
            for key, value in sorted(attributes.items())
            if key in _SQS_DELIVERY_ATTRIBUTES and isinstance(value, str)
        }
        if allowed_attributes:
            metadata["system_attributes"] = allowed_attributes
    return metadata


def _write_result_conflict(
    s3: S3Client,
    config: WorkerConfig,
    *,
    item_id: str,
    run_id: str,
    existing_body: bytes,
    candidate_body: bytes,
    candidate: ScrapeResult,
    existing: ScrapeResult | None,
    reason: str,
    delivery_metadata: dict[str, object] | None,
) -> str:
    """Persist fail-closed evidence before a conflicting message is terminalized."""
    existing_observation = _observation(existing) if existing is not None else None
    candidate_observation = _observation(candidate)
    differing_fields = (
        sorted(
            field
            for field in SEMANTIC_OBSERVATION_FIELDS
            if existing_observation is None
            or existing_observation.get(field) != candidate_observation.get(field)
        )
        if existing_observation is not None
        else ["existing_result_invalid"]
    )
    if existing is not None:
        if existing.item_id != item_id:
            differing_fields.append("item_id")
        if existing.run_id != run_id:
            differing_fields.append("run_id")
        differing_fields.sort()
    existing_sha256 = hashlib.sha256(existing_body).hexdigest()
    candidate_sha256 = hashlib.sha256(candidate_body).hexdigest()
    record = {
        "schema_version": 2,
        "terminal_status": "result-conflict",
        "run_id": run_id,
        "item_id": item_id,
        "detected_at": datetime.now(UTC).isoformat(),
        "reason": reason,
        "existing_sha256": existing_sha256,
        "candidate_sha256": candidate_sha256,
        "existing_status": existing.status.value if existing is not None else None,
        "candidate_status": candidate.status.value,
        "differing_fields": differing_fields,
        "canonical_result_key": (
            f"{config.s3_scraper_prefix}/runs/{run_id}/results/{item_id}.json"
        ),
        "existing_evidence": {
            "body_sha256": existing_sha256,
            "semantic_observation": existing_observation,
            "result": existing.model_dump(mode="json") if existing is not None else None,
        },
        "candidate_evidence": {
            "body_sha256": candidate_sha256,
            "body_base64": base64.b64encode(candidate_body).decode("ascii"),
            "semantic_observation": candidate_observation,
            "result": candidate.model_dump(mode="json"),
        },
        "sqs_delivery": delivery_metadata or {},
    }
    # Candidate-addressed keys preserve every distinct observation rather than
    # letting a later disagreement disappear behind one marker per item.
    key = (
        f"{config.s3_scraper_prefix}/runs/{run_id}/result-conflicts/"
        f"v2/{item_id}/{candidate_sha256}.json"
    )
    try:
        s3.put_object(
            Bucket=config.s3_bucket,
            Key=key,
            Body=json.dumps(record, indent=2, sort_keys=True, allow_nan=False).encode(),
            ContentType="application/json",
            IfNoneMatch="*",
        )
    except ClientError as exc:
        # A 409 conditional-request conflict can occur while an object is being
        # deleted and does not prove this terminal evidence exists durably.
        if not _proves_object_already_exists(exc):
            raise
    return key


def _write_result(
    s3: S3Client,
    config: WorkerConfig,
    item_id: str,
    run_id: str,
    result: ScrapeResult,
    result_key: str,
    *,
    delivery_metadata: dict[str, object] | None = None,
    _terminal_candidate: TerminalCandidate | None = None,
) -> Literal["created", "duplicate"]:
    """Publish one exact-run observation with first-writer-wins semantics."""
    if result.status not in _CONCLUSIVE_STATUSES:
        raise ValueError(f"Cannot publish inconclusive result status {result.status.value}")
    if result.is_soft_blocked or result.is_network_error:
        raise ValueError("Cannot publish a conclusive result that still carries a retry hint")
    run_result_key = f"{config.s3_scraper_prefix}/runs/{run_id}/results/{item_id}.json"
    if _terminal_candidate is None:
        result.item_id = item_id
        result.scraped_at = datetime.now(UTC)
        result.run_id = run_id
        body = result.model_dump_json().encode()
        candidate = write_terminal_candidate(
            s3,
            config,
            run_id=run_id,
            item_id=item_id,
            kind="result",
            candidate_body=body,
            result=result,
            delivery_metadata=delivery_metadata,
        )
    else:
        candidate = _terminal_candidate
        if (
            candidate.run_id != run_id
            or candidate.item_id != item_id
            or candidate.kind != "result"
            or candidate.result != result
        ):
            raise CandidateJournalError("Result replay candidate identity is invalid")
        body = candidate.candidate_body
    decision = claim_terminal_decision(s3, config, candidate=candidate)
    if decision.candidate.candidate_sha256 != candidate.candidate_sha256:
        if decision.kind == "result":
            _write_result(
                s3,
                config,
                item_id,
                run_id,
                decision.candidate.result,
                result_key,
                delivery_metadata=None,
                _terminal_candidate=decision.candidate,
            )
        else:
            _write_failure(
                s3,
                config,
                run_id,
                item_id,
                decision.candidate.result,
                delivery_metadata=None,
                _terminal_candidate=decision.candidate,
            )
            conflict = write_terminal_decision_conflict(
                s3,
                config,
                decision=decision,
                candidate=candidate,
            )
            if delivery_metadata is not None:
                write_terminal_disposition(
                    s3,
                    config,
                    run_id=run_id,
                    item_id=item_id,
                    delivery_metadata=delivery_metadata,
                    candidate=candidate,
                    canonical_key=decision.canonical_key,
                    canonical_body=decision.candidate.candidate_body,
                    canonical_result=decision.candidate.result,
                    outcome="conflict",
                    conflict_evidence_key=conflict.key,
                )
            raise ResultPublicationConflict(
                f"Terminal decision for run={run_id}, item={item_id} chose a "
                "permanent failure; durable cross-kind evidence was recorded"
            ) from None
    canonical_body = body
    canonical_result: ScrapeResult | None = result
    outcome: Literal["created", "duplicate"] = "created"
    try:
        s3.put_object(
            Bucket=config.s3_bucket,
            Key=run_result_key,
            Body=body,
            ContentType="application/json",
            IfNoneMatch="*",
        )
    except ClientError as exc:
        # A 409 does not prove that a competing writer completed. Propagate it
        # so SQS can redeliver rather than reading or terminalizing uncertainty.
        if not _proves_object_already_exists(exc):
            raise
        canonical_body = s3.get_object(
            Bucket=config.s3_bucket,
            Key=run_result_key,
        )["Body"].read()
        existing: ScrapeResult | None = None
        reason = "existing exact-run result is invalid"
        try:
            existing_object = decode_strict_json_object(
                canonical_body,
                label=f"Canonical result {run_result_key}",
            )
            existing = ScrapeResult.model_validate(existing_object)
        except (ValueError, TypeError):
            pass
        else:
            if existing.item_id != item_id or existing.run_id != run_id:
                reason = "existing exact-run result has mismatched identity"
            elif existing.status not in _CONCLUSIVE_STATUSES:
                reason = "existing exact-run result is not conclusive"
            elif existing.is_soft_blocked or existing.is_network_error:
                reason = "existing exact-run result carries a retry hint"
            elif _observation(existing) == _observation(result):
                outcome = "duplicate"
                canonical_result = existing
            else:
                reason = "exact-run observations disagree"

        if outcome != "duplicate":
            conflict_key = _write_result_conflict(
                s3,
                config,
                item_id=item_id,
                run_id=run_id,
                existing_body=canonical_body,
                candidate_body=body,
                candidate=result,
                existing=existing,
                reason=reason,
                delivery_metadata=delivery_metadata,
            )
            if delivery_metadata is not None:
                write_terminal_disposition(
                    s3,
                    config,
                    run_id=run_id,
                    item_id=item_id,
                    delivery_metadata=delivery_metadata,
                    candidate=candidate,
                    canonical_key=run_result_key,
                    canonical_body=canonical_body,
                    canonical_result=existing,
                    outcome="conflict",
                    conflict_evidence_key=conflict_key,
                )
            raise ResultPublicationConflict(
                f"Conflicting exact-run result for run={run_id}, item={item_id}; "
                "durable conflict evidence was recorded"
            ) from None

    if delivery_metadata is not None:
        write_terminal_disposition(
            s3,
            config,
            run_id=run_id,
            item_id=item_id,
            delivery_metadata=delivery_metadata,
            candidate=candidate,
            canonical_key=run_result_key,
            canonical_body=canonical_body,
            canonical_result=canonical_result,
            outcome=outcome,
        )
    s3.put_object(
        Bucket=config.s3_bucket,
        Key=result_key,
        Body=canonical_body,
        ContentType="application/json",
    )
    return outcome


def _write_failure(
    s3: S3Client,
    config: WorkerConfig,
    run_id: str,
    item_id: str,
    result: ScrapeResult,
    *,
    delivery_metadata: dict[str, object] | None = None,
    _terminal_candidate: TerminalCandidate | None = None,
) -> Literal["created", "duplicate"]:
    """Publish one permanent failure with first-writer-wins semantics."""
    if result.status not in {ScrapeStatus.FAILED, ScrapeStatus.INVALID_INPUT}:
        raise ValueError(f"Cannot publish non-failure status {result.status.value}")
    if result.is_soft_blocked or result.is_network_error:
        raise ValueError("Cannot publish a permanent failure that carries a retry hint")
    prefix = f"{config.s3_scraper_prefix}/runs/{run_id}/failures"
    failure_key = f"{prefix}/{item_id}.json"
    if _terminal_candidate is None:
        result.item_id = item_id
        result.run_id = run_id
        result.scraped_at = datetime.now(UTC)
        data = result.model_dump(mode="json")
        data["failed_at"] = datetime.now(UTC).isoformat()
        body = json.dumps(data, sort_keys=True, allow_nan=False).encode()
        candidate = write_terminal_candidate(
            s3,
            config,
            run_id=run_id,
            item_id=item_id,
            kind="failure",
            candidate_body=body,
            result=result,
            delivery_metadata=delivery_metadata,
        )
    else:
        candidate = _terminal_candidate
        if (
            candidate.run_id != run_id
            or candidate.item_id != item_id
            or candidate.kind != "failure"
            or candidate.result != result
        ):
            raise CandidateJournalError("Failure replay candidate identity is invalid")
        body = candidate.candidate_body
    decision = claim_terminal_decision(s3, config, candidate=candidate)
    if decision.candidate.candidate_sha256 != candidate.candidate_sha256:
        if decision.kind == "failure":
            _write_failure(
                s3,
                config,
                run_id,
                item_id,
                decision.candidate.result,
                delivery_metadata=None,
                _terminal_candidate=decision.candidate,
            )
        else:
            _write_result(
                s3,
                config,
                item_id,
                run_id,
                decision.candidate.result,
                f"{config.s3_scraper_prefix}/results/{item_id}.json",
                delivery_metadata=None,
                _terminal_candidate=decision.candidate,
            )
            conflict = write_terminal_decision_conflict(
                s3,
                config,
                decision=decision,
                candidate=candidate,
            )
            if delivery_metadata is not None:
                write_terminal_disposition(
                    s3,
                    config,
                    run_id=run_id,
                    item_id=item_id,
                    delivery_metadata=delivery_metadata,
                    candidate=candidate,
                    canonical_key=decision.canonical_key,
                    canonical_body=decision.candidate.candidate_body,
                    canonical_result=decision.candidate.result,
                    outcome="conflict",
                    conflict_evidence_key=conflict.key,
                )
            raise FailurePublicationConflict(
                f"Terminal decision for run={run_id}, item={item_id} chose a "
                "conclusive result; durable cross-kind evidence was recorded"
            ) from None
    canonical_body = body
    canonical_result: ScrapeResult | None = result
    outcome: Literal["created", "duplicate"] = "created"
    try:
        s3.put_object(
            Bucket=config.s3_bucket,
            Key=failure_key,
            Body=body,
            ContentType="application/json",
            IfNoneMatch="*",
        )
    except ClientError as exc:
        if not _proves_object_already_exists(exc):
            raise
        canonical_body = s3.get_object(
            Bucket=config.s3_bucket,
            Key=failure_key,
        )["Body"].read()
        existing: ScrapeResult | None = None
        reason = "existing exact-run failure is invalid"
        try:
            decoded = decode_strict_json_object(
                canonical_body,
                label=f"Canonical failure {failure_key}",
            )
            existing = ScrapeResult.model_validate(decoded)
        except (TypeError, ValueError):
            pass
        else:
            if existing.item_id != item_id or existing.run_id != run_id:
                reason = "existing exact-run failure has mismatched identity"
            elif existing.status not in {ScrapeStatus.FAILED, ScrapeStatus.INVALID_INPUT}:
                reason = "existing exact-run failure is not permanent"
            elif existing.is_soft_blocked or existing.is_network_error:
                reason = "existing exact-run failure carries a retry hint"
            elif _observation(existing) == _observation(result):
                outcome = "duplicate"
                canonical_result = existing
            else:
                reason = "exact-run permanent failures disagree"
        if outcome != "duplicate":
            conflict_key = _write_failure_conflict(
                s3,
                config,
                item_id=item_id,
                run_id=run_id,
                existing_body=canonical_body,
                candidate_body=body,
                existing=existing,
                candidate=result,
                reason=reason,
            )
            if delivery_metadata is not None:
                write_terminal_disposition(
                    s3,
                    config,
                    run_id=run_id,
                    item_id=item_id,
                    delivery_metadata=delivery_metadata,
                    candidate=candidate,
                    canonical_key=failure_key,
                    canonical_body=canonical_body,
                    canonical_result=existing,
                    outcome="conflict",
                    conflict_evidence_key=conflict_key,
                )
            raise FailurePublicationConflict(
                f"Conflicting exact-run failure for run={run_id}, item={item_id}; "
                "durable conflict evidence was recorded"
            ) from None
    if delivery_metadata is not None:
        write_terminal_disposition(
            s3,
            config,
            run_id=run_id,
            item_id=item_id,
            delivery_metadata=delivery_metadata,
            candidate=candidate,
            canonical_key=failure_key,
            canonical_body=canonical_body,
            canonical_result=canonical_result,
            outcome=outcome,
        )
    return outcome


def _write_failure_conflict(
    s3: S3Client,
    config: WorkerConfig,
    *,
    item_id: str,
    run_id: str,
    existing_body: bytes,
    candidate_body: bytes,
    existing: ScrapeResult | None,
    candidate: ScrapeResult,
    reason: str,
) -> str:
    """Preserve a disagreeing permanent failure without changing canonical state."""
    candidate_sha256 = hashlib.sha256(candidate_body).hexdigest()
    key = (
        f"{config.s3_scraper_prefix}/runs/{run_id}/failure-conflicts/"
        f"v1/{item_id}/{candidate_sha256}.json"
    )
    record = {
        "schema_version": 1,
        "terminal_status": "failure-conflict",
        "run_id": run_id,
        "item_id": item_id,
        "detected_at": datetime.now(UTC).isoformat(),
        "reason": reason,
        "canonical_failure_key": (
            f"{config.s3_scraper_prefix}/runs/{run_id}/failures/{item_id}.json"
        ),
        "existing_sha256": hashlib.sha256(existing_body).hexdigest(),
        "candidate_sha256": candidate_sha256,
        "existing_observation": _observation(existing) if existing is not None else None,
        "candidate_observation": _observation(candidate),
        "candidate_body_base64": base64.b64encode(candidate_body).decode("ascii"),
    }
    try:
        s3.put_object(
            Bucket=config.s3_bucket,
            Key=key,
            Body=json.dumps(record, sort_keys=True, allow_nan=False).encode(),
            ContentType="application/json",
            IfNoneMatch="*",
        )
    except ClientError as exc:
        if not _proves_object_already_exists(exc):
            raise
    return key


def _write_failure_artifacts(
    s3: S3Client,
    config: WorkerConfig,
    run_id: str,
    item_id: str,
    artifacts: Iterable[FailureArtifact],
) -> None:
    """Write plugin-provided diagnostic artifacts beside failure JSON."""
    prefix = f"{config.s3_scraper_prefix}/runs/{run_id}/failures"
    for artifact in artifacts:
        suffix = artifact.suffix.lstrip(".")
        key = f"{prefix}/{item_id}.{suffix}"
        try:
            s3.put_object(
                Bucket=config.s3_bucket,
                Key=key,
                Body=artifact.body,
                ContentType=artifact.content_type,
            )
            logger.info(f"Failure artifact saved to s3://{config.s3_bucket}/{key}")
        except Exception:
            logger.debug(f"Failed to save failure artifact {key}")


def _write_stats(
    s3: S3Client,
    config: WorkerConfig,
    run_id: str,
    task_id: str,
    stats: dict[str, object],
) -> None:
    key = f"{config.s3_scraper_prefix}/runs/{run_id}/logs/{task_id}-stats.json"
    s3.put_object(
        Bucket=config.s3_bucket,
        Key=key,
        Body=json.dumps(stats, indent=2).encode(),
        ContentType="application/json",
    )
    logger.info(f"Stats written to s3://{config.s3_bucket}/{key}")


def _receive_message(sqs: SQSClient, config: WorkerConfig) -> MessageTypeDef | None:
    response = sqs.receive_message(
        QueueUrl=config.sqs_queue_url,
        MaxNumberOfMessages=1,
        WaitTimeSeconds=20,
        VisibilityTimeout=_MESSAGE_VISIBILITY_TIMEOUT_S,
        MessageSystemAttributeNames=[
            "ApproximateFirstReceiveTimestamp",
            "ApproximateReceiveCount",
            "SenderId",
            "SentTimestamp",
            "SequenceNumber",
        ],
    )
    messages = response.get("Messages", [])
    return messages[0] if messages else None


def _queue_is_empty(sqs: SQSClient, config: WorkerConfig) -> bool:
    attrs = sqs.get_queue_attributes(
        QueueUrl=config.sqs_queue_url,
        AttributeNames=[
            "ApproximateNumberOfMessages",
            "ApproximateNumberOfMessagesNotVisible",
            "ApproximateNumberOfMessagesDelayed",
        ],
    )["Attributes"]
    visible = int(attrs["ApproximateNumberOfMessages"])
    in_flight = int(attrs["ApproximateNumberOfMessagesNotVisible"])
    delayed = int(attrs["ApproximateNumberOfMessagesDelayed"])
    if visible == 0 and in_flight == 0 and delayed == 0:
        return True
    logger.info(f"Still waiting: visible={visible}, in_flight={in_flight}, delayed={delayed}")
    return False


def _requeue(sqs: SQSClient, config: WorkerConfig, receipt: str, timeout: int) -> None:
    sqs.change_message_visibility(
        QueueUrl=config.sqs_queue_url,
        ReceiptHandle=receipt,
        VisibilityTimeout=timeout,
    )


def _parse_work_message(raw_body: str, default_run_id: str) -> WorkMessage:
    """Parse and validate an SQS body at the worker boundary."""
    if not isinstance(raw_body, str):
        raise ValueError("SQS message body must be a string")

    def reject_constant(value: str) -> None:
        raise ValueError(f"SQS message contains non-standard JSON constant: {value}")

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        decoded_object: dict[str, object] = {}
        for key, value in pairs:
            if key in decoded_object:
                raise ValueError(f"SQS message contains duplicate JSON field: {key}")
            decoded_object[key] = value
        return decoded_object

    decoded = json.loads(
        raw_body,
        object_pairs_hook=unique_object,
        parse_constant=reject_constant,
    )
    if not isinstance(decoded, dict):
        raise ValueError("SQS message body must be a JSON object")
    stack: list[tuple[object, int]] = [(decoded, 0)]
    while stack:
        value, depth = stack.pop()
        if depth > _MAX_MESSAGE_NESTING:
            raise ValueError(f"SQS message exceeds maximum JSON nesting of {_MAX_MESSAGE_NESTING}")
        if isinstance(value, dict):
            stack.extend((child, depth + 1) for child in value.values())
        elif isinstance(value, list):
            stack.extend((child, depth + 1) for child in value)
    if "run_id" not in decoded:
        raise ValueError(
            "SQS message is missing run_id; assigning it to worker run "
            f"{default_run_id!r} would violate exact-run isolation"
        )
    return WorkMessage.model_validate(decoded)


def _quarantine_invalid_message(
    sqs: SQSClient,
    config: WorkerConfig,
    message: MessageTypeDef,
    error: Exception,
) -> None:
    """Move a malformed message to the DLQ without terminating the worker."""
    raw_body = message.get("Body")
    receipt = message.get("ReceiptHandle")
    if not isinstance(receipt, str) or not receipt:
        logger.error(f"Cannot quarantine malformed SQS message without a receipt: {error}")
        return

    dlq_body = raw_body if isinstance(raw_body, str) and raw_body else "{}"
    # Delete only after the DLQ accepts the copy, so a transient send failure
    # cannot discard the original message.
    sqs.send_message(QueueUrl=config.sqs_dlq_url, MessageBody=dlq_body)
    sqs.delete_message(QueueUrl=config.sqs_queue_url, ReceiptHandle=receipt)
    logger.error(f"Quarantined malformed SQS message: {error}")


def _quarantine_result_conflict(
    sqs: SQSClient,
    config: WorkerConfig,
    message: MessageTypeDef,
    error: RuntimeError,
) -> None:
    """Move a conflicting duplicate to the DLQ only after its durable record exists."""
    raw_body = message.get("Body")
    receipt = message.get("ReceiptHandle")
    if not isinstance(raw_body, str) or not raw_body:
        raise ValueError("Cannot quarantine result conflict without its original message body")
    if not isinstance(receipt, str) or not receipt:
        raise ValueError("Cannot quarantine result conflict without a receipt handle")
    sqs.send_message(QueueUrl=config.sqs_dlq_url, MessageBody=raw_body)
    sqs.delete_message(QueueUrl=config.sqs_queue_url, ReceiptHandle=receipt)
    logger.error(f"Quarantined conflicting exact-run publication: {error}")


def _ensure_failure_dlq_delivery(
    s3: S3Client,
    sqs: SQSClient,
    config: WorkerConfig,
    message: MessageTypeDef,
    *,
    run_id: str,
    item_id: str,
) -> None:
    """Complete the failure-to-DLQ outbox step before main-queue deletion."""
    marker_key = f"{config.s3_scraper_prefix}/runs/{run_id}/failure-deliveries/{item_id}.json"
    if _result_exists(s3, config.s3_bucket, marker_key):
        return
    raw_body = message.get("Body")
    if not isinstance(raw_body, str) or not raw_body:
        raise ValueError("Cannot deliver a permanent failure without its original message body")
    response = sqs.send_message(QueueUrl=config.sqs_dlq_url, MessageBody=raw_body)
    message_id = response.get("MessageId")
    record = {
        "schema_version": 1,
        "run_id": run_id,
        "item_id": item_id,
        "delivered_at": datetime.now(UTC).isoformat(),
        "body_sha256": hashlib.sha256(raw_body.encode()).hexdigest(),
        "dlq_message_id": message_id if isinstance(message_id, str) else None,
    }
    try:
        s3.put_object(
            Bucket=config.s3_bucket,
            Key=marker_key,
            Body=json.dumps(record, sort_keys=True, allow_nan=False).encode(),
            ContentType="application/json",
            IfNoneMatch="*",
        )
    except ClientError as exc:
        if not _proves_object_already_exists(exc):
            raise


def _read_work_message(
    sqs: SQSClient,
    config: WorkerConfig,
    message: MessageTypeDef,
    default_run_id: str,
) -> WorkMessage | None:
    """Validate or quarantine one message without escaping its failure boundary."""
    try:
        raw_body = message["Body"]
        receipt = message["ReceiptHandle"]
        if not isinstance(raw_body, str):
            raise ValueError("SQS message body must be a string")
        if not isinstance(receipt, str) or not receipt:
            raise ValueError("SQS message receipt handle must be a non-empty string")
        work_message = _parse_work_message(raw_body, default_run_id)
        if work_message.run_id != default_run_id:
            raise ValueError(
                f"SQS message belongs to run {work_message.run_id!r}, not worker run "
                f"{default_run_id!r}"
            )
        return work_message
    except Exception as exc:
        try:
            _quarantine_invalid_message(sqs, config, message, exc)
        except Exception:
            logger.exception(
                "Failed to quarantine malformed SQS message; leaving it for redelivery"
            )
        return None


def run_worker(scraper_factory: Callable[[], Scraper], config: WorkerConfig | None = None) -> None:
    """Long-poll SQS and scrape one item per message until queue drains or SIGTERM.

    Parameters
    ----------
    scraper_factory
        Callable that returns a fresh ``Scraper`` instance. Called once at startup.
    config
        Worker configuration. If None, loads from environment via ``WorkerConfig()``.
        Subclasses of WorkerConfig are accepted and their defaults apply.
    """
    if config is None:
        config = WorkerConfig()

    session = make_boto3_session(config=config)
    s3 = session.client("s3")
    sqs = session.client("sqs")

    shutdown = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: shutdown.set())
    signal.signal(signal.SIGALRM, _sigalrm_handler)

    task_id = socket.gethostname()
    start_time = datetime.now(UTC)
    run_id = config.run_id

    startup_delay = random.uniform(0, 30)
    logger.info(f"Startup jitter: sleeping {startup_delay:.1f}s before first poll")
    time.sleep(startup_delay)

    scraper = scraper_factory()
    consecutive_empty = 0
    stats = WorkerStats()

    logger.info(f"Worker started. task_id={task_id}, run_id={run_id}, queue={config.sqs_queue_url}")

    try:
        while not shutdown.is_set():
            msg = _receive_message(sqs, config)
            if msg is None:
                consecutive_empty += 1
                if consecutive_empty >= 3 and _queue_is_empty(sqs, config):
                    logger.info("Queue empty — worker exiting")
                    break
                if consecutive_empty >= 3:
                    consecutive_empty = 0
                continue

            consecutive_empty = 0
            work_message = _read_work_message(sqs, config, msg, run_id)
            if work_message is None:
                stats.permanent_failure_count += 1
                continue
            item = work_message.to_work_item()
            item_id = item.item_id
            msg_run_id = work_message.run_id
            receipt = msg["ReceiptHandle"]

            result_key = f"{config.s3_scraper_prefix}/results/{item_id}.json"
            exact_run_prefix = f"{config.s3_scraper_prefix}/runs/{msg_run_id}"
            exact_result_key = f"{exact_run_prefix}/results/{item_id}.json"
            exact_failure_key = f"{exact_run_prefix}/failures/{item_id}.json"
            delivery_metadata = _sqs_delivery_metadata(msg)

            # Submit/recovery decides which IDs enter the queue. Once a validated
            # same-run message exists, the worker never drops it merely because
            # the mutable cross-run cache has an object. Every delivery performs
            # one portal lookup and runs through the append-only candidate,
            # decision, conflict, and disposition protocol. This deliberately
            # favors crash-safe evidence reconstruction over a rare one-item
            # lookup optimization; it never causes a whole-run re-scrape.
            exact_result_exists = _result_exists(s3, config.s3_bucket, exact_result_key)
            exact_failure_exists = _result_exists(s3, config.s3_bucket, exact_failure_key)
            if exact_result_exists or exact_failure_exists:
                if exact_result_exists and exact_failure_exists:
                    logger.error(
                        "Exact-run result/failure overlap for {}; re-scraping because no "
                        "terminal checkpoint can be trusted. Recovery finalization remains "
                        "blocked.",
                        item_id,
                    )
                else:
                    logger.warning(
                        "Exact-run terminal object exists for {}; repeating one lookup "
                        "to reconstruct append-only delivery evidence",
                        item_id,
                    )

            logger.info(f"Scraping {item_id}")
            t0 = time.perf_counter()
            result: ScrapeResult
            try:
                signal.alarm(_SCRAPE_TIMEOUT_S)
                result = scraper(item)
            except TimeoutError:
                logger.warning(
                    f"Scrape timed out after {_SCRAPE_TIMEOUT_S}s for {item_id} "
                    f"— resetting scraper, message will be redelivered by SQS"
                )
                with contextlib.suppress(Exception):
                    _requeue(sqs, config, receipt, 30)
                signal.alarm(30)  # bound the scraper close; if it hangs, worker exits
                scraper.reset()
                continue
            except Exception:
                logger.exception(
                    f"Uncaught exception scraping {item_id} — letting visibility timeout expire"
                )
                continue
            finally:
                signal.alarm(0)

            stats.items_processed += 1
            result.scrape_duration_s = round(time.perf_counter() - t0, 3)

            if result.is_soft_blocked:
                stats.soft_blocked_count += 1
                delay = int(
                    random.uniform(config.soft_blocked_delay_min, config.soft_blocked_delay_max)
                )
                logger.warning(
                    f"Soft-blocked on {item_id}, requeueing with {delay}s visibility delay"
                )
                _requeue(sqs, config, receipt, delay)
                scraper.reset()
                continue

            if result.status in (ScrapeStatus.SUCCESS, ScrapeStatus.NO_RESULTS):
                try:
                    publication = _write_result(
                        s3,
                        config,
                        item_id,
                        msg_run_id,
                        result,
                        result_key,
                        delivery_metadata=delivery_metadata,
                    )
                except ResultPublicationConflict as exc:
                    stats.permanent_failure_count += 1
                    try:
                        _quarantine_result_conflict(sqs, config, msg, exc)
                    except Exception:
                        logger.exception(
                            "Failed to quarantine conflicting result; leaving it for redelivery"
                        )
                    continue
                sqs.delete_message(QueueUrl=config.sqs_queue_url, ReceiptHandle=receipt)
                if result.status == ScrapeStatus.SUCCESS:
                    stats.success_count += 1
                else:
                    stats.no_results_count += 1
                logger.info(f"Done: {item_id} → {result.status.value} (publication={publication})")

            elif result.status in (ScrapeStatus.FAILED, ScrapeStatus.INVALID_INPUT):
                if result.is_network_error:
                    delay = 300
                    _requeue(sqs, config, receipt, delay)
                    logger.warning(
                        f"Network error on {item_id} — requeued with {delay}s visibility delay"
                    )
                    scraper.reset()
                    continue
                else:
                    stats.permanent_failure_count += 1
                    logger.warning(f"Permanent failure on {item_id}: {result.classification}")
                    try:
                        _write_failure(
                            s3,
                            config,
                            msg_run_id,
                            item_id,
                            result,
                            delivery_metadata=delivery_metadata,
                        )
                    except FailurePublicationConflict as exc:
                        try:
                            _quarantine_result_conflict(sqs, config, msg, exc)
                        except Exception:
                            logger.exception(
                                "Failed to quarantine conflicting failure; leaving it "
                                "for redelivery"
                            )
                        continue
                    artifact_getter = getattr(scraper, "failure_artifacts", None)
                    if callable(artifact_getter):
                        try:
                            artifacts = artifact_getter(item)
                        except Exception:
                            logger.debug(f"Failed to collect failure artifacts for {item_id}")
                        else:
                            _write_failure_artifacts(
                                s3,
                                config,
                                msg_run_id,
                                item_id,
                                artifacts,
                            )
                    _ensure_failure_dlq_delivery(
                        s3,
                        sqs,
                        config,
                        msg,
                        run_id=msg_run_id,
                        item_id=item_id,
                    )
                    sqs.delete_message(QueueUrl=config.sqs_queue_url, ReceiptHandle=receipt)

            time.sleep(random.uniform(0.5, 1.5))

    finally:
        try:
            signal.alarm(15)
            scraper.close()
        except Exception:
            pass
        finally:
            signal.alarm(0)

        end_time = datetime.now(UTC)
        runtime_seconds = (end_time - start_time).total_seconds()
        try:
            _write_stats(
                s3,
                config,
                run_id,
                task_id,
                stats.as_dict(
                    task_id=task_id,
                    run_id=run_id,
                    runtime_seconds=runtime_seconds,
                ),
            )
        except Exception:
            logger.exception("Failed to write worker stats")

        logger.info(
            f"Worker shut down. Runtime: {runtime_seconds:.0f}s, "
            f"processed: {stats.items_processed}, "
            f"success: {stats.success_count}, no_results: {stats.no_results_count}, "
            f"soft_blocked: {stats.soft_blocked_count}, "
            f"failures: {stats.permanent_failure_count}"
        )
