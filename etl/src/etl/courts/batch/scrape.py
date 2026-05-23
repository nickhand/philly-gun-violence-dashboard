"""SQS worker: long-poll the queue and scrape one incident per message."""

import json
import os
import random
import signal
import socket
import threading
import time
from datetime import UTC, datetime

from botocore.exceptions import ClientError
from loguru import logger

from dashboard_utils.aws import make_boto3_session
from etl.courts.config import ScraperConfig
from etl.courts.scraper.core import UJSPortalScraper
from etl.courts.scraper.schema import OutcomeStatus, ScrapeOutcome, SoftBlocked

# Hard cap on a single scrape attempt (max_attempts * worst-case timing).
# Fires SIGALRM if Playwright deadlocks at the subprocess level.
_SCRAPE_TIMEOUT_S = 300


def _result_exists(s3, bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] in {"404", "NoSuchKey"}:
            return False
        raise


def _write_result(
    s3,
    config: ScraperConfig,
    incident: str,
    run_id: str,
    outcome: ScrapeOutcome,
    result_key: str,
) -> None:
    outcome.incident_number = incident
    outcome.scraped_at = datetime.now(UTC)
    outcome.run_id = run_id
    s3.put_object(
        Bucket=config.s3_bucket,
        Key=result_key,
        Body=outcome.model_dump_json().encode(),
        ContentType="application/json",
    )


def _write_failure(
    s3,
    config: ScraperConfig,
    run_id: str,
    incident: str,
    outcome: ScrapeOutcome,
    page=None,
) -> None:
    prefix = f"{config.s3_scraper_prefix}/runs/{run_id}/failures"
    data = outcome.model_dump(mode="json")
    data["failed_at"] = datetime.now(UTC).isoformat()
    s3.put_object(
        Bucket=config.s3_bucket,
        Key=f"{prefix}/{incident}.json",
        Body=json.dumps(data).encode(),
        ContentType="application/json",
    )
    if page is not None:
        try:
            screenshot_bytes = page.screenshot(full_page=True)
            s3.put_object(
                Bucket=config.s3_bucket,
                Key=f"{prefix}/{incident}.png",
                Body=screenshot_bytes,
                ContentType="image/png",
            )
            logger.info(f"Screenshot saved to s3://{config.s3_bucket}/{prefix}/{incident}.png")
        except Exception:
            logger.debug("Failed to capture failure screenshot")


def _write_stats(s3, config: ScraperConfig, run_id: str, task_id: str, stats: dict) -> None:
    key = f"{config.s3_scraper_prefix}/runs/{run_id}/logs/{task_id}-stats.json"
    s3.put_object(
        Bucket=config.s3_bucket,
        Key=key,
        Body=json.dumps(stats, indent=2).encode(),
        ContentType="application/json",
    )
    logger.info(f"Stats written to s3://{config.s3_bucket}/{key}")


def _sigalrm_handler(signum: int, frame: object) -> None:
    raise TimeoutError(f"scrape exceeded {_SCRAPE_TIMEOUT_S}s")


def run_worker(config: ScraperConfig, run_id: str) -> None:
    """Long-poll SQS and scrape one incident per message until queue drains or SIGTERM."""
    session = make_boto3_session()
    s3 = session.client("s3")
    sqs = session.client("sqs")

    shutdown = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: shutdown.set())
    signal.signal(signal.SIGALRM, _sigalrm_handler)

    task_id = socket.gethostname()
    start_time = datetime.now(UTC)
    force_rescrape = os.environ.get("FORCE_RESCRAPE", "").lower() in ("1", "true", "yes")

    startup_delay = random.uniform(0, 30)
    logger.info(f"Startup jitter: sleeping {startup_delay:.1f}s before first poll")
    time.sleep(startup_delay)

    scraper = UJSPortalScraper(
        max_attempts=8,
        enable_screenshots=False,
        errors="ignore",
    )
    consecutive_empty = 0

    # Stats counters
    incidents_processed = 0
    success_count = 0
    no_results_count = 0
    soft_blocked_count = 0
    permanent_failure_count = 0

    logger.info(f"Worker started. task_id={task_id}, run_id={run_id}, queue={config.sqs_queue_url}, force_rescrape={force_rescrape}")

    try:
        while not shutdown.is_set():
            response = sqs.receive_message(
                QueueUrl=config.sqs_queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20,
            )
            messages = response.get("Messages", [])

            if not messages:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    # Confirm queue is truly empty (visible + in-flight)
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
                        logger.info("Queue empty — worker exiting")
                        break
                    logger.info(f"Still waiting: visible={visible}, in_flight={in_flight}")
                    consecutive_empty = 0
                continue

            consecutive_empty = 0
            msg = messages[0]
            body = json.loads(msg["Body"])
            incident = body["incident_number"]
            receipt = msg["ReceiptHandle"]

            result_key = f"{config.s3_scraper_prefix}/results/{incident}.json"

            # Idempotency check: skip if already scraped (bypassed when FORCE_RESCRAPE=1)
            if not force_rescrape and _result_exists(s3, config.s3_bucket, result_key):
                logger.info(f"Already scraped {incident}, skipping")
                sqs.delete_message(QueueUrl=config.sqs_queue_url, ReceiptHandle=receipt)
                continue

            logger.info(f"Scraping {incident}")
            t0 = time.perf_counter()
            try:
                signal.alarm(_SCRAPE_TIMEOUT_S)
                outcome: ScrapeOutcome = scraper(incident)
            except SoftBlocked:
                soft_blocked_count += 1
                delay_min = int(os.environ.get("SOFT_BLOCKED_DELAY_MIN", "300"))
                delay_max = int(os.environ.get("SOFT_BLOCKED_DELAY_MAX", "900"))
                delay = int(random.uniform(delay_min, delay_max))
                logger.warning(
                    f"SOFT_BLOCKED {incident}, requeueing with {delay}s visibility delay"
                )
                sqs.change_message_visibility(
                    QueueUrl=config.sqs_queue_url,
                    ReceiptHandle=receipt,
                    VisibilityTimeout=delay,
                )
                # Recycle Playwright context after a block to clear session state
                logger.info("Recycling Playwright context after SOFT_BLOCKED")
                scraper._reset_page()
                continue
            except TimeoutError:
                logger.warning(
                    f"Scrape timed out after {_SCRAPE_TIMEOUT_S}s for {incident} "
                    f"— resetting context, message will be redelivered by SQS"
                )
                try:
                    sqs.change_message_visibility(
                        QueueUrl=config.sqs_queue_url,
                        ReceiptHandle=receipt,
                        VisibilityTimeout=30,
                    )
                except Exception:
                    pass
                signal.alarm(30)  # bound the browser close; if it hangs, worker exits
                scraper._reset_page()
                continue
            except Exception:
                logger.exception(
                    f"Uncaught exception scraping {incident} — letting visibility timeout expire"
                )
                continue
            finally:
                signal.alarm(0)

            incidents_processed += 1

            outcome.scrape_duration_s = round(time.perf_counter() - t0, 3)

            if outcome.status in (OutcomeStatus.SUCCESS, OutcomeStatus.NO_RESULTS):
                _write_result(s3, config, incident, run_id, outcome, result_key)
                sqs.delete_message(QueueUrl=config.sqs_queue_url, ReceiptHandle=receipt)
                if outcome.status == OutcomeStatus.SUCCESS:
                    success_count += 1
                else:
                    no_results_count += 1
                logger.info(f"Done: {incident} → {outcome.status.value}")

            elif outcome.status in (OutcomeStatus.FAILED, OutcomeStatus.INVALID_INPUT):
                if outcome.classification == "NETWORK_OR_SERVER_ERROR":
                    sqs.change_message_visibility(
                        QueueUrl=config.sqs_queue_url,
                        ReceiptHandle=receipt,
                        VisibilityTimeout=300,
                    )
                    logger.warning(
                        f"NETWORK_OR_SERVER_ERROR on {incident} — requeueing for another worker"
                    )
                else:
                    permanent_failure_count += 1
                    logger.warning(f"Permanent failure on {incident}: {outcome.classification}")
                    _write_failure(s3, config, run_id, incident, outcome, page=scraper._page)
                    sqs.send_message(QueueUrl=config.sqs_dlq_url, MessageBody=msg["Body"])
                    sqs.delete_message(QueueUrl=config.sqs_queue_url, ReceiptHandle=receipt)

            # Fixed inter-incident jitter (politeness delay per AOPC agreement)
            time.sleep(random.uniform(0.5, 1.5))

    finally:
        scraper.close()

        end_time = datetime.now(UTC)
        runtime_seconds = (end_time - start_time).total_seconds()
        incidents_per_minute = (incidents_processed / runtime_seconds * 60) if runtime_seconds > 0 else 0

        stats = {
            "task_id": task_id,
            "run_id": run_id,
            "incidents_processed": incidents_processed,
            "success_count": success_count,
            "no_results_count": no_results_count,
            "soft_blocked_count": soft_blocked_count,
            "permanent_failure_count": permanent_failure_count,
            "total_runtime_seconds": round(runtime_seconds, 1),
            "incidents_per_minute": round(incidents_per_minute, 1),
        }
        try:
            _write_stats(s3, config, run_id, task_id, stats)
        except Exception:
            logger.exception("Failed to write worker stats")

        logger.info(
            f"Worker shut down. Runtime: {runtime_seconds:.0f}s, "
            f"processed: {incidents_processed}, "
            f"success: {success_count}, no_results: {no_results_count}, "
            f"soft_blocked: {soft_blocked_count}, failures: {permanent_failure_count}"
        )


def main() -> None:
    """Entry point for the Fargate worker container."""
    config = ScraperConfig()
    run_id = os.environ.get("RUN_ID", "unknown")
    run_worker(config, run_id)
