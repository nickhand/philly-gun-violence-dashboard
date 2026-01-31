"""
Extraction helpers for courts portal scraping.

Uploads incident numbers to S3, triggers batch scraping, and fetches results.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import pandas as pd
from loguru import logger
from mypy_boto3_s3.client import S3Client

from dashboard_utils.aws import parse_s3_uri, read_csv_df, read_json, write_csv_df
from dashboard_utils.env import s3_settings
from etl.courts.batch.aws import AWS
from etl.courts.scraper.schema import ScrapeOutcome


@dataclass
class PortalBatchConfig:
    """Configuration for portal batch scraping.

    Attributes
    ----------
    search_by : str
        The field to search by; defaults to "Incident Number".
    ntasks : int
        Number of parallel tasks to run; defaults to 10.
    sleep : int
        Seconds to sleep between requests; defaults to 2.
    log_freq : int
        Frequency of logging progress; defaults to every 10 requests.
    seed : int
        Random seed for sampling; defaults to 42.
    errors : str
        Error handling strategy; defaults to "ignore".
    dry_run : bool
        If ``True``, do not actually submit jobs; defaults to ``False``.
    sample : int | None
        If set, randomly sample this many incident numbers to scrape.
    debug : bool
        If ``True``, run in debug mode; defaults to ``False``.
    bucket : str
        The S3 bucket to use; defaults to the configured AWS bucket name.
    subfolder_prefix : str
        The S3 subfolder prefix to use; defaults to "courts-scraper".
    exclude_known_cases : bool
        If ``True``, exclude incident numbers already known to have court cases.
    no_retry : bool
        If ``True``, disable retry mechanism (max_attempts=1) for debugging.
    screenshots : bool
        If ``True``, enable screenshots for failures; defaults to ``True``.
    """

    search_by: Literal["Incident Number", "Docket Number"] = "Incident Number"
    ntasks: int = 10
    sleep: int = 2
    log_freq: int = 10
    seed: int = 42
    errors: Literal["ignore", "raise"] = "ignore"
    dry_run: bool = False
    sample: int | None = None
    debug: bool = False
    bucket: str = s3_settings.AWS_BUCKET_NAME
    subfolder_prefix: str = "courts-scraper"
    exclude_known_cases: bool = False
    no_retry: bool = False
    screenshots: bool = True


def _upload_inputs_to_s3(
    s3: S3Client,
    df: pd.DataFrame,
    bucket: str,
    run_folder: str,
) -> str:
    """Write input values to S3 and return the S3 path.

    Parameters
    ----------
    s3 : S3Client
        The S3 client to use for uploading.
    df : pd.DataFrame
        DataFrame of incident numbers to upload.
    bucket : str
        The S3 bucket to upload to.
    run_folder : str
        The run folder path (e.g., 'courts-scraper/runs/{run_id}').

    Returns
    -------
    str
        The S3 URI of the uploaded CSV.
    """
    # The input key: {run_folder}/inputs/incident_numbers.csv
    input_key = f"{run_folder}/inputs/incident_numbers.csv"

    # Upload csv
    write_csv_df(
        s3,
        bucket=bucket,
        key=input_key,
        df=df,
        index=False,
        header=False,
    )

    # Return S3 path for input file
    return f"s3://{bucket}/{input_key}"


def _download_results(
    s3: S3Client,
    run_folder: str,
) -> tuple[dict[str, ScrapeOutcome], pd.DataFrame]:
    """Download scraping results from S3.

    This function downloads from the merged/ subfolder:
    1. The portal results JSON file.
    2. The echoed input CSV file.

    Parameters
    ----------
    s3 : S3Client
        The S3 client to use for downloading.
    run_folder : str
        The S3 URI to the run folder (e.g., 's3://bucket/courts-scraper/runs/{run_id}').

    Returns
    -------
    tuple
        ``(parsed_results, input_df)`` where ``parsed_results`` is a dict mapping
        incident numbers to ScrapeOutcome objects and ``input_df`` is the echoed
        input DataFrame.
    """
    # Strip s3://bucket/ from prefix
    bucket, key_prefix = parse_s3_uri(run_folder)
    merged_prefix = f"{key_prefix}/merged"

    # Get the results JSON
    # NOTE: this is a dict mapping dc_key to ScrapeOutcome dicts
    results = read_json(s3, bucket=bucket, key=f"{merged_prefix}/portal_results.json")

    # Validate the results as ScrapeOutcome objects
    parsed_results: dict[str, ScrapeOutcome] = {}
    for k, v in results.items():
        parsed_results[k] = ScrapeOutcome.model_validate(v)

    # Get the echoed input CSV
    input_df = read_csv_df(
        s3,
        bucket=bucket,
        key=f"{merged_prefix}/portal_input.csv",
        header=None,
        names=["dc_key"],
        dtype={"dc_key": "str"},
    )

    # Validate lengths match
    if len(input_df) != len(parsed_results):
        raise ValueError(
            "Number of echoed input rows does not match number of results "
            f"({len(input_df)} vs {len(parsed_results)})"
        )

    return parsed_results, input_df


def extract_portal(
    s3: S3Client,
    incident_numbers: pd.DataFrame,
    cfg: PortalBatchConfig,
) -> tuple[dict[str, ScrapeOutcome], pd.DataFrame]:
    """Run the portal scraper in batch and return results.

    Parameters
    ----------
    s3 : S3Client
        The S3 client to use for uploading inputs and downloading results.
    incident_numbers : pd.DataFrame
        DataFrame with a column ``dc_key`` of incident numbers to scrape.
    cfg : PortalBatchConfig
        Configuration for the batch scraping.

    Returns
    -------
    tuple[dict[str, ScrapeOutcome], pd.DataFrame]
        ``(results, echoed_input)`` where ``results`` is a dictionary mapping incident numbers to
        ScrapeOutcome objects and ``echoed_input`` is the echoed input DataFrame.
    """
    # Optional sample
    if cfg.sample is not None:
        incident_numbers = incident_numbers.sample(cfg.sample, random_state=cfg.seed)

    # Log how many to scrape
    logger.info(f"Scraping {len(incident_numbers)} incident numbers")

    # Upload the inputs to S3
    # Structure: courts-scraper/runs/{run_id}/inputs/incident_numbers.csv
    run_id = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")
    run_folder = f"{cfg.subfolder_prefix}/runs/{run_id}"
    input_filename = _upload_inputs_to_s3(
        s3,
        incident_numbers,
        cfg.bucket,
        run_folder,
    )

    # The shards folder where per-worker outputs will be stored
    # Structure: courts-scraper/runs/{run_id}/shards/
    shards_folder = f"s3://{cfg.bucket}/{run_folder}/shards"

    # Log it
    logger.info(f"Uploaded incident numbers to {input_filename}")
    logger.info(f"Shard outputs will be saved to {shards_folder}")

    # Submit the batch job
    aws = AWS(debug=cfg.debug)
    aws.submit_jobs(
        input_filename=input_filename,
        output_folder=shards_folder,
        search_by=cfg.search_by,
        dry_run=cfg.dry_run,
        sample=cfg.sample,
        log_freq=cfg.log_freq,
        seed=cfg.seed,
        errors=cfg.errors,
        sleep=cfg.sleep,
        ntasks=cfg.ntasks,
        wait=True,
        run_id=run_id,
        no_retry=cfg.no_retry,
        screenshots=cfg.screenshots,
    )

    # Download the results from S3 (from merged/ folder) and return them
    run_folder_uri = f"s3://{cfg.bucket}/{run_folder}"
    results, echoed_input = _download_results(s3, run_folder_uri)
    return results, echoed_input
