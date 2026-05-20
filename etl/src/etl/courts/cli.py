import os
from typing import Annotated, Literal

import typer
from loguru import logger

from dashboard_utils.aws import make_boto3_session, make_s3_client
from etl.courts.extract import PortalBatchConfig
from etl.courts.pipeline import update_courts

app = typer.Typer(name="courts", help="Courts portal ETL.")


@app.command()
def update(
    dry_run: Annotated[
        bool,
        typer.Option(help="Do everything except write outputs."),
    ] = False,
    sample: Annotated[
        int | None,
        typer.Option(help="Sample this many incident numbers."),
    ] = None,
    log_freq: Annotated[
        int,
        typer.Option(help="Log every N portal requests."),
    ] = 10,
    seed: Annotated[
        int,
        typer.Option(help="Random seed for sampling."),
    ] = 42,
    debug: Annotated[
        bool,
        typer.Option(help="Verbose logging."),
    ] = False,
    errors: Annotated[
        Literal["ignore", "raise"],
        typer.Option(help="Error handling mode."),
    ] = "ignore",
    no_retry: Annotated[
        bool,
        typer.Option(
            "--no-retry",
            help="Disable retry mechanism (max_attempts=1) for debugging.",
        ),
    ] = False,
) -> None:
    """Run the courts portal scraper pipeline end-to-end.

    Seeds the SQS queue, launches Fargate workers, waits for completion,
    then writes courts flags to processed data.
    """
    s3 = make_s3_client()
    cfg = PortalBatchConfig(
        dry_run=dry_run,
        sample=sample,
        log_freq=log_freq,
        seed=seed,
        debug=debug,
        errors=errors,
        no_retry=no_retry,
    )
    update_courts(s3, cfg=cfg)
    logger.info("Courts flags updated.")


@app.command()
def submit(
    dry_run: Annotated[
        bool,
        typer.Option(help="Seed queue and write manifest, but don't launch ECS workers."),
    ] = False,
    sample: Annotated[
        int | None,
        typer.Option(help="Sample this many incident numbers."),
    ] = None,
    seed: Annotated[
        int,
        typer.Option(help="Random seed for sampling."),
    ] = 42,
) -> None:
    """Seed the SQS queue and launch Fargate workers. Exits immediately (non-blocking).

    Use `courts monitor` to wait for completion,
    then `courts aggregate` to collect results.
    """
    from etl.courts.batch.aws import (
        get_existing_incidents,
        launch_workers,
        make_run_id,
        seed_queue,
        write_run_manifest,
    )
    from etl.courts.config import ScraperConfig
    from etl.utils.storage import load_shootings_database

    config = ScraperConfig()
    session = make_boto3_session()
    s3 = session.client("s3")
    sqs = session.client("sqs")
    ecs = session.client("ecs")

    gdf = load_shootings_database()
    all_incidents = gdf["dc_key"].astype(str).unique().tolist()
    if sample is not None:
        import random as _random

        _random.seed(seed)
        all_incidents = _random.sample(all_incidents, min(sample, len(all_incidents)))

    existing = get_existing_incidents(s3, config)
    incidents = [inc for inc in all_incidents if inc not in existing]
    logger.info(
        f"{len(incidents)}/{len(all_incidents)} incidents missing results — seeding queue"
    )

    if not incidents:
        logger.info("All incidents already scraped. Nothing to do.")
        return

    run_id = make_run_id()
    logger.info(f"Run ID: {run_id}")

    seed_queue(sqs, config, incidents, run_id)
    write_run_manifest(s3, config, run_id, incidents, worker_count=config.ecs_task_count)

    if not dry_run:
        launch_workers(ecs, config, run_id)
    else:
        logger.info("dry_run=True: skipping ECS worker launch")


@app.command()
def worker() -> None:
    """Run the SQS worker loop (Fargate container entrypoint).

    Long-polls the queue, scrapes one incident per message, and writes
    per-incident results to S3. Handles SIGTERM for graceful shutdown.
    """
    from etl.courts.batch.scrape import run_worker
    from etl.courts.config import ScraperConfig

    config = ScraperConfig()
    run_id = os.environ.get("RUN_ID", "unknown")
    run_worker(config, run_id)


@app.command()
def monitor(
    run_id: Annotated[
        str | None,
        typer.Option(help="Run ID to finalize manifest when queue drains."),
    ] = None,
) -> None:
    """Poll the SQS queue until both visible and in-flight counts reach zero."""
    from etl.courts.batch.aws import monitor_until_empty
    from etl.courts.config import ScraperConfig

    config = ScraperConfig()
    session = make_boto3_session()
    sqs = session.client("sqs")
    s3 = session.client("s3") if run_id else None
    monitor_until_empty(sqs, config, s3=s3, run_id=run_id)


@app.command()
def aggregate() -> None:
    """Read all per-incident results from S3 and print a summary."""
    from etl.courts.batch.aggregate import aggregate_results
    from etl.courts.config import ScraperConfig

    config = ScraperConfig()
    s3 = make_s3_client()
    results = aggregate_results(s3, config)

    counts: dict[str, int] = {}
    for outcome in results.values():
        counts[outcome.status.value] = counts.get(outcome.status.value, 0) + 1

    total = len(results)
    logger.info(f"Total results: {total}")
    for status, count in sorted(counts.items()):
        pct = count / total * 100 if total else 0
        logger.info(f"  {status}: {count} ({pct:.1f}%)")


@app.command()
def snapshot() -> None:
    """Materialize all results/*.json into a Parquet snapshot on S3.

    Uses DuckDB to read the full results prefix in parallel and writes
    a summary Parquet (no nested results array) to
    {s3_scraper_prefix}/snapshots/courts_results.parquet.
    """
    from etl.courts.batch.aggregate import snapshot_to_parquet
    from etl.courts.config import ScraperConfig

    config = ScraperConfig()
    s3 = make_s3_client()
    dest = snapshot_to_parquet(s3, config)
    logger.info(f"Snapshot written to {dest}")


@app.command()
def diagnose(
    run_path: Annotated[
        str,
        typer.Argument(help="Path to run directory or merged audit directory."),
    ],
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Show detailed incident lists."),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON instead of formatted text."),
    ] = False,
    by_attempts: Annotated[
        int | None,
        typer.Option("--by-attempts", help="Output DC keys that took exactly N attempts."),
    ] = None,
    dc_key: Annotated[
        str | None,
        typer.Option("--dc-key", help="Look up audit record for a specific DC key."),
    ] = None,
    show_missing: Annotated[
        bool,
        typer.Option("--show-missing", help="Output DC keys that were never attempted."),
    ] = False,
) -> None:
    """Diagnose a scrape run and identify issues."""
    from etl.courts.verification.diagnose import run as diagnose_run

    diagnose_run(
        run_path=run_path,
        verbose=verbose,
        json_output=json_output,
        by_attempts=by_attempts,
        dc_key=dc_key,
        show_missing=show_missing,
    )
