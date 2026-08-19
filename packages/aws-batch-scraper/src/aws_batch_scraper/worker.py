"""Generic SQS worker: long-poll the queue and scrape one item per message."""

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
_OBSERVATION_FIELDS = {
    "status",
    "data",
    "classification",
    "subreason",
    "is_soft_blocked",
    "is_network_error",
    "final_url",
    "error_message",
    "extra",
}


class ResultPublicationConflict(RuntimeError):
    """Raised after durable evidence proves two run results disagree."""


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
    """Return stable scraper output, excluding per-attempt timing metadata."""
    return result.model_dump(mode="json", include=_OBSERVATION_FIELDS)


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
) -> None:
    """Persist fail-closed evidence before a conflicting message is terminalized."""
    existing_observation = _observation(existing) if existing is not None else None
    candidate_observation = _observation(candidate)
    differing_fields = (
        sorted(
            field
            for field in _OBSERVATION_FIELDS
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
    record = {
        "schema_version": 1,
        "terminal_status": "result-conflict",
        "run_id": run_id,
        "item_id": item_id,
        "detected_at": datetime.now(UTC).isoformat(),
        "reason": reason,
        "existing_sha256": hashlib.sha256(existing_body).hexdigest(),
        "candidate_sha256": hashlib.sha256(candidate_body).hexdigest(),
        "existing_status": existing.status.value if existing is not None else None,
        "candidate_status": candidate.status.value,
        "differing_fields": differing_fields,
    }
    key = f"{config.s3_scraper_prefix}/runs/{run_id}/result-conflicts/{item_id}.json"
    try:
        s3.put_object(
            Bucket=config.s3_bucket,
            Key=key,
            Body=json.dumps(record, indent=2, allow_nan=False).encode(),
            ContentType="application/json",
            IfNoneMatch="*",
        )
    except ClientError as exc:
        # A 409 conditional-request conflict can occur while an object is being
        # deleted and does not prove this terminal evidence exists durably.
        if not _proves_object_already_exists(exc):
            raise


def _write_result(
    s3: S3Client,
    config: WorkerConfig,
    item_id: str,
    run_id: str,
    result: ScrapeResult,
    result_key: str,
) -> Literal["created", "duplicate"]:
    """Publish one exact-run observation with first-writer-wins semantics."""
    if result.status not in _CONCLUSIVE_STATUSES:
        raise ValueError(f"Cannot publish inconclusive result status {result.status.value}")
    result.item_id = item_id
    result.scraped_at = datetime.now(UTC)
    result.run_id = run_id
    body = result.model_dump_json().encode()
    run_result_key = f"{config.s3_scraper_prefix}/runs/{run_id}/results/{item_id}.json"
    canonical_body = body
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
            existing = ScrapeResult.model_validate_json(canonical_body)
        except (ValueError, TypeError):
            pass
        else:
            if existing.item_id != item_id or existing.run_id != run_id:
                reason = "existing exact-run result has mismatched identity"
            elif existing.status not in _CONCLUSIVE_STATUSES:
                reason = "existing exact-run result is not conclusive"
            elif _observation(existing) == _observation(result):
                outcome = "duplicate"
            else:
                reason = "exact-run observations disagree"

        if outcome != "duplicate":
            _write_result_conflict(
                s3,
                config,
                item_id=item_id,
                run_id=run_id,
                existing_body=canonical_body,
                candidate_body=body,
                candidate=result,
                existing=existing,
                reason=reason,
            )
            raise ResultPublicationConflict(
                f"Conflicting exact-run result for run={run_id}, item={item_id}; "
                "durable conflict evidence was recorded"
            ) from None

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
) -> None:
    prefix = f"{config.s3_scraper_prefix}/runs/{run_id}/failures"
    data = result.model_dump(mode="json")
    data["item_id"] = item_id
    data["run_id"] = run_id
    data["failed_at"] = datetime.now(UTC).isoformat()
    s3.put_object(
        Bucket=config.s3_bucket,
        Key=f"{prefix}/{item_id}.json",
        Body=json.dumps(data).encode(),
        ContentType="application/json",
    )


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
    error: ResultPublicationConflict,
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
    logger.error(f"Quarantined conflicting exact-run result: {error}")


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

            # Idempotency is controlled by the message's originating submit run.
            # A force worker must not accidentally force stale messages from a
            # different run that happen to share the queue.
            if not work_message.force_rescrape and _result_exists(s3, config.s3_bucket, result_key):
                logger.info(f"Already processed {item_id}, skipping")
                sqs.delete_message(QueueUrl=config.sqs_queue_url, ReceiptHandle=receipt)
                continue

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
                    _write_failure(s3, config, msg_run_id, item_id, result)
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
                    sqs.send_message(QueueUrl=config.sqs_dlq_url, MessageBody=msg["Body"])
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
