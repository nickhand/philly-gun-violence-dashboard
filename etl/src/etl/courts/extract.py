"""
Extraction helpers for courts portal scraping.

Uploads incident numbers to S3, triggers batch scraping, and fetches results.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import pandas as pd
from loguru import logger

from etl.config import settings
from etl.courts.batch.aws import AWS
from etl.courts.portal.schema import PortalResult
from etl.utils.aws import get_s3_client, open_csv_from_s3


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
        The S3 subfolder prefix to use; defaults to "courts/batch".
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
    subfolder_prefix: str = "courts/batch"
    exclude_known_cases: bool = False


def _upload_inputs_to_s3(
    df: pd.DataFrame,
    bucket: str,
    subfolder: str,
) -> tuple[str, str]:
    """Write input values to S3 and return (input_key, output_prefix).

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame of incident numbers to upload.
    bucket : str
        The S3 bucket to upload to.
    subfolder : str
        The S3 subfolder within the bucket to upload to.

    Returns
    -------
    tuple
        ``(input_key, output_prefix)`` where ``input_key`` is the S3 key of the uploaded CSV
        and ``output_prefix`` is the S3 prefix where results will be stored.
    """
    # The S3 client
    s3 = get_s3_client()

    # The input key and output prefix
    input_key = f"{subfolder}/incident_numbers.csv"
    output_prefix = f"s3://{bucket}/{subfolder}/results"

    # Upload CSV
    csv_bytes = df.to_csv(index=False, header=False).encode()
    s3.put_object(Bucket=bucket, Key=input_key, Body=csv_bytes)

    # Return S3 paths
    return f"s3://{bucket}/{input_key}", output_prefix


def _download_results(output_prefix: str) -> tuple[list[PortalResult], pd.DataFrame]:
    """Download scraping results from S3.

    This function downloads:
    1. The portal results JSON file.
    2. The echoed input CSV file.

    Parameters
    ----------
    output_prefix : str
        The S3 prefix where the results are stored.

    Returns
    -------
    tuple
        ``(results, input_df)`` where ``results`` is the list of result dicts and ``input_df``
        is the echoed input DataFrame.
    """
    # Create the S3 client
    s3 = get_s3_client()

    # Strip s3://bucket/ from prefix
    _, _, suffix = output_prefix.partition("s3://")
    bucket, _, key_prefix = suffix.partition("/")

    # Get the results object
    results_obj = s3.get_object(Bucket=bucket, Key=f"{key_prefix}/portal_results.json")
    results = [PortalResult.model_validate(r) for r in json.loads(results_obj["Body"].read())]

    # Get the echoed input CSV
    with open_csv_from_s3(s3, bucket=bucket, key=f"{key_prefix}/portal_input.csv") as f:
        input_df = pd.read_csv(
            f,
            header=None,
            names=["dc_key"],
            dtype={"dc_key": "str"},
        )

    return results, input_df


def extract_portal(
    incident_numbers: pd.DataFrame,
    cfg: PortalBatchConfig,
) -> tuple[list[PortalResult], pd.DataFrame]:
    """Run the portal scraper in batch and return results.

    Parameters
    ----------
    incident_numbers : pd.DataFrame
        DataFrame with a column ``dc_key`` of incident numbers to scrape.
    cfg : PortalBatchConfig
        Configuration for the batch scraping.

    Returns
    -------
    tuple[list[PortalResult], pd.DataFrame]
        ``(results, echoed_input)`` where ``results`` is the list of result dicts and
        ``echoed_input`` is the echoed input DataFrame.
    """
    # Optional sample
    if cfg.sample is not None:
        incident_numbers = incident_numbers.sample(cfg.sample, random_state=cfg.seed)

    logger.info(f"Scraping {len(incident_numbers)} incident numbers")

    # Upload the inputs to S3
    date_string = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")
    s3_subfolder = f"{cfg.subfolder_prefix}/{date_string}"
    input_filename, output_folder = _upload_inputs_to_s3(incident_numbers, cfg.bucket, s3_subfolder)

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
    results, echoed_input = _download_results(output_folder)
    return results, echoed_input
