"""Extraction helpers for courts portal scraping.

Seeds the SQS queue, launches Fargate workers, waits for completion,
then aggregates per-incident results from S3.
"""

from dataclasses import dataclass
from typing import Literal

import pandas as pd
from loguru import logger
from mypy_boto3_s3.client import S3Client

from etl.courts.batch.aggregate import aggregate_results
from etl.courts.batch.aws import (
    get_existing_incidents,
    launch_workers,
    make_run_id,
    monitor_until_empty,
    seed_queue,
    write_run_manifest,
)
from etl.courts.config import ScraperConfig
from etl.courts.scraper.schema import ScrapeOutcome


@dataclass
class PortalBatchConfig:
    """Configuration for portal batch scraping.

    Attributes
    ----------
    search_by : str
        The field to search by; defaults to "Incident Number".
    sleep : int
        Seconds to sleep between requests (passed to worker scraper).
    log_freq : int
        Frequency of logging progress.
    seed : int
        Random seed for sampling.
    errors : str
        Error handling strategy.
    dry_run : bool
        If True, seed queue but don't launch ECS workers.
    sample : int | None
        If set, randomly sample this many incident numbers.
    debug : bool
        If True, run in debug mode.
    exclude_known_cases : bool
        If True, exclude incident numbers already known to have court cases.
    no_retry : bool
        If True, disable retry mechanism (max_attempts=1) for debugging.
    screenshots : bool
        If True, enable screenshots for failures.
    """

    search_by: Literal["Incident Number", "Docket Number"] = "Incident Number"
    sleep: int = 7
    log_freq: int = 10
    seed: int = 42
    errors: Literal["ignore", "raise"] = "ignore"
    dry_run: bool = False
    sample: int | None = None
    debug: bool = False
    exclude_known_cases: bool = False
    no_retry: bool = False
    screenshots: bool = True


def extract_portal(
    s3: S3Client,
    incident_numbers: pd.DataFrame,
    cfg: PortalBatchConfig,
) -> dict[str, ScrapeOutcome]:
    """Seed the SQS queue, launch workers, wait for completion, return results.

    Parameters
    ----------
    s3 : S3Client
        S3 client for writing manifest and reading results.
    incident_numbers : pd.DataFrame
        DataFrame with a column ``dc_key`` of incident numbers to scrape.
    cfg : PortalBatchConfig
        Batch configuration.

    Returns
    -------
    dict[str, ScrapeOutcome]
        Mapping from incident number to ScrapeOutcome.
    """
    from dashboard_utils.aws import make_boto3_session

    config = ScraperConfig()
    session = make_boto3_session()
    sqs = session.client("sqs")
    ecs = session.client("ecs")

    # Optional sample
    if cfg.sample is not None:
        incident_numbers = incident_numbers.sample(cfg.sample, random_state=cfg.seed)

    incidents = incident_numbers["dc_key"].astype(str).tolist()

    existing = get_existing_incidents(s3, config)
    incidents = [inc for inc in incidents if inc not in existing]
    logger.info(f"{len(incidents)} incidents missing results — seeding queue")

    if not incidents:
        logger.info("All incidents already scraped — returning existing results")
        return aggregate_results(s3, config)

    run_id = make_run_id()
    logger.info(f"Run ID: {run_id}")

    # Seed queue and write audit manifest
    seed_queue(sqs, config, incidents, run_id)
    write_run_manifest(s3, config, run_id, incidents, worker_count=config.ecs_task_count)

    if not cfg.dry_run:
        launch_workers(ecs, config, run_id)
        monitor_until_empty(sqs, config, s3=s3, run_id=run_id)
    else:
        logger.info("dry_run=True: skipping worker launch and queue monitoring")

    return aggregate_results(s3, config)
