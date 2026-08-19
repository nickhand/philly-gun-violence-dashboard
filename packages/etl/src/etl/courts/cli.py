"""Courts portal ETL CLI — built on the aws-batch-scraper framework."""

from typing import Annotated

import typer
from aws_batch_scraper.aws import make_boto3_session
from aws_batch_scraper.cli import create_cli
from loguru import logger

from etl.courts.config import CourtsSubmitterConfig, CourtsWorkerConfig
from etl.courts.extract import load_incidents
from etl.courts.scraper.core import UJSPortalScraper

app = create_cli(
    name="courts",
    script_name="gv-dashboard-etl",
    scraper_factory=lambda: UJSPortalScraper(max_attempts=8, errors="ignore"),
    input_loader=load_incidents,
    worker_config_class=CourtsWorkerConfig,
    submitter_config_class=CourtsSubmitterConfig,
)


@app.command()
def process() -> None:
    """Aggregate scraper results and write processed courts flags.

    Reads one completed run's inputs/results from S3, transforms them to
    nullable court-search flags, and writes the processed flags and diagnostics.
    """
    from uuid import uuid4

    from aws_batch_scraper.aggregate import read_run_items
    from aws_batch_scraper.lease import claim_run_lease_for_processing, release_run_lease

    from etl.courts.pipeline import process_results

    config = CourtsWorkerConfig()
    s3 = make_boto3_session(config=config).client("s3")
    run_id = config.run_id.strip()
    if not run_id or run_id == "unknown":
        raise typer.BadParameter("Courts processing requires a concrete RUN_ID.")

    # This read-only preflight must happen before claiming/releasing the lease.
    # An early manual dispatch can otherwise turn "workers still live" into a
    # terminal processing failure and accidentally permit an overlapping run.
    read_run_items(s3, config, run_id, require_completed=True)

    # Move from the coordinator's run-scoped owner to a unique process owner.
    # CAS makes this exclusive even when duplicate callers use the same RUN_ID.
    process_owner = f"process:{uuid4().hex}"
    claim_run_lease_for_processing(s3, config, run_id, process_owner)
    try:
        process_results(s3, config)
    except Exception as exc:
        try:
            released = release_run_lease(
                s3,
                config,
                run_id,
                owner=process_owner,
                terminal_status="failure",
                detail=str(exc),
            )
            if not released:
                logger.error(f"Failed court-processing run {run_id} no longer owns its lease")
        except Exception:
            logger.exception(f"Could not release lease after court-processing failure for {run_id}")
        raise
    else:
        released = release_run_lease(
            s3,
            config,
            run_id,
            owner=process_owner,
            terminal_status="success",
        )
        if not released:
            raise RuntimeError(f"Successful court-processing run {run_id} did not own its lease")


@app.command()
def smoke(
    skip_aws: Annotated[
        bool,
        typer.Option(help="Skip AWS queue, bucket, cluster, and task-definition checks."),
    ] = False,
    skip_portal: Annotated[
        bool,
        typer.Option(help="Skip live UJS portal browser startup check."),
    ] = False,
) -> None:
    """Validate courts scraper runtime dependencies without writing outputs."""
    if not skip_aws:
        from aws_batch_scraper.orchestrate import resolve_split_task_definitions

        config = CourtsSubmitterConfig()
        session = make_boto3_session(config=config)
        session.client("sqs").get_queue_attributes(
            QueueUrl=config.sqs_queue_url,
            AttributeNames=["QueueArn"],
        )
        session.client("s3").head_bucket(Bucket=config.s3_bucket)
        resolve_split_task_definitions(session.client("ecs"), config)
        logger.info("Courts AWS smoke checks passed.")

    if not skip_portal:
        with UJSPortalScraper(max_attempts=1, errors="ignore") as scraper:
            if scraper.page is None:
                raise RuntimeError("UJS portal browser check did not create a page")
        logger.info("Courts portal smoke check passed.")
