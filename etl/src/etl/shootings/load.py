"""Load/save helpers for shootings data."""

import geopandas as gpd
from loguru import logger
from mypy_boto3_s3.client import S3Client

from dashboard_utils.aws import write_geojson_gdf
from dashboard_utils.env import settings
from dashboard_utils.paths import get_processed_key

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
    key = get_processed_key("shootings")
    write_geojson_gdf(s3, settings.AWS_BUCKET_NAME, key, df)
    logger.info(f"Wrote shootings dataset to s3://{settings.AWS_BUCKET_NAME}/{key}")
