"""Utilities for reading and writing processed data and metadata."""

from datetime import UTC, datetime
from typing import Any

import geopandas as gpd
import pandas as pd
from mypy_boto3_s3.client import S3Client

from dashboard_utils.aws import make_s3_client, write_json
from dashboard_utils.env import s3_settings
from dashboard_utils.processed import (
    read_processed_csv,
    read_processed_geojson,
    read_processed_json,
)

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
        s3_settings.AWS_BUCKET_NAME,
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
    """Load the shootings database GeoDataFrame from s3."""
    return read_processed_geojson("shootings", s3=_client(s3))


def load_street_blocks(*, s3: S3Client | None = None) -> gpd.GeoDataFrame:
    """Load the street blocks GeoDataFrame."""
    return read_processed_geojson("street_blocks", s3=_client(s3))


def load_homicide_database(*, s3: S3Client | None = None) -> pd.DataFrame:
    """Load the daily homicide database DataFrame."""
    df = read_processed_csv("homicides_daily", s3=_client(s3), parse_dates=["date"])
    return df.sort_values("date")


def load_homicide_totals(*, s3: S3Client | None = None) -> pd.DataFrame:
    """Load the yearly homicide totals DataFrame."""
    data = read_processed_json("homicides_totals", s3=_client(s3))
    df = pd.DataFrame.from_dict(data, orient="index")
    df.index.name = "year"
    return df.reset_index()


def load_courts_flags(*, s3: S3Client | None = None) -> pd.DataFrame:
    """Load the courts flags DataFrame."""
    return read_processed_csv("courts_flags", s3=_client(s3), dtype={"dc_key": str})
