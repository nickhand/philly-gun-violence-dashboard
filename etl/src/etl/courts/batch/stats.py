"""Run throughput and timing stats for a completed scrape run."""

import json
import statistics

from loguru import logger
from mypy_boto3_s3.client import S3Client

from etl.courts.config import WorkerConfig


def get_latest_run_id(s3: S3Client, config: WorkerConfig) -> str:
    """Return the run_id of the most recently submitted run.

    Run IDs use ISO timestamp prefixes so lexicographic sort gives chronological order.
    """
    prefix = f"{config.s3_scraper_prefix}/runs/"
    paginator = s3.get_paginator("list_objects_v2")

    run_ids: list[str] = []
    for page in paginator.paginate(Bucket=config.s3_bucket, Prefix=prefix, Delimiter="/"):
        for cp in page.get("CommonPrefixes", []):
            # cp["Prefix"] looks like "ujs-scraper/runs/2026-05-19T143022Z-a3f1/"
            run_id = cp["Prefix"].removeprefix(prefix).rstrip("/")
            if run_id:
                run_ids.append(run_id)

    if not run_ids:
        raise ValueError(f"No runs found under s3://{config.s3_bucket}/{prefix}")

    return sorted(run_ids)[-1]


def print_failures(s3: S3Client, config: WorkerConfig, run_id: str) -> None:
    """Print all permanent failures for a run."""
    prefix = f"{config.s3_scraper_prefix}/runs/{run_id}/failures/"
    paginator = s3.get_paginator("list_objects_v2")

    failures: list[dict] = []
    for page in paginator.paginate(Bucket=config.s3_bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key_incident = obj["Key"].removeprefix(prefix).removesuffix(".json")
            body = s3.get_object(Bucket=config.s3_bucket, Key=obj["Key"])["Body"].read()
            try:
                rec = json.loads(body)
                # Fall back to the S3 key filename when the JSON field is None
                if not rec.get("incident_number"):
                    rec["incident_number"] = key_incident
                failures.append(rec)
            except Exception:
                failures.append({"incident_number": key_incident, "error": "could not parse JSON"})

    if not failures:
        logger.info(f"No failures found for run {run_id}")
        return

    logger.info(f"\n=== Failures for run {run_id} ({len(failures)} total) ===")
    for f in sorted(failures, key=lambda x: x.get("incident_number", "")):
        incident = f.get("incident_number", "?")
        classification = f.get("classification", "?")
        subreason = f.get("subreason", "")
        logger.info(f"  {incident}  {classification}  {subreason}")


def print_run_stats(s3: S3Client, config: WorkerConfig, run_id: str) -> None:
    """Print per-worker throughput and per-scrape timing for a completed run."""
    prefix = f"{config.s3_scraper_prefix}/runs/{run_id}/logs/"
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

    input_key = f"{config.s3_scraper_prefix}/runs/{run_id}/input.jsonl"
    try:
        body = s3.get_object(Bucket=config.s3_bucket, Key=input_key)["Body"].read()
        run_incidents = [
            json.loads(line)["incident_number"]
            for line in body.decode().splitlines()
            if line.strip()
        ]
    except Exception as e:
        logger.warning(f"Could not read input.jsonl: {e}")
        run_incidents = []

    durations: list[float] = []
    for incident in run_incidents[:200]:
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
