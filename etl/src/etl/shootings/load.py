"""Load/save helpers for shootings data."""

import geopandas as gpd
from loguru import logger
from mypy_boto3_s3.client import S3Client

from dashboard_utils.processed import write_processed_geojson

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
    write_processed_geojson("shootings", df, s3=s3)
    logger.info("Wrote shootings dataset to S3")
