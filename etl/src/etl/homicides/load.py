"""Load/save helpers for homicide statistics."""

import pandas as pd
from mypy_boto3_s3.client import S3Client

from dashboard_utils.aws import write_csv_df, write_json
from dashboard_utils.env import settings
from dashboard_utils.paths import get_processed_key

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
    path : pathlib.Path or str, optional
        Output CSV path; defaults to the raw homicide totals path.
    """
    cleaned = database.drop_duplicates(subset=["date"], keep="last")
    key = get_processed_key("homicides_daily")
    write_csv_df(s3, settings.AWS_BUCKET_NAME, key, cleaned)


def write_processed_totals(s3: S3Client, merged_totals: pd.DataFrame) -> None:
    """
    Persist merged annual/YTD totals to JSON.

    Parameters
    ----------
    s3 : S3Client
        The S3 client to use for uploading the totals.
    merged_totals : pandas.DataFrame
        DataFrame with columns including ``year``.
    path : pathlib.Path or str, optional
        Output JSON path; defaults to the processed homicide totals path.
    """
    key = get_processed_key("homicides_totals")
    payload = merged_totals.set_index("year").to_dict(orient="index")
    write_json(s3, settings.AWS_BUCKET_NAME, key, payload)
