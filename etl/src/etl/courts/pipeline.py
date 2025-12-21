"""Orchestration for scraping courts data from the PA UJS portal."""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import find_dotenv, load_dotenv
from loguru import logger
from s3fs import S3FileSystem

from etl.courts.batch.aws import AWS
from etl.courts.batch.scrape import scrape
from etl.utils.paths import data_dir

BUCKET_NAME = "phl-gun-violence-data"  # adjust if needed
DATA_DIR = data_dir()

# Where merged scraped results are saved locally
DATA_PATH = DATA_DIR / "processed" / "scraped_courts_data.csv"

__all__ = ["run", "merge"]


def _upload_inputs_to_s3(df: pd.DataFrame, bucket: str, subfolder: str) -> tuple[str, str]:
    """Write input values to S3 and return (input_key, output_prefix)."""
    s3 = S3FileSystem()
    input_key = f"s3://{bucket}/{subfolder}/incident_numbers.csv"
    output_prefix = f"s3://{bucket}/{subfolder}/results"

    with s3.open(input_key, "w") as f:
        df.to_csv(f, header=None, index=False)

    return input_key, output_prefix


def run(
    data: pd.DataFrame,
    dry_run: bool = False,
    sample: int | None = None,
    log_freq: int = 10,
    seed: int = 42,
    sleep: int = 2,
    ntasks: int = 10,
    debug: bool = False,
) -> pd.DataFrame:
    """
    Run the courts portal scraper for incident numbers.

    Parameters
    ----------
    data : pandas.DataFrame
        Input data with a ``dc_key`` column.
    dry_run : bool, optional
        If True, run without writing outputs.
    sample : int, optional
        Randomly sample this many incident numbers before scraping.
    log_freq : int, optional
        Log every N requests inside the scraper.
    seed : int, optional
        Random seed for sampling.
    sleep : int, optional
        Delay between requests in the portal scraper.
    ntasks : int, optional
        Number of parallel tasks to launch via ECS.
    debug : bool, optional
        Verbose logging.
    """
    load_dotenv(find_dotenv())

    # Unique incident numbers
    incident_numbers = data[["dc_key"]].drop_duplicates()

    # Drop ones we already have marked as having a court case
    if DATA_PATH.exists():
        existing = pd.read_csv(DATA_PATH, dtype={"dc_key": str})
        known_cases = existing[existing["has_court_case"] == True]
        incident_numbers = incident_numbers[
            ~incident_numbers["dc_key"].isin(known_cases["dc_key"])
        ]

    # Optional sample
    if sample is not None:
        incident_numbers = incident_numbers.sample(sample, random_state=seed)

    logger.info("Scraping %d incident numbers", len(incident_numbers))

    # Upload inputs
    date_string = datetime.today().strftime("%y-%m-%d %H_%M_%S")
    s3_subfolder = f"courts-data/{date_string}"
    input_filename, output_folder = _upload_inputs_to_s3(
        incident_numbers, BUCKET_NAME, s3_subfolder
    )
    logger.info("Uploaded incident numbers to %s", input_filename)
    logger.info("Output will be saved to %s", output_folder)

    # Invoke batch scrape via ECS
    aws = AWS(debug=debug)
    aws.submit_jobs(
        input_filename=input_filename,
        output_folder=output_folder,
        search_by="Incident Number",
        dry_run=dry_run,
        sample=sample,
        log_freq=log_freq,
        seed=seed,
        errors="ignore",
        sleep=sleep,
        ntasks=ntasks,
        wait=True,
    )

    # Invalidate cache and pull results
    s3 = S3FileSystem()
    s3.invalidate_cache()
    with s3.open(f"{output_folder}/portal_results.json", "r") as f:
        results = json.load(f)
    with s3.open(f"{output_folder}/portal_input.csv", "r") as f:
        output = pd.read_csv(f, header=None, names=["dc_key"], dtype=str)

    # Extract dc_numbers from results
    dc_numbers_with_cases = (
        pd.DataFrame(
            {"dc_key": ["20" + rr["dc_number"] for r in results for rr in r]}, dtype=str
        )
        .drop_duplicates()
        .assign(has_court_case=True)
    )

    # Merge and persist locally
    output = output.merge(dc_numbers_with_cases, on="dc_key", how="left").assign(
        has_court_case=lambda df: df.has_court_case.fillna(False)
    )
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(DATA_PATH, index=False)
    return output


def merge(data: pd.DataFrame, debug: bool = False) -> pd.DataFrame:
    """Merge courts data into an existing dataframe by dc_key."""
    if not DATA_PATH.exists():
        if debug:
            logger.debug("No existing courts data at %s", DATA_PATH)
        data["has_court_case"] = False
        return data

    existing = pd.read_csv(DATA_PATH, dtype={"dc_key": str})
    if debug:
        logger.debug("Merging in court case information")
    return data.merge(existing, on="dc_key", how="left").assign(
        has_court_case=lambda df: df["has_court_case"].fillna(False)
    )
