"""CLI command factory for aws-batch-scraper plugins."""

import csv
import json
import queue
import random
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, TypedDict

import typer
from loguru import logger
from mypy_boto3_ecs.client import ECSClient
from mypy_boto3_s3.client import S3Client

from aws_batch_scraper.config import (
    SubmitterConfig,
    WorkerConfig,
    require_github_repository,
    require_github_workflow_file,
)
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


class _SubmitPhase(StrEnum):
    """Durable-side-effect phase used to choose safe failure compensation."""

    LEASE_ACQUIRED = "lease-acquired"
    MANIFEST_WRITE_STARTED = "manifest-write-started"
    MANIFEST_WRITTEN = "manifest-written"
    QUEUE_SEED_STARTED = "queue-seed-started"
    QUEUE_SEEDED = "queue-seeded"
    WORKER_LAUNCH_UNKNOWN = "worker-launch-unknown"
    WORKERS_PARTIALLY_STARTED = "workers-partially-started"
    WORKERS_STARTED = "workers-started"
    MONITOR_STARTED = "monitor-started"


def _monitor_command(script_name: str, name: str, run_id: str) -> list[str]:
    """Build the coordinator command shared by normal and recovery handoffs."""
    return [
        script_name,
        name,
        "monitor",
        "--run-id",
        run_id,
    ]


def _record_submission_recovery(
    s3: S3Client,
    config: SubmitterConfig,
    run_id: str,
    phase: _SubmitPhase,
    error: Exception,
    *,
    task_arns: list[str] | None = None,
) -> None:
    """Keep durable evidence when submission cannot be safely compensated."""
    key = f"{config.s3_scraper_prefix}/runs/{run_id}/submission-recovery.json"
    record = {
        "run_id": run_id,
        "recorded_at": datetime.now(UTC).isoformat(),
        "phase": phase.value,
        "detail": str(error),
        "lease_action": "retained",
        "task_arns": task_arns or [],
    }
    try:
        s3.put_object(
            Bucket=config.s3_bucket,
            Key=key,
            Body=json.dumps(record, indent=2).encode(),
            ContentType="application/json",
        )
    except Exception:
        logger.exception(f"Could not persist submission recovery evidence for {run_id}")
    logger.error(
        f"Submission for {run_id} failed during {phase.value}; retaining its active "
        "lease and run artifacts for recovery"
    )


def _handoff_partial_submission(
    s3: S3Client,
    ecs: ECSClient,
    config: SubmitterConfig,
    run_id: str,
    task_arns: list[str],
    monitor_command: list[str],
) -> None:
    """Persist live tasks and start a recovery monitor, preserving caller errors."""
    from aws_batch_scraper.orchestrate import launch_monitor, write_task_arns

    try:
        write_task_arns(s3, config, run_id, task_arns)
    except Exception:
        logger.exception(f"Could not persist all known worker task ARNs for failed run {run_id}")

    try:
        launch_monitor(
            ecs,
            config,
            run_id,
            monitor_command,
        )
    except Exception:
        logger.exception(
            f"Could not launch recovery monitor for {run_id}; the active lease and run "
            "manifest remain for manual recovery"
        )
        return

    logger.warning(
        f"Submission for {run_id} failed after {len(task_arns)} worker(s) started; "
        "a recovery monitor now owns terminal cleanup"
    )


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


def _resolve_run_id(
    run_id: str | None,
    latest: bool,
    s3: S3Client,
    config: WorkerConfig,
) -> str:
    """Resolve mutually exclusive explicit/latest run selection."""
    if run_id is None and not latest:
        raise typer.BadParameter("Provide a run ID or pass --latest.")
    if run_id is not None and latest:
        raise typer.BadParameter("Cannot pass both a run ID and --latest.")
    if latest:
        from aws_batch_scraper.stats import get_latest_run_id

        latest_run_id = get_latest_run_id(s3, config)
        logger.info(f"Latest run: {latest_run_id}")
        return latest_run_id
    if run_id is None:
        # Defensive runtime check kept explicit so `python -O` cannot erase it.
        raise typer.BadParameter("Provide a run ID or pass --latest.")
    return run_id


def create_cli(
    name: str,
    script_name: str,
    scraper_factory: Callable[[], Scraper],
    input_loader: Callable[[SubmitterConfig], list[WorkItem]],
    worker_config_class: type[WorkerConfig] = WorkerConfig,
    submitter_config_class: type[SubmitterConfig] = SubmitterConfig,
    minimum_full_run_interval: timedelta | None = None,
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
    minimum_full_run_interval
        Optional read-only guard interval for duplicate full submissions. Plugins
        enabling this policy expose an explicit ``--allow-recent-full-run`` bypass.

    Returns
    -------
    typer.Typer
        App pre-populated with: submit, worker, monitor, aggregate, run_stats,
        failures, bench. Call ``app.command()`` to add plugin-specific commands.
    """
    app = typer.Typer(name=name, help=f"{name.capitalize()} scraper ETL.")

    @app.command()
    def submit(
        dry_run: Annotated[
            bool,
            typer.Option(help="Preview selected work without mutating SQS, S3, or ECS."),
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
        allow_recent_full_run: Annotated[
            bool,
            typer.Option(
                "--allow-recent-full-run",
                help="Explicitly bypass the configured recent full-run guard.",
            ),
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
        if not dry_run and not wait and not monitor_in_ecs:
            raise typer.BadParameter("Use --wait or --monitor-in-ecs for terminal run ownership.")
        if allow_recent_full_run and minimum_full_run_interval is None:
            raise typer.BadParameter("This scraper does not configure a recent full-run guard.")

        from aws_batch_scraper.aws import make_boto3_session
        from aws_batch_scraper.ids import make_run_id
        from aws_batch_scraper.lease import acquire_run_lease
        from aws_batch_scraper.orchestrate import (
            WorkerLaunchError,
            launch_monitor,
            launch_workers,
            monitor_run,
            resolve_split_task_definitions,
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
        candidate_count = len(items)

        if sample is not None:
            selection_mode = "sample"
            random.seed(seed)
            items = random.sample(items, min(sample, len(items)))
        elif force:
            selection_mode = "full"
        else:
            selection_mode = "incremental"
        if allow_recent_full_run and selection_mode != "full":
            raise typer.BadParameter("--allow-recent-full-run is valid only for a full run.")

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

        if (
            selection_mode == "full"
            and minimum_full_run_interval is not None
            and not allow_recent_full_run
        ):
            from aws_batch_scraper.run_guard import find_full_run_suppression

            suppression = find_full_run_suppression(
                s3,
                config,
                current_candidate_count=candidate_count,
                minimum_interval=minimum_full_run_interval,
            )
            if suppression is not None:
                logger.info(
                    "Skipping duplicate full submission: {} run {} at {} already "
                    "covers this minimum interval. Use --allow-recent-full-run only "
                    "for an intentional override.",
                    suppression.reason,
                    suppression.run_id,
                    suppression.reference_at.isoformat(),
                )
                return

        worker_count = workers if workers is not None else config.ecs_task_count
        if not 1 <= worker_count <= 10:
            raise typer.BadParameter("Worker count must be between 1 and 10.")
        run_id = make_run_id()
        logger.info(f"Run ID: {run_id}")

        if dry_run:
            logger.info(
                f"Dry-run preview: would queue {len(items)} item(s) and launch "
                f"{worker_count} worker(s) for run {run_id}"
            )
            return

        # Validate both resolved definitions before the first durable mutation.
        # Launch helpers repeat this check to defend direct library callers and
        # post-validation config mutation.
        require_github_repository(config.github_repository)
        require_github_workflow_file(config.github_workflow_file)
        resolve_split_task_definitions(ecs, config)

        phase = _SubmitPhase.LEASE_ACQUIRED
        lease_acquired = False
        task_arns: list[str] = []
        launch_ambiguous = False
        monitor_started = False
        synchronous_monitor_started = False
        monitor_cmd = _monitor_command(script_name, name, run_id)
        try:
            acquire_run_lease(s3, config, run_id)
            lease_acquired = True
            phase = _SubmitPhase.MANIFEST_WRITE_STARTED
            write_run_manifest(
                s3,
                config,
                run_id,
                items,
                worker_count=worker_count,
                selection_mode=selection_mode,
                candidate_count=candidate_count,
            )
            phase = _SubmitPhase.MANIFEST_WRITTEN
            phase = _SubmitPhase.QUEUE_SEED_STARTED
            seeded_count = seed_queue(sqs, config, items, run_id, force_rescrape=force)
            if seeded_count != len(items):
                raise RuntimeError(f"SQS accepted only {seeded_count}/{len(items)} run message(s)")
            phase = _SubmitPhase.QUEUE_SEEDED
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
                task_arns = list(exc.launched_task_arns)
                launch_ambiguous = exc.launch_ambiguous
                if launch_ambiguous:
                    phase = _SubmitPhase.WORKER_LAUNCH_UNKNOWN
                elif task_arns:
                    phase = _SubmitPhase.WORKERS_PARTIALLY_STARTED
                raise
            if not task_arns:
                raise RuntimeError("ECS returned no worker tasks")
            phase = _SubmitPhase.WORKERS_STARTED
            write_task_arns(s3, config, run_id, task_arns)
            if monitor_in_ecs:
                launch_monitor(ecs, config, run_id, monitor_cmd)
                monitor_started = True
                phase = _SubmitPhase.MONITOR_STARTED

            if wait:
                synchronous_monitor_started = True
                monitor_run(ecs, sqs, s3, config, run_id)
        except Exception as exc:
            if not lease_acquired:
                raise
            if synchronous_monitor_started:
                # monitor_run owns terminal/recovery compensation after it starts.
                raise

            _record_submission_recovery(
                s3,
                config,
                run_id,
                phase,
                exc,
                task_arns=task_arns,
            )
            if task_arns and not monitor_started and not synchronous_monitor_started:
                _handoff_partial_submission(
                    s3,
                    ecs,
                    config,
                    run_id,
                    task_arns,
                    monitor_cmd,
                )
            raise

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
            require_github_repository(config.github_repository)
            require_github_workflow_file(config.github_workflow_file)
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
