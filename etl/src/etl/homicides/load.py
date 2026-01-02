"""Load/save helpers for homicide statistics."""

import pandas as pd
from mypy_boto3_s3.client import S3Client

from dashboard_utils.aws import upload_file
from dashboard_utils.env import settings
from dashboard_utils.paths import data_dir, get_processed_path

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
    # Make sure local path exists
    database_path = get_processed_path("homicides_daily")
    database_path.parent.mkdir(parents=True, exist_ok=True)

    # Clean duplicates and write to CSV locally
    cleaned = database.drop_duplicates(subset=["date"], keep="last")
    cleaned.to_csv(database_path, index=False)

    # Key in s3 is relative to data_dir
    key = str(database_path.relative_to(data_dir()))

    # Mirror to s3
    upload_file(
        s3,
        database_path,
        bucket=settings.AWS_BUCKET_NAME,
        key=key,
        content_type="text/csv",
    )


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
    # Make sure local path exists
    totals_path = get_processed_path("homicides_totals")
    totals_path.parent.mkdir(parents=True, exist_ok=True)

    # Write to JSON locally
    merged_totals.set_index("year").to_json(totals_path, orient="index")

    # Key in s3 is relative to data_dir
    key = str(totals_path.relative_to(data_dir()))

    # Mirror to s3
    upload_file(
        s3,
        totals_path,
        bucket=settings.AWS_BUCKET_NAME,
        key=key,
        content_type="application/json",
    )
