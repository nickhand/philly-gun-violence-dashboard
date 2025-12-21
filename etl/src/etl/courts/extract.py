"""
Extraction helpers for courts portal scraping.
Uploads incident numbers to S3, triggers batch scraping, and fetches results.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd
from loguru import logger
from s3fs import S3FileSystem

from etl.courts.batch.aws import AWS
from etl.utils.paths import data_dir


@dataclass
class PortalBatchConfig:
    search_by: str = "Incident Number"
    ntasks: int = 10
    sleep: int = 2
    log_freq: int = 10
    seed: int = 42
    errors: str = "ignore"
    dry_run: bool = False
    sample: int | None = None
    debug: bool = False
    bucket: str = "phl-gun-violence-data"
    subfolder_prefix: str = "courts-data"


def _upload_inputs_to_s3(df: pd.DataFrame, bucket: str, subfolder: str) -> tuple[str, str]:
    """Write input values to S3 and return (input_key, output_prefix)."""
    s3 = S3FileSystem()
    input_key = f"s3://{bucket}/{subfolder}/incident_numbers.csv"
    output_prefix = f"s3://{bucket}/{subfolder}/results"

    with s3.open(input_key, "w") as f:
        df.to_csv(f, header=None, index=False)

    return input_key, output_prefix


def _download_results(output_prefix: str) -> tuple[list[dict[str, Any]], pd.DataFrame]:
    """Download portal results and the echoed input CSV from S3."""
    s3 = S3FileSystem()
    s3.invalidate_cache()
    with s3.open(f"{output_prefix}/portal_results.json", "r") as f:
        results = json.load(f)
    with s3.open(f"{output_prefix}/portal_input.csv", "r") as f:
        input_df = pd.read_csv(f, header=None, names=["dc_key"], dtype=str)
    return results, input_df


def extract_portal(
    incident_numbers: pd.DataFrame,
    cfg: PortalBatchConfig,
) -> tuple[list[dict[str, Any]], pd.DataFrame]:
    """
    Run the portal scraper in batch and return (raw_results, input_df_echo).
    """
    # Optional sample
    if cfg.sample is not None:
        incident_numbers = incident_numbers.sample(cfg.sample, random_state=cfg.seed)

    logger.info("Scraping %d incident numbers", len(incident_numbers))

    date_string = datetime.today().strftime("%y-%m-%d %H_%M_%S")
    s3_subfolder = f"{cfg.subfolder_prefix}/{date_string}"
    input_filename, output_folder = _upload_inputs_to_s3(
        incident_numbers, cfg.bucket, s3_subfolder
    )

    logger.info("Uploaded incident numbers to %s", input_filename)
    logger.info("Output will be saved to %s", output_folder)

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

    results, echoed_input = _download_results(output_folder)
    return results, echoed_input
