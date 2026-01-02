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
from dashboard_utils.env import settings
from etl.courts.batch.aws import AWS
from etl.courts.portal.schema import PortalResult


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
    bucket: str = settings.AWS_BUCKET_NAME
    subfolder_prefix: str = "courts-scraper"
    exclude_known_cases: bool = False


def _upload_inputs_to_s3(
    s3: S3Client,
    df: pd.DataFrame,
    bucket: str,
    subfolder: str,
) -> str:
    """Write input values to S3 and return (input_key, output_prefix).

    Parameters
    ----------
    s3 : S3Client
        The S3 client to use for uploading.
    df : pd.DataFrame
        DataFrame of incident numbers to upload.
    bucket : str
        The S3 bucket to upload to.
    subfolder : str
        The S3 subfolder within the bucket to upload to.

    Returns
    -------
    str
        The S3 key of the uploaded CSV.
    """
    # The input key and output prefix
    input_key = f"{subfolder}/incident_numbers.csv"

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
    output_prefix: str,
) -> tuple[dict[str, list[PortalResult] | None], pd.DataFrame]:
    """Download scraping results from S3.

    This function downloads:
    1. The portal results JSON file.
    2. The echoed input CSV file.

    Parameters
    ----------
    s3 : S3Client
        The S3 client to use for downloading.
    output_prefix : str
        The S3 prefix where the results are stored.

    Returns
    -------
    tuple
        ``(parsed_results, input_df)`` where ``parsed_results`` is the dict of
        result lists and ``input_df`` is the echoed input DataFrame.
    """
    # Strip s3://bucket/ from prefix
    bucket, key_prefix = parse_s3_uri(output_prefix)

    # Get the results JSON
    # NOTE: this is a dict mapping dc_key to list of PortalResult dicts or None
    results = read_json(s3, bucket=bucket, key=f"{key_prefix}/portal_results.json")

    # Validate the results
    parsed_results: dict[str, list[PortalResult] | None] = {}
    for k, v in results.items():
        if v is None:
            parsed_results[k] = None
        else:
            parsed_results[k] = [PortalResult.model_validate(r) for r in v]

    # Get the echoed input CSV
    input_df = read_csv_df(
        s3,
        bucket=bucket,
        key=f"{key_prefix}/portal_input.csv",
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
) -> tuple[dict[str, list[PortalResult] | None], pd.DataFrame]:
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
    tuple[dict[str, list[PortalResult] | None], pd.DataFrame]
        ``(results, echoed_input)`` where ``results`` is a dictionary mapping incident numbers to
        lists of PortalResult objects (or None) and ``echoed_input`` is the echoed input DataFrame.
    """
    # Optional sample
    if cfg.sample is not None:
        incident_numbers = incident_numbers.sample(cfg.sample, random_state=cfg.seed)

    # Log how many to scrape
    logger.info(f"Scraping {len(incident_numbers)} incident numbers")

    # Upload the inputs to S3
    date_string = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")
    s3_subfolder = f"{cfg.subfolder_prefix}/{date_string}"
    input_filename = _upload_inputs_to_s3(
        s3,
        incident_numbers,
        cfg.bucket,
        s3_subfolder,
    )

    # The output folder where results will be stored
    output_folder = f"s3://{cfg.bucket}/{s3_subfolder}/results"

    # Log it
    logger.info(f"Uploaded incident numbers to {input_filename}")
    logger.info(f"Output will be saved to {output_folder}")

    # Submit the batch job
    aws = AWS(debug=cfg.debug)
    aws.submit_jobs(
        input_filename=input_filename,
        output_folder=output_folder,
        search_by=cfg.search_by,
        dry_run=cfg.dry_run,
        sample=cfg.sample,
        log_freq=cfg.log_freq,
        seed=cfg.seed,
        errors=cfg.errors,
        sleep=cfg.sleep,
        ntasks=cfg.ntasks,
        wait=True,
    )

    # Download the results from S3 and return them
    results, echoed_input = _download_results(s3, output_folder)
    return results, echoed_input
