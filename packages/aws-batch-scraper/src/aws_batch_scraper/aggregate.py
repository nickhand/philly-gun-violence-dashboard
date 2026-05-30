"""Aggregate per-item results from S3 into a combined dict."""

from concurrent.futures import ThreadPoolExecutor, as_completed

from loguru import logger
from mypy_boto3_s3.client import S3Client

from aws_batch_scraper.config import WorkerConfig
from aws_batch_scraper.types import ScrapeResult

_FETCH_WORKERS = 30


def aggregate_results(s3: S3Client, config: WorkerConfig) -> dict[str, ScrapeResult]:
    """Read all results/{item_id}.json from S3 and return as a dict.

    Uses a thread pool to fetch files concurrently — sequential fetches at
    ~50ms each would take ~12 minutes for 15k items.

    Returns
    -------
    dict[str, ScrapeResult]
        Mapping from item_id to ScrapeResult.
    """
    prefix = f"{config.s3_scraper_prefix}/results/"
    paginator = s3.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=config.s3_bucket, Prefix=prefix)

    keys: list[tuple[str, str]] = []
    for page in pages:
        for obj in page.get("Contents", []):
            key = obj["Key"]
            item_id = key.removeprefix(prefix).removesuffix(".json")
            if item_id:
                keys.append((item_id, key))

    logger.info(f"Fetching {len(keys)} result files from s3://{config.s3_bucket}/{prefix}")

    def _fetch(item_key: tuple[str, str]) -> tuple[str, ScrapeResult]:
        item_id, key = item_key
        body = s3.get_object(Bucket=config.s3_bucket, Key=key)["Body"].read()
        return item_id, ScrapeResult.model_validate_json(body)

    total = len(keys)
    results: dict[str, ScrapeResult] = {}
    errors = 0
    log_every = max(1, total // 10)
    with ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as pool:
        futures = {pool.submit(_fetch, ik): ik for ik in keys}
        for future in as_completed(futures):
            try:
                item_id, result = future.result()
                results[item_id] = result
            except Exception:
                errors += 1
                item_id, key = futures[future]
                logger.warning(f"Failed to fetch result for {item_id} ({key})")
            done = len(results) + errors
            if done % log_every == 0:
                logger.info(f"Fetched {done}/{total} results ({done / total * 100:.0f}%)")

    if errors:
        logger.warning(f"{errors} results failed to fetch and were skipped")
    logger.info(f"Aggregated {len(results)} results")
    return results
