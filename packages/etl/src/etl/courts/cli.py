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
def snapshot() -> None:
    """Materialize all results/*.json into a Parquet snapshot on S3."""
    from aws_batch_scraper.aggregate import snapshot_to_parquet

    config = CourtsWorkerConfig()
    s3 = make_boto3_session(config=config).client("s3")
    dest = snapshot_to_parquet(s3, config)
    logger.info(f"Snapshot written to {dest}")


@app.command()
def process() -> None:
    """Aggregate scraper results and write processed courts flags.

    Reads all results/*.json from S3, transforms to dc_key/has_court_case flags,
    and writes processed/scraped_courts_data.csv plus portal_results.json.
    """
    from etl.courts.pipeline import process_results

    config = CourtsWorkerConfig()
    s3 = make_boto3_session(config=config).client("s3")
    process_results(s3, config)


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
        config = CourtsSubmitterConfig()
        session = make_boto3_session(config=config)
        session.client("sqs").get_queue_attributes(
            QueueUrl=config.sqs_queue_url,
            AttributeNames=["QueueArn"],
        )
        session.client("s3").head_bucket(Bucket=config.s3_bucket)
        session.client("ecs").describe_clusters(clusters=[config.ecs_cluster_name])
        session.client("ecs").describe_task_definition(
            taskDefinition=config.ecs_task_definition,
        )
        logger.info("Courts AWS smoke checks passed.")

    if not skip_portal:
        with UJSPortalScraper(max_attempts=1, errors="ignore") as scraper:
            if scraper.page is None:
                raise RuntimeError("UJS portal browser check did not create a page")
        logger.info("Courts portal smoke check passed.")
