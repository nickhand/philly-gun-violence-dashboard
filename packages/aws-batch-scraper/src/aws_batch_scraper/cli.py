"""CLI command factory for aws-batch-scraper plugins."""

import csv
import queue
import random
import threading
import time
from collections.abc import Callable
from typing import Annotated, TypedDict

import typer
from loguru import logger
from mypy_boto3_s3.client import S3Client

from aws_batch_scraper.config import SubmitterConfig, WorkerConfig
from aws_batch_scraper.types import Scraper, WorkItem


class BenchResult(TypedDict):
    """Single item timing row emitted by the local benchmark."""

    worker: int
    item_id: str
    status: str
    classification: str | None
    attempt_count: int
    elapsed_s: float
    error: str


def _bench_worker(
    worker_id: int,
    scraper_factory: Callable[[], Scraper],
    work_queue: "queue.Queue[WorkItem]",
    results: list[BenchResult],
    results_lock: threading.Lock,
    no_jitter: bool,
) -> None:
    scraper = scraper_factory()
    try:
        while True:
            try:
                item = work_queue.get_nowait()
            except queue.Empty:
                break
            t0 = time.perf_counter()
            try:
                result = scraper(item)
                elapsed = time.perf_counter() - t0
                row: BenchResult = {
                    "worker": worker_id,
                    "item_id": item.item_id,
                    "status": result.status.value,
                    "classification": result.classification or None,
                    "attempt_count": result.attempt_count,
                    "elapsed_s": round(elapsed, 3),
                    "error": result.error_message or "",
                }
                logger.info(
                    f"[w{worker_id}] {item.item_id}: {result.status.value} "
                    f"({result.classification}) in {elapsed:.2f}s"
                )
            except Exception as exc:
                elapsed = time.perf_counter() - t0
                row = {
                    "worker": worker_id,
                    "item_id": item.item_id,
                    "status": "error",
                    "classification": None,
                    "attempt_count": 0,
                    "elapsed_s": round(elapsed, 3),
                    "error": str(exc),
                }
                logger.warning(f"[w{worker_id}] {item.item_id}: exception in {elapsed:.2f}s: {exc}")
                scraper.reset()
            with results_lock:
                results.append(row)
            if not no_jitter:
                time.sleep(random.uniform(0.5, 1.5))
    finally:
        scraper.close()


def _run_bench(
    item_list: list[WorkItem],
    scraper_factory: Callable[[], Scraper],
    workers: int = 1,
    no_jitter: bool = False,
    output: str = "bench_results.csv",
) -> None:
    """Scrape items locally across N worker threads and write timing CSV."""
    logger.info(
        f"Benchmarking {len(item_list)} items across {workers} worker(s) (no_jitter={no_jitter})"
    )

    work_queue: queue.Queue[WorkItem] = queue.Queue()
    for item in item_list:
        work_queue.put(item)

    results: list[BenchResult] = []
    results_lock = threading.Lock()

    threads = [
        threading.Thread(
            target=_bench_worker,
            args=(i + 1, scraper_factory, work_queue, results, results_lock, no_jitter),
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
    actual_throughput = len(results) / wall_elapsed * 60

    logger.info(f"\n--- Benchmark results ({len(results)} items, {workers} worker(s)) ---")
    logger.info(
        f"  per-scrape: mean={mean_s:.2f}s  "
        f"min={min(elapsed_vals):.2f}s  max={max(elapsed_vals):.2f}s"
    )
    logger.info(f"  wall time: {wall_elapsed:.1f}s")
    logger.info(f"  actual throughput: {actual_throughput:.1f} items/min (all workers combined)")
    logger.info(f"  theoretical single-worker: {60 / mean_s:.1f} items/min")
    logger.info(
        f"  scaling efficiency: {actual_throughput / (60 / mean_s) / workers * 100:.0f}% of linear"
    )
    logger.info(f"  status breakdown: {status_counts}")
    logger.info(f"  CSV written to: {output}")


def create_cli(
    name: str,
    script_name: str,
    scraper_factory: Callable[[], Scraper],
    input_loader: Callable[[SubmitterConfig], list[WorkItem]],
    worker_config_class: type[WorkerConfig] = WorkerConfig,
    submitter_config_class: type[SubmitterConfig] = SubmitterConfig,
) -> typer.Typer:
    """Build a Typer app with generic scraper commands.

    Parameters
    ----------
    name
        CLI sub-command group name (e.g. ``"courts"``).
    script_name
        Entry-point script name used when building the ECS monitor command
        (e.g. ``"gv-dashboard-etl"``).
    scraper_factory
        Callable that returns a fresh ``Scraper`` instance.
    input_loader
        Callable that takes a ``SubmitterConfig`` and returns the list of
        ``WorkItem`` objects to scrape.
    worker_config_class
        Pydantic-settings class for worker/aggregate commands.
    submitter_config_class
        Pydantic-settings class for submit/monitor commands.

    Returns
    -------
    typer.Typer
        App pre-populated with: submit, worker, monitor, aggregate, run_stats,
        failures, bench. Call ``app.command()`` to add plugin-specific commands.
    """
    app = typer.Typer(name=name, help=f"{name.capitalize()} scraper ETL.")

    def _resolve_run_id(
        run_id: str | None,
        latest: bool,
        s3: S3Client,
        config: WorkerConfig,
    ) -> str:
        if run_id is None and not latest:
            raise typer.BadParameter("Provide a run ID or pass --latest.")
        if run_id is not None and latest:
            raise typer.BadParameter("Cannot pass both a run ID and --latest.")
        if latest:
            from aws_batch_scraper.stats import get_latest_run_id

            latest_run_id = get_latest_run_id(s3, config)
            logger.info(f"Latest run: {latest_run_id}")
            return latest_run_id

        # The first guard establishes this for the non-latest branch.
        assert run_id is not None
        return run_id

    @app.command()
    def submit(
        dry_run: Annotated[
            bool,
            typer.Option(help="Seed queue and write manifest, but don't launch ECS workers."),
        ] = False,
        sample: Annotated[
            int | None,
            typer.Option(help="Sample this many items."),
        ] = None,
        seed: Annotated[
            int,
            typer.Option(help="Random seed for sampling."),
        ] = 42,
        workers: Annotated[
            int | None,
            typer.Option(help="Number of Fargate workers to launch."),
        ] = None,
        force: Annotated[
            bool,
            typer.Option("--force", help="Re-scrape all items, including those already in S3."),
        ] = False,
        soft_blocked_delay: Annotated[
            int | None,
            typer.Option(help="Max soft-block requeue delay in seconds (default 900)."),
        ] = None,
        wait: Annotated[
            bool,
            typer.Option("--wait", help="Wait for launched ECS tasks to stop."),
        ] = False,
        monitor_in_ecs: Annotated[
            bool,
            typer.Option(
                "--monitor-in-ecs",
                help="Launch a Fargate monitor task and exit.",
            ),
        ] = False,
    ) -> None:
        """Seed the SQS queue and launch Fargate workers."""
        if wait and monitor_in_ecs:
            raise typer.BadParameter("Use either --wait or --monitor-in-ecs, not both.")

        from aws_batch_scraper.aws import make_boto3_session
        from aws_batch_scraper.ids import make_run_id
        from aws_batch_scraper.orchestrate import (
            WorkerLaunchError,
            launch_monitor,
            launch_workers,
            monitor_run,
            write_run_manifest,
            write_task_arns,
        )
        from aws_batch_scraper.queue import get_existing_items, seed_queue

        config = submitter_config_class()
        session = make_boto3_session(config=config)
        s3 = session.client("s3")
        sqs = session.client("sqs")
        ecs = session.client("ecs")

        items = input_loader(config)

        if sample is not None:
            random.seed(seed)
            items = random.sample(items, min(sample, len(items)))

        existing = get_existing_items(s3, config)
        if force:
            logger.info(
                f"--force: queuing all {len(items)} items "
                f"(ignoring {len(existing)} existing results)"
            )
        else:
            items = [it for it in items if it.item_id not in existing]
            logger.info(f"{len(items)} items missing results — seeding queue")

        if not items:
            logger.info("All items already scraped. Nothing to do.")
            return

        worker_count = workers if workers is not None else config.ecs_task_count
        run_id = make_run_id()
        logger.info(f"Run ID: {run_id}")

        seed_queue(sqs, config, items, run_id)
        write_run_manifest(s3, config, run_id, items, worker_count=worker_count)

        if not dry_run:
            try:
                task_arns = launch_workers(
                    ecs,
                    config,
                    run_id,
                    worker_count=worker_count,
                    force_rescrape=force,
                    soft_blocked_delay_max=soft_blocked_delay,
                )
            except WorkerLaunchError as exc:
                if exc.launched_task_arns:
                    write_task_arns(s3, config, run_id, exc.launched_task_arns)
                raise
            write_task_arns(s3, config, run_id, task_arns)
            if monitor_in_ecs:
                monitor_cmd = [
                    "uv",
                    "run",
                    script_name,
                    name,
                    "monitor",
                    "--run-id",
                    run_id,
                ]
                launch_monitor(ecs, config, run_id, monitor_cmd)
        else:
            logger.info("dry_run=True: skipping ECS worker launch")

        if wait and not dry_run:
            monitor_run(ecs, sqs, s3, config, run_id)

    @app.command()
    def worker() -> None:
        """Run the SQS worker loop (Fargate container entrypoint)."""
        from aws_batch_scraper.worker import run_worker

        config = worker_config_class()
        run_worker(scraper_factory, config)

    @app.command()
    def monitor(
        run_id: Annotated[
            str | None,
            typer.Option(help="Run ID to monitor."),
        ] = None,
        latest: Annotated[
            bool,
            typer.Option("--latest", help="Use the most recent run automatically."),
        ] = False,
    ) -> None:
        """Monitor a run until all workers stop."""
        from aws_batch_scraper.aws import make_boto3_session
        from aws_batch_scraper.orchestrate import monitor_run, monitor_until_empty

        config = submitter_config_class()
        session = make_boto3_session(config=config)
        sqs = session.client("sqs")
        s3 = session.client("s3")

        if run_id or latest:
            resolved = _resolve_run_id(run_id, latest, s3, config)
            ecs = session.client("ecs")
            monitor_run(ecs, sqs, s3, config, resolved)
        else:
            monitor_until_empty(sqs, config, s3=None, run_id=None)

    @app.command()
    def aggregate() -> None:
        """Read all per-item results from S3 and print a summary."""
        from aws_batch_scraper.aggregate import aggregate_results
        from aws_batch_scraper.aws import make_boto3_session

        config = worker_config_class()
        s3 = make_boto3_session(config=config).client("s3")
        results = aggregate_results(s3, config)

        counts: dict[str, int] = {}
        for result in results.values():
            counts[result.status.value] = counts.get(result.status.value, 0) + 1

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
        from aws_batch_scraper.aws import make_boto3_session
        from aws_batch_scraper.stats import print_run_stats

        config = worker_config_class()
        s3 = make_boto3_session(config=config).client("s3")
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
        """Print permanent failures for a run."""
        from aws_batch_scraper.aws import make_boto3_session
        from aws_batch_scraper.stats import print_failures

        config = worker_config_class()
        s3 = make_boto3_session(config=config).client("s3")
        resolved = _resolve_run_id(run_id, latest, s3, config)
        print_failures(s3, config, resolved)

    @app.command()
    def bench(
        sample: Annotated[
            int,
            typer.Option(help="Number of items to benchmark."),
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
        no_jitter: Annotated[
            bool,
            typer.Option("--no-jitter", help="Skip inter-item jitter."),
        ] = False,
    ) -> None:
        """Run the scraper locally on a sample of items and record per-item timing."""
        config = submitter_config_class()
        items = input_loader(config)
        random.seed(seed)
        sampled = random.sample(items, min(sample, len(items)))
        _run_bench(sampled, scraper_factory, workers=workers, no_jitter=no_jitter, output=output)

    return app
