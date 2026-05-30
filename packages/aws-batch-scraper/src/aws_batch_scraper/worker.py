"""Generic SQS worker: long-poll the queue and scrape one item per message."""

import contextlib
import json
import random
import signal
import socket
import threading
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from types import FrameType

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
    WorkItem,
)

# Hard cap on a single scrape attempt. Fires SIGALRM if the scraper deadlocks
# at the subprocess/browser level.
_SCRAPE_TIMEOUT_S = 300
_MESSAGE_VISIBILITY_TIMEOUT_S = _SCRAPE_TIMEOUT_S + 120


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


def _write_result(
    s3: S3Client,
    config: WorkerConfig,
    item_id: str,
    run_id: str,
    result: ScrapeResult,
    result_key: str,
) -> None:
    result.item_id = item_id
    result.scraped_at = datetime.now(UTC)
    result.run_id = run_id
    s3.put_object(
        Bucket=config.s3_bucket,
        Key=result_key,
        Body=result.model_dump_json().encode(),
        ContentType="application/json",
    )


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
        ],
    )["Attributes"]
    visible = int(attrs["ApproximateNumberOfMessages"])
    in_flight = int(attrs["ApproximateNumberOfMessagesNotVisible"])
    if visible == 0 and in_flight == 0:
        return True
    logger.info(f"Still waiting: visible={visible}, in_flight={in_flight}")
    return False


def _requeue(sqs: SQSClient, config: WorkerConfig, receipt: str, timeout: int) -> None:
    sqs.change_message_visibility(
        QueueUrl=config.sqs_queue_url,
        ReceiptHandle=receipt,
        VisibilityTimeout=timeout,
    )


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
    force_rescrape = config.force_rescrape
    run_id = config.run_id

    startup_delay = random.uniform(0, 30)
    logger.info(f"Startup jitter: sleeping {startup_delay:.1f}s before first poll")
    time.sleep(startup_delay)

    scraper = scraper_factory()
    consecutive_empty = 0
    stats = WorkerStats()

    logger.info(
        f"Worker started. task_id={task_id}, run_id={run_id}, "
        f"queue={config.sqs_queue_url}, force_rescrape={force_rescrape}"
    )

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
            body = json.loads(msg["Body"])
            item_id: str = body["item_id"]
            msg_run_id: str = body.get("run_id", run_id)
            extra = {k: v for k, v in body.items() if k not in ("item_id", "run_id")}
            item = WorkItem(item_id=item_id, extra=extra)
            receipt = msg["ReceiptHandle"]

            result_key = f"{config.s3_scraper_prefix}/results/{item_id}.json"

            # Idempotency: skip if already processed (bypassed by FORCE_RESCRAPE=1)
            if not force_rescrape and _result_exists(s3, config.s3_bucket, result_key):
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
                _write_result(s3, config, item_id, msg_run_id, result, result_key)
                sqs.delete_message(QueueUrl=config.sqs_queue_url, ReceiptHandle=receipt)
                if result.status == ScrapeStatus.SUCCESS:
                    stats.success_count += 1
                else:
                    stats.no_results_count += 1
                logger.info(f"Done: {item_id} → {result.status.value}")

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
