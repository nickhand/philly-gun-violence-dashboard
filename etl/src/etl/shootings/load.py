"""Load/save helpers for shootings data."""

import geopandas as gpd
from loguru import logger
from mypy_boto3_s3.client import S3Client

from dashboard_utils.aws import upload_file
from dashboard_utils.env import settings
from dashboard_utils.paths import data_dir, get_processed_path

__all__ = ["write_shootings_dataset"]


def write_shootings_dataset(s3: S3Client, df: gpd.GeoDataFrame) -> None:
    """
    Persist the cleaned shootings dataset to disk and mirror to S3.

    Parameters
    ----------
    s3 : S3Client
        The S3 client to use for uploading the dataset.
    df : geopandas.GeoDataFrame
        Cleaned shootings data to save.
    """
    # Make sure local path exists
    shootings_path = get_processed_path("shootings")
    shootings_path.parent.mkdir(parents=True, exist_ok=True)

    # Save locally to GeoJSON
    df.to_file(shootings_path, driver="GeoJSON")
    logger.info(f"Wrote shootings dataset to {shootings_path}")

    # Key in s3 is relative to data_dir
    key = str(shootings_path.relative_to(data_dir()))

    # Mirror to s3
    upload_file(
        s3,
        shootings_path,
        bucket=settings.AWS_BUCKET_NAME,
        key=key,
        content_type="application/geo+json",
    )
