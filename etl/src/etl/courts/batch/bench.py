"""Local benchmark runner: scrape a sample of incidents and record per-incident timing."""

import csv
import queue
import random
import threading
import time

from loguru import logger


def _bench_worker(
    worker_id: int,
    work_queue: "queue.Queue[str]",
    results: list[dict],
    results_lock: threading.Lock,
    no_jitter: bool,
) -> None:
    from etl.courts.scraper.core import UJSPortalScraper
    from etl.courts.scraper.schema import SoftBlocked

    scraper = UJSPortalScraper(max_attempts=8, errors="ignore")
    try:
        while True:
            try:
                incident = work_queue.get_nowait()
            except queue.Empty:
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


def run_bench(
    incident_list: list[str],
    workers: int = 1,
    no_jitter: bool = False,
    output: str = "bench_results.csv",
) -> None:
    """Scrape incidents locally across N worker threads and write timing CSV."""
    logger.info(
        f"Benchmarking {len(incident_list)} incidents across {workers} worker(s) "
        f"(no_jitter={no_jitter})"
    )

    work_queue: queue.Queue[str] = queue.Queue()
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
    actual_throughput = len(results) / wall_elapsed * 60

    logger.info(f"\n--- Benchmark results ({len(results)} incidents, {workers} worker(s)) ---")
    logger.info(f"  per-scrape: mean={mean_s:.2f}s  min={min(elapsed_vals):.2f}s  max={max(elapsed_vals):.2f}s")
    logger.info(f"  wall time: {wall_elapsed:.1f}s")
    logger.info(f"  actual throughput: {actual_throughput:.1f} incidents/min (all workers combined)")
    logger.info(f"  theoretical single-worker: {60/mean_s:.1f} incidents/min")
    logger.info(f"  scaling efficiency: {actual_throughput / (60/mean_s) / workers * 100:.0f}% of linear")
    logger.info(f"  status breakdown: {status_counts}")
    logger.info(f"  CSV written to: {output}")
