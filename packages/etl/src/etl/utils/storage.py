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
    read_processed_json,
)

__all__ = [
    "build_meta",
    "write_meta",
    "load_shootings_database",
    "load_street_blocks",
    "load_homicide_database",
    "load_courts_flags",
    "load_courts_metadata",
]


def build_meta(
    *,
    data_through: Any = None,
    status: str = "success",
    now: datetime | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build one validated, JSON-safe processed metadata object."""
    timestamp = now or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("Metadata timestamp must include a timezone")
    data_through_iso = (
        pd.to_datetime(data_through).date().isoformat()
        if data_through is not None
        else pd.Timestamp(timestamp).date().isoformat()
    )
    return {
        "status": status,
        "last_updated": timestamp.astimezone(UTC).isoformat(),
        "data_through": data_through_iso,
        "schema_version": 1,
        **{key: _meta_value(value) for key, value in extra.items() if value is not None},
    }


def write_meta(
    *,
    subfolder: str,
    data_through: Any = None,
    s3: S3Client | None = None,
    status: str = "success",
    **extra: Any,
) -> None:
    """Build and write processed metadata for a legacy stable object."""
    meta = build_meta(data_through=data_through, status=status, **extra)

    write_json(
        _client(s3),
        get_s3_settings().s3_bucket,
        f"{get_s3_settings().s3_processed_prefix}/{subfolder}/meta.json",
        meta,
        indent=2,
    )


def _meta_value(value: Any) -> Any:
    """Return a JSON-safe metadata value for common pandas/numpy scalars."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


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


def load_courts_metadata(*, s3: S3Client | None = None) -> Any:
    """Load the provenance metadata paired with the stable courts flags."""
    return read_processed_json("courts_meta", s3=_client(s3))
