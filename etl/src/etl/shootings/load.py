"""Load/save helpers for shootings data."""

import geopandas as gpd
from loguru import logger

from etl.utils.aws import mirror_to_s3
from etl.utils.paths import get_processed_path

__all__ = ["write_shootings_dataset"]


def write_shootings_dataset(df: gpd.GeoDataFrame) -> None:
    """
    Persist the cleaned shootings dataset to disk and mirror to S3.

    Parameters
    ----------
    df : geopandas.GeoDataFrame
        Cleaned shootings data to save.
    """
    shootings_path = get_processed_path("shootings")
    shootings_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_file(shootings_path, driver="GeoJSON")
    logger.info(f"Wrote shootings dataset to {shootings_path}")
    mirror_to_s3(shootings_path)
