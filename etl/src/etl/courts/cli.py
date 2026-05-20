import csv
import os
import queue as _queue
import random
import threading
import time
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

    Use `courts monitor` to wait for completion,
    then `courts aggregate` to collect results.
    By default, already-scraped incidents are skipped. Pass --force to re-scrape everything.
    """
    from etl.courts.batch.aws import (
        get_existing_incidents,
        launch_workers,
        make_run_id,
        seed_queue,
        write_run_manifest,
        write_task_arns,
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
    if force:
        incidents = all_incidents
        logger.info(f"--force: queuing all {len(incidents)} incidents (ignoring {len(existing)} existing results)")
    else:
        incidents = [inc for inc in all_incidents if inc not in existing]
        logger.info(
            f"{len(incidents)}/{len(all_incidents)} incidents missing results — seeding queue"
        )

    if not incidents:
        logger.info("All incidents already scraped. Nothing to do.")
        return

    worker_count = workers if workers is not None else config.ecs_task_count
    run_id = make_run_id()
    logger.info(f"Run ID: {run_id}")

    seed_queue(sqs, config, incidents, run_id)
    write_run_manifest(s3, config, run_id, incidents, worker_count=worker_count)

    if not dry_run:
        task_arns = launch_workers(
            ecs, config, run_id,
            worker_count=worker_count,
            force_rescrape=force,
            soft_blocked_delay_max=soft_blocked_delay,
        )
        write_task_arns(s3, config, run_id, task_arns)
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
        typer.Option(help="Run ID to monitor. Uses ECS task status as primary signal."),
    ] = None,
) -> None:
    """Monitor a run until all workers stop.

    When --run-id is provided, polls ECS task status for the specific tasks
    launched by that submit (primary signal), then finalizes the run manifest.
    Without --run-id, falls back to polling SQS queue depth.
    """
    from etl.courts.config import ScraperConfig

    config = ScraperConfig()
    session = make_boto3_session()
    sqs = session.client("sqs")
    s3 = session.client("s3")

    if run_id:
        from etl.courts.batch.aws import monitor_run
        ecs = session.client("ecs")
        monitor_run(ecs, sqs, s3, config, run_id)
    else:
        from etl.courts.batch.aws import monitor_until_empty
        monitor_until_empty(sqs, config, s3=None, run_id=None)


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
def run_stats(
    run_id: Annotated[str, typer.Argument(help="Run ID to report on.")],
) -> None:
    """Print throughput and timing stats for a completed run.

    Reads per-worker stats from runs/{run_id}/logs/ and per-scrape timing
    from a sample of results/ files written during that run.
    """
    import json
    import statistics

    from etl.courts.config import ScraperConfig

    config = ScraperConfig()
    s3 = make_s3_client()
    prefix = f"{config.s3_scraper_prefix}/runs/{run_id}/logs/"

    # --- Per-worker stats ---
    paginator = s3.get_paginator("list_objects_v2")
    worker_stats: list[dict] = []
    for page in paginator.paginate(Bucket=config.s3_bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            body = s3.get_object(Bucket=config.s3_bucket, Key=obj["Key"])["Body"].read()
            worker_stats.append(json.loads(body))

    if not worker_stats:
        logger.warning(f"No worker stats found under s3://{config.s3_bucket}/{prefix}")
        return

    total_incidents = sum(w.get("incidents_processed", 0) for w in worker_stats)
    total_soft_blocked = sum(w.get("soft_blocked_count", 0) for w in worker_stats)
    total_failures = sum(w.get("permanent_failure_count", 0) for w in worker_stats)
    ipm_values = [w["incidents_per_minute"] for w in worker_stats if w.get("incidents_per_minute")]

    logger.info(f"\n=== Run stats: {run_id} ===")
    logger.info(f"Workers: {len(worker_stats)}")
    logger.info(f"Total incidents processed: {total_incidents}")
    logger.info(f"Soft-blocked deferrals: {total_soft_blocked}")
    logger.info(f"Permanent failures: {total_failures}")
    if ipm_values:
        logger.info(f"Per-worker throughput: {[round(v, 1) for v in ipm_values]} incidents/min")
        logger.info(f"Combined throughput: {sum(ipm_values):.1f} incidents/min")

    # --- Per-scrape timing (from result files for this run's incidents) ---
    # Read input.jsonl to get the exact incidents for this run
    input_key = f"{config.s3_scraper_prefix}/runs/{run_id}/input.jsonl"
    try:
        body = s3.get_object(Bucket=config.s3_bucket, Key=input_key)["Body"].read()
        run_incidents = [json.loads(line)["incident_number"] for line in body.decode().splitlines() if line.strip()]
    except Exception as e:
        logger.warning(f"Could not read input.jsonl: {e}")
        run_incidents = []

    durations: list[float] = []
    if run_incidents:
        for incident in run_incidents[:200]:  # cap at 200 for speed
            result_key = f"{config.s3_scraper_prefix}/results/{incident}.json"
            try:
                body = s3.get_object(Bucket=config.s3_bucket, Key=result_key)["Body"].read()
                rec = json.loads(body)
                if rec.get("scrape_duration_s") is not None:
                    durations.append(rec["scrape_duration_s"])
            except Exception:
                pass

    if durations:
        logger.info(f"\nPer-scrape timing ({len(durations)} samples):")
        logger.info(f"  mean: {statistics.mean(durations):.2f}s")
        logger.info(f"  median: {statistics.median(durations):.2f}s")
        logger.info(f"  p95: {sorted(durations)[int(len(durations)*0.95)]:.2f}s")
        logger.info(f"  min: {min(durations):.2f}s  max: {max(durations):.2f}s")
    else:
        logger.info("\nNo scrape_duration_s found (run predates timing instrumentation).")


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


def _bench_worker(
    worker_id: int,
    work_queue: "_queue.Queue[str]",
    results: list[dict],
    results_lock: threading.Lock,
    no_jitter: bool,
) -> None:
    """Single benchmark worker thread: pulls incidents from shared queue and times each scrape."""
    from etl.courts.scraper.core import UJSPortalScraper
    from etl.courts.scraper.schema import SoftBlocked

    scraper = UJSPortalScraper(max_attempts=8, enable_screenshots=False, errors="ignore")
    try:
        while True:
            try:
                incident = work_queue.get_nowait()
            except _queue.Empty:
                break
            t0 = time.perf_counter()
            try:
                outcome = scraper(incident)
                elapsed = time.perf_counter() - t0
                row = {
                    "worker": worker_id,
                    "incident": incident,
                    "status": outcome.status.value,
                    "classification": outcome.classification,
                    "attempt_count": outcome.attempt_count,
                    "elapsed_s": round(elapsed, 3),
                    "error": "",
                }
                logger.info(
                    f"[w{worker_id}] {incident}: {outcome.status.value} "
                    f"({outcome.classification}) in {elapsed:.2f}s"
                )
            except SoftBlocked:
                elapsed = time.perf_counter() - t0
                row = {
                    "worker": worker_id,
                    "incident": incident,
                    "status": "soft_blocked",
                    "classification": "SOFT_BLOCKED",
                    "attempt_count": 2,
                    "elapsed_s": round(elapsed, 3),
                    "error": "SoftBlocked",
                }
                logger.warning(f"[w{worker_id}] {incident}: SOFT_BLOCKED in {elapsed:.2f}s")
                scraper._reset_page()
            with results_lock:
                results.append(row)
            if not no_jitter:
                time.sleep(random.uniform(0.5, 1.5))
    finally:
        scraper.close()


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
    if incidents:
        incident_list = [inc.strip() for inc in incidents.split(",") if inc.strip()]
    else:
        from etl.utils.storage import load_shootings_database

        gdf = load_shootings_database()
        all_incidents = gdf["dc_key"].astype(str).unique().tolist()
        random.seed(seed)
        incident_list = random.sample(all_incidents, min(sample, len(all_incidents)))

    logger.info(
        f"Benchmarking {len(incident_list)} incidents across {workers} worker(s) "
        f"(no_jitter={no_jitter})"
    )

    work_queue: _queue.Queue[str] = _queue.Queue()
    for inc in incident_list:
        work_queue.put(inc)

    results: list[dict] = []
    results_lock = threading.Lock()

    threads = [
        threading.Thread(
            target=_bench_worker,
            args=(i + 1, work_queue, results, results_lock, no_jitter),
            daemon=True,
        )
        for i in range(workers)
    ]

    wall_start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall_elapsed = time.perf_counter() - wall_start

    if not results:
        logger.warning("No results recorded.")
        return

    with open(output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    elapsed_vals = [r["elapsed_s"] for r in results]
    status_counts: dict[str, int] = {}
    for r in results:
        status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1

    mean_s = sum(elapsed_vals) / len(elapsed_vals)
    actual_throughput = len(results) / wall_elapsed * 60  # wall-clock incidents/min

    logger.info(f"\n--- Benchmark results ({len(results)} incidents, {workers} worker(s)) ---")
    logger.info(f"  per-scrape: mean={mean_s:.2f}s  min={min(elapsed_vals):.2f}s  max={max(elapsed_vals):.2f}s")
    logger.info(f"  wall time: {wall_elapsed:.1f}s")
    logger.info(f"  actual throughput: {actual_throughput:.1f} incidents/min (all workers combined)")
    logger.info(f"  theoretical single-worker: {60/mean_s:.1f} incidents/min")
    logger.info(f"  scaling efficiency: {actual_throughput / (60/mean_s) / workers * 100:.0f}% of linear")
    logger.info(f"  status breakdown: {status_counts}")
    logger.info(f"  CSV written to: {output}")


