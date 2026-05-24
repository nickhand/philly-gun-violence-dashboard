"""Submit a scrape run: filter incidents, seed SQS, launch Fargate workers."""

import random

from loguru import logger
from mypy_boto3_ecs.client import ECSClient
from mypy_boto3_s3.client import S3Client
from mypy_boto3_sqs.client import SQSClient

from etl.courts.batch.aws import (
    get_existing_incidents,
    launch_monitor,
    launch_workers,
    make_run_id,
    seed_queue,
    write_run_manifest,
    write_task_arns,
)
from etl.courts.config import SubmitterConfig


def submit_run(
    s3: S3Client,
    sqs: SQSClient,
    ecs: ECSClient,
    config: SubmitterConfig,
    *,
    sample: int | None = None,
    seed: int = 42,
    workers: int | None = None,
    force: bool = False,
    dry_run: bool = False,
    soft_blocked_delay: int | None = None,
    monitor_in_ecs: bool = False,
) -> str | None:
    """Filter incidents, seed the SQS queue, and launch Fargate workers.

    Returns the run_id, or None if there was nothing to do.
    """
    from etl.utils.storage import load_shootings_database

    gdf = load_shootings_database(s3=s3)
    all_incidents = gdf["dc_key"].astype(str).unique().tolist()

    if sample is not None:
        random.seed(seed)
        all_incidents = random.sample(all_incidents, min(sample, len(all_incidents)))

    existing = get_existing_incidents(s3, config)
    if force:
        incidents = all_incidents
        logger.info(
            f"--force: queuing all {len(incidents)} incidents "
            f"(ignoring {len(existing)} existing results)"
        )
    else:
        incidents = [inc for inc in all_incidents if inc not in existing]
        logger.info(
            f"{len(incidents)}/{len(all_incidents)} incidents missing results — seeding queue"
        )

    if not incidents:
        logger.info("All incidents already scraped. Nothing to do.")
        return None

    worker_count = workers if workers is not None else config.ecs_task_count
    run_id = make_run_id()
    logger.info(f"Run ID: {run_id}")

    seed_queue(sqs, config, incidents, run_id)
    write_run_manifest(s3, config, run_id, incidents, worker_count=worker_count)

    if not dry_run:
        task_arns = launch_workers(
            ecs,
            config,
            run_id,
            worker_count=worker_count,
            force_rescrape=force,
            soft_blocked_delay_max=soft_blocked_delay,
        )
        write_task_arns(s3, config, run_id, task_arns)
        if monitor_in_ecs:
            launch_monitor(ecs, config, run_id)
    else:
        logger.info("dry_run=True: skipping ECS worker launch")

    return run_id
