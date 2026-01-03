"""Utilities for reading and writing processed data and metadata."""

from datetime import UTC, datetime
from typing import Any

import geopandas as gpd
import pandas as pd

from dashboard_utils.aws import make_s3_client, read_csv_df, read_geojson_gdf, read_json, write_json
from dashboard_utils.env import settings
from dashboard_utils.paths import get_processed_key

__all__ = [
    "write_meta",
    "load_shootings_database",
    "load_street_blocks",
    "load_homicide_database",
    "load_homicide_totals",
    "load_courts_flags",
]


def write_meta(*, subfolder: str, data_through: Any = None) -> None:
    """Write data/processed/<subfolder>/meta.json with last_updated and data_through.

    Parameters
    ----------
    s3 : S3Client
        The S3 client to use for uploading the meta.json file.
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
        settings.AWS_BUCKET_NAME,
        f"processed/{subfolder}/meta.json",
        meta,
        indent=2,
    )


# -----------------------------------------------------------------------------
# Processed data loaders
# -----------------------------------------------------------------------------


def load_shootings_database() -> gpd.GeoDataFrame:
    """Load the shootings database GeoDataFrame from s3."""
    s3 = make_s3_client()
    key = get_processed_key("shootings")
    return read_geojson_gdf(s3, bucket=settings.AWS_BUCKET_NAME, key=key)


def load_street_blocks() -> gpd.GeoDataFrame:
    """Load the street blocks GeoDataFrame."""
    s3 = make_s3_client()
    key = get_processed_key("street_blocks")
    return read_geojson_gdf(s3, bucket=settings.AWS_BUCKET_NAME, key=key)


def load_homicide_database() -> pd.DataFrame:
    """Load the daily homicide database DataFrame."""
    s3 = make_s3_client()
    key = get_processed_key("homicides_daily")
    df = read_csv_df(s3, bucket=settings.AWS_BUCKET_NAME, key=key, parse_dates=["date"])
    return df.sort_values("date")


def load_homicide_totals() -> pd.DataFrame:
    """Load the yearly homicide totals DataFrame."""
    s3 = make_s3_client()
    key = get_processed_key("homicides_totals")
    data = read_json(s3, bucket=settings.AWS_BUCKET_NAME, key=key)
    df = pd.DataFrame.from_dict(data, orient="index")
    df.index.name = "year"
    return df.reset_index()


def load_courts_flags() -> pd.DataFrame:
    """Load the courts flags DataFrame."""
    s3 = make_s3_client()
    key = get_processed_key("courts_flags")
    return read_csv_df(s3, bucket=settings.AWS_BUCKET_NAME, key=key, dtype={"dc_key": str})
