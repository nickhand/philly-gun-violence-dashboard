"""Load/save helpers for homicide statistics."""

import numpy as np
import pandas as pd
from mypy_boto3_s3.client import S3Client

from dashboard_utils.processed import write_processed_csv, write_processed_json

__all__ = ["write_homicide_database", "write_processed_totals"]


def write_homicide_database(s3: S3Client, database: pd.DataFrame) -> None:
    """
    Persist the homicide daily totals database.

    Parameters
    ----------
    s3 : S3Client
        The S3 client to use for uploading the database.
    database : pandas.DataFrame
        DataFrame with columns ``date`` and ``total``.
    """
    cleaned = database.drop_duplicates(subset=["date"], keep="last")
    write_processed_csv("homicides_daily", cleaned, s3=s3)


def write_processed_totals(s3: S3Client, merged_totals: pd.DataFrame) -> None:
    """
    Persist merged annual/YTD totals to JSON.

    Parameters
    ----------
    s3 : S3Client
        The S3 client to use for uploading the totals.
    merged_totals : pandas.DataFrame
        DataFrame with columns including ``year``.
    """
    payload = merged_totals.set_index("year").replace({np.nan: None}).to_dict(orient="index")
    write_processed_json("homicides_totals", payload, s3=s3)
