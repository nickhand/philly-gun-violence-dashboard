import os
import random
from typing import Annotated

import typer
from loguru import logger

from dashboard_utils.aws import make_boto3_session, make_s3_client

app = typer.Typer(name="courts", help="Courts portal ETL.")


def _resolve_run_id(run_id: str | None, latest: bool, s3, config) -> str:
    """Validate and resolve run_id / --latest into a concrete run ID."""
    if run_id is None and not latest:
        raise typer.BadParameter("Provide a run ID or pass --latest.")
    if run_id is not None and latest:
        raise typer.BadParameter("Cannot pass both a run ID and --latest.")
    if latest:
        from etl.courts.batch.stats import get_latest_run_id
        run_id = get_latest_run_id(s3, config)
        logger.info(f"Latest run: {run_id}")
    return run_id  # type: ignore[return-value]


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
    workers: Annotated[
        int | None,
        typer.Option(help="Number of Fargate workers to launch (overrides ECS_TASK_COUNT default)."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Re-scrape all incidents, including those already in S3."),
    ] = False,
    soft_blocked_delay: Annotated[
        int | None,
        typer.Option(
            help="Max SOFT_BLOCKED requeue delay in seconds (default 900). Use a small value like 60 for benchmark runs.",
        ),
    ] = None,
) -> None:
    """Seed the SQS queue and launch Fargate workers. Exits immediately (non-blocking).

    Use `courts monitor` to wait for completion, then `courts process` to write flags.
    By default, already-scraped incidents are skipped. Pass --force to re-scrape everything.
    """
    from etl.courts.config import SubmitterConfig
    from etl.courts.extract import submit_run

    config = SubmitterConfig()
    session = make_boto3_session()
    submit_run(
        session.client("s3"),
        session.client("sqs"),
        session.client("ecs"),
        config,
        sample=sample,
        seed=seed,
        workers=workers,
        force=force,
        dry_run=dry_run,
        soft_blocked_delay=soft_blocked_delay,
    )


@app.command()
def worker() -> None:
    """Run the SQS worker loop (Fargate container entrypoint).

    Long-polls the queue, scrapes one incident per message, and writes
    per-incident results to S3. Handles SIGTERM for graceful shutdown.
    """
    from etl.courts.batch.scrape import run_worker
    from etl.courts.config import WorkerConfig

    config = WorkerConfig()
    run_id = os.environ.get("RUN_ID", "unknown")
    run_worker(config, run_id)


@app.command()
def monitor(
    run_id: Annotated[
        str | None,
        typer.Option(help="Run ID to monitor. Uses ECS task status as primary signal."),
    ] = None,
    latest: Annotated[
        bool,
        typer.Option("--latest", help="Use the most recent run automatically."),
    ] = False,
) -> None:
    """Monitor a run until all workers stop.

    When --run-id or --latest is provided, polls ECS task status for the specific tasks
    launched by that submit (primary signal), then finalizes the run manifest.
    Without either, falls back to polling SQS queue depth.
    """
    from etl.courts.config import SubmitterConfig

    config = SubmitterConfig()
    session = make_boto3_session()
    sqs = session.client("sqs")
    s3 = session.client("s3")

    if run_id or latest:
        resolved = _resolve_run_id(run_id, latest, s3, config)
        from etl.courts.batch.aws import monitor_run
        ecs = session.client("ecs")
        monitor_run(ecs, sqs, s3, config, resolved)
    else:
        from etl.courts.batch.aws import monitor_until_empty
        monitor_until_empty(sqs, config, s3=None, run_id=None)


@app.command()
def aggregate() -> None:
    """Read all per-incident results from S3 and print a summary."""
    from etl.courts.batch.aggregate import aggregate_results
    from etl.courts.config import WorkerConfig

    config = WorkerConfig()
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
def run_stats(
    run_id: Annotated[
        str | None,
        typer.Argument(help="Run ID to report on. Omit when using --latest."),
    ] = None,
    latest: Annotated[
        bool,
        typer.Option("--latest", help="Use the most recent run automatically."),
    ] = False,
) -> None:
    """Print throughput and timing stats for a completed run."""
    from etl.courts.batch.stats import print_run_stats
    from etl.courts.config import WorkerConfig

    config = WorkerConfig()
    s3 = make_s3_client()
    resolved = _resolve_run_id(run_id, latest, s3, config)
    print_run_stats(s3, config, resolved)


@app.command()
def failures(
    run_id: Annotated[
        str | None,
        typer.Argument(help="Run ID to inspect. Omit when using --latest."),
    ] = None,
    latest: Annotated[
        bool,
        typer.Option("--latest", help="Use the most recent run automatically."),
    ] = False,
) -> None:
    """Print permanent failures for a run.

    Pass a run ID directly, or use --latest to inspect the most recent run.
    """
    from etl.courts.batch.stats import print_failures
    from etl.courts.config import WorkerConfig

    config = WorkerConfig()
    s3 = make_s3_client()
    resolved = _resolve_run_id(run_id, latest, s3, config)
    print_failures(s3, config, resolved)


@app.command()
def snapshot() -> None:
    """Materialize all results/*.json into a Parquet snapshot on S3."""
    from etl.courts.batch.aggregate import snapshot_to_parquet
    from etl.courts.config import WorkerConfig

    config = WorkerConfig()
    s3 = make_s3_client()
    dest = snapshot_to_parquet(s3, config)
    logger.info(f"Snapshot written to {dest}")


@app.command()
def process() -> None:
    """Aggregate scraper results and write processed courts flags.

    Reads all results/*.json from S3, writes a Parquet snapshot,
    transforms to dc_key/has_court_case flags, and writes
    processed/scraped_courts_data.csv.
    """
    from etl.courts.config import WorkerConfig
    from etl.courts.pipeline import process_results

    config = WorkerConfig()
    s3 = make_s3_client()
    process_results(s3, config)


@app.command()
def bench(
    sample: Annotated[
        int,
        typer.Option(help="Number of incidents to benchmark."),
    ] = 20,
    workers: Annotated[
        int,
        typer.Option(help="Number of concurrent scraper workers."),
    ] = 1,
    seed: Annotated[
        int,
        typer.Option(help="Random seed for sampling."),
    ] = 42,
    output: Annotated[
        str,
        typer.Option(help="Path to write timing CSV."),
    ] = "bench_results.csv",
    incidents: Annotated[
        str | None,
        typer.Option(help="Comma-separated incident numbers to use instead of sampling."),
    ] = None,
    no_jitter: Annotated[
        bool,
        typer.Option("--no-jitter", help="Skip inter-incident jitter (faster, less realistic)."),
    ] = False,
) -> None:
    """Run the scraper locally on a sample of incidents and record per-incident timing.

    Bypasses SQS and ECS — scrapes directly and writes a CSV with elapsed time,
    status, and classification for each incident. Use --workers N to simulate
    concurrent workers (note: all share your local IP, unlike Fargate).
    """
    from etl.courts.batch.bench import run_bench

    if incidents:
        incident_list = [inc.strip() for inc in incidents.split(",") if inc.strip()]
    else:
        from etl.utils.storage import load_shootings_database

        gdf = load_shootings_database()
        all_incidents = gdf["dc_key"].astype(str).unique().tolist()
        random.seed(seed)
        incident_list = random.sample(all_incidents, min(sample, len(all_incidents)))

    run_bench(incident_list, workers=workers, no_jitter=no_jitter, output=output)
