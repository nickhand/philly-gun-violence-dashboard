"""Aggregator: collect per-incident results from S3 into a combined dict."""

from concurrent.futures import ThreadPoolExecutor, as_completed

from loguru import logger
from mypy_boto3_s3.client import S3Client

from etl.courts.config import WorkerConfig
from etl.courts.scraper.schema import ScrapeOutcome

_FETCH_WORKERS = 30


def aggregate_results(s3: S3Client, config: WorkerConfig) -> dict[str, ScrapeOutcome]:
    """Read all results/{incident}.json from S3 and return as a dict.

    Uses a thread pool to fetch files concurrently — sequential fetches at
    ~50ms each would take ~12 minutes for 15k incidents.

    Returns
    -------
    dict[str, ScrapeOutcome]
        Mapping from incident number to ScrapeOutcome.
    """
    prefix = f"{config.s3_scraper_prefix}/results/"
    paginator = s3.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=config.s3_bucket, Prefix=prefix)

    keys: list[tuple[str, str]] = []
    for page in pages:
        for obj in page.get("Contents", []):
            key = obj["Key"]
            incident = key.removeprefix(prefix).removesuffix(".json")
            if incident:
                keys.append((incident, key))

    logger.info(f"Fetching {len(keys)} result files from s3://{config.s3_bucket}/{prefix}")

    def _fetch(incident_key: tuple[str, str]) -> tuple[str, ScrapeOutcome]:
        incident, key = incident_key
        body = s3.get_object(Bucket=config.s3_bucket, Key=key)["Body"].read()
        return incident, ScrapeOutcome.model_validate_json(body)

    total = len(keys)
    results: dict[str, ScrapeOutcome] = {}
    errors = 0
    log_every = max(1, total // 10)
    with ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as pool:
        futures = {pool.submit(_fetch, ik): ik for ik in keys}
        for future in as_completed(futures):
            try:
                incident, outcome = future.result()
                results[incident] = outcome
            except Exception:
                errors += 1
                incident, key = futures[future]
                logger.warning(f"Failed to fetch result for {incident} ({key})")
            done = len(results) + errors
            if done % log_every == 0:
                logger.info(f"Fetched {done}/{total} results ({done/total*100:.0f}%)")

    if errors:
        logger.warning(f"{errors} results failed to fetch and were skipped")
    logger.info(f"Aggregated {len(results)} results")
    return results


def snapshot_to_parquet(s3: S3Client, config: WorkerConfig) -> str:
    """Read all results/*.json via DuckDB and write a Parquet snapshot to S3.

    The snapshot contains per-incident summary columns (no nested results
    array) and is written to ``{s3_scraper_prefix}/snapshots/courts_results.parquet``.

    Returns
    -------
    str
        S3 URI of the written Parquet file.
    """
    import duckdb

    from dashboard_utils.aws import make_boto3_session

    session = make_boto3_session()
    creds = session.get_credentials().get_frozen_credentials()

    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute(f"SET s3_region='{config.aws_region}';")
    con.execute(f"SET s3_access_key_id='{creds.access_key}';")
    con.execute(f"SET s3_secret_access_key='{creds.secret_key}';")
    if creds.token:
        con.execute(f"SET s3_session_token='{creds.token}';")

    src = f"s3://{config.s3_bucket}/{config.s3_scraper_prefix}/results/*.json"
    dest = f"s3://{config.s3_bucket}/{config.s3_scraper_prefix}/snapshots/courts_results.parquet"

    con.execute(f"""
        COPY (
            SELECT
                regexp_extract(filename, '/results/([^/]+)\\.json$', 1) AS dc_key,
                status,
                classification,
                subreason,
                attempt_count,
                scraped_at::TIMESTAMPTZ AS scraped_at,
                run_id,
                CASE WHEN results IS NOT NULL THEN len(results) ELSE 0 END AS result_count
            FROM read_json_auto('{src}', filename=true, union_by_name=true)
        ) TO '{dest}' (FORMAT PARQUET, COMPRESSION 'zstd')
    """)

    logger.info(f"Snapshot written to {dest}")
    return dest
