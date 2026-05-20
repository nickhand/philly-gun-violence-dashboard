"""Utilities for reading and writing processed data and metadata."""

from datetime import UTC, datetime
from typing import Any

import geopandas as gpd
import pandas as pd
from mypy_boto3_s3.client import S3Client

from dashboard_utils.aws import make_s3_client, write_json
from dashboard_utils.config import get_s3_settings
from dashboard_utils.constants import REFERENCE_CRS
from dashboard_utils.processed import (
    read_processed_csv,
    read_processed_geojson,
)

__all__ = [
    "write_meta",
    "load_shootings_database",
    "load_street_blocks",
    "load_homicide_database",
    "load_courts_flags",
]


def write_meta(*, subfolder: str, data_through: Any = None) -> None:
    """Write data/processed/<subfolder>/meta.json with last_updated and data_through.

    Parameters
    ----------
    subfolder : str
        The subfolder under data/processed/ to write the meta.json file to.
    data_through : Any, optional
        The date through which the data is valid. If None, uses the current date.
    """
    # Build the meta dict
    now = datetime.now(UTC)
    data_through_iso = (
        pd.to_datetime(data_through).date().isoformat()
        if data_through is not None
        else pd.Timestamp(now).date().isoformat()
    )
    meta = {"last_updated": now.isoformat(), "data_through": data_through_iso}

    s3 = make_s3_client()
    write_json(
        s3,
        get_s3_settings().s3_bucket,
        f"processed/{subfolder}/meta.json",
        meta,
        indent=2,
    )


# -----------------------------------------------------------------------------
# Processed data loaders
# -----------------------------------------------------------------------------


def _client(s3: S3Client | None) -> S3Client:
    return s3 or make_s3_client()


def load_shootings_database(*, s3: S3Client | None = None) -> gpd.GeoDataFrame:
    """Load the shootings database GeoDataFrame from s3.

    Data is stored in S3 as EPSG:4326 (WGS84) for web mapping,
    but converted to REFERENCE_CRS (EPSG:2272) for ETL spatial operations.
    """
    gdf = read_processed_geojson("shootings", s3=_client(s3))
    return gdf.to_crs(REFERENCE_CRS)


def load_street_blocks(*, s3: S3Client | None = None) -> gpd.GeoDataFrame:
    """Load the street blocks GeoDataFrame.

    Data is stored in S3 as EPSG:4326 (WGS84) for web mapping,
    but converted to REFERENCE_CRS (EPSG:2272) for ETL spatial operations.
    """
    gdf = read_processed_geojson("street_blocks", s3=_client(s3))
    return gdf.to_crs(REFERENCE_CRS)


def load_homicide_database(*, s3: S3Client | None = None) -> pd.DataFrame:
    """Load the daily homicide database DataFrame."""
    df = read_processed_csv("homicides_daily", s3=_client(s3), parse_dates=["date"])
    return df.sort_values("date")


def load_courts_flags(*, s3: S3Client | None = None) -> pd.DataFrame:
    """Load the courts flags DataFrame."""
    return read_processed_csv("courts_flags", s3=_client(s3), dtype={"dc_key": str})
