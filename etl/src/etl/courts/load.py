"""Load/save helpers for courts portal scraping results."""

import pandas as pd
from mypy_boto3_s3.client import S3Client

from dashboard_utils.processed import read_processed_csv, write_processed_csv, write_processed_json
from etl.courts.scraper.schema import ScrapeOutcome

__all__ = ["read_existing_flags", "write_flags", "write_portal_results"]


def read_existing_flags(s3: S3Client | None = None) -> pd.DataFrame:
    """Read existing dc_key/has_court_case flags if present."""
    try:
        return read_processed_csv("courts_flags", s3=s3, dtype={"dc_key": str})
    except FileNotFoundError:
        return pd.DataFrame(columns=["dc_key", "has_court_case"])


def write_flags(s3: S3Client, df: pd.DataFrame) -> None:
    """Persist flags to CSV."""
    write_processed_csv("courts_flags", df, s3=s3)


def write_portal_results(s3: S3Client, portal_results: dict[str, ScrapeOutcome]) -> None:
    """Write aggregated portal results to processed/courts/portal_results.json."""
    result_dicts = {k: v.model_dump(mode="json") for k, v in portal_results.items()}
    write_processed_json("portal_results", result_dicts, s3=s3)
