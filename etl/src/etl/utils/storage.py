"""Utilities for reading and writing processed data and metadata."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from mypy_boto3_s3.client import S3Client

from dashboard_utils.aws import upload_file
from dashboard_utils.env import settings
from dashboard_utils.paths import get_processed_path, processed_data_dir

__all__ = [
    "write_meta",
    "load_shootings_database",
    "load_street_blocks",
    "load_homicide_database",
    "load_homicide_totals",
    "load_courts_flags",
]


def write_meta(s3: S3Client, *, subfolder: str, data_through: Any = None) -> None:
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

    # Ensure the folder exists
    folder = processed_data_dir() / subfolder
    folder.mkdir(parents=True, exist_ok=True)

    # Write the meta.json file locally
    path = folder / "meta.json"
    path.write_text(json.dumps(meta, indent=2))

    # Upload it to s3
    upload_file(
        s3,
        path,
        bucket=settings.AWS_BUCKET_NAME,
        key=f"processed/{subfolder}/meta.json",
        content_type="application/json",
    )


# -----------------------------------------------------------------------------
# Processed data loaders
# -----------------------------------------------------------------------------


def _ensure_path_exists(path: Path) -> None:
    """Ensure that the given path exists, raising FileNotFoundError if not."""
    if not path.exists():
        raise FileNotFoundError(f"Missing data at {path}")


def load_shootings_database() -> gpd.GeoDataFrame:
    """Load the shootings database GeoDataFrame."""
    path = get_processed_path("shootings")
    _ensure_path_exists(path)
    return gpd.read_file(path)


def load_street_blocks() -> gpd.GeoDataFrame:
    """Load the street blocks GeoDataFrame."""
    path = get_processed_path("street_blocks")
    _ensure_path_exists(path)
    return gpd.read_file(path)


def load_homicide_database() -> pd.DataFrame:
    """Load the daily homicide database DataFrame."""
    path = get_processed_path("homicides_daily")
    _ensure_path_exists(path)
    return pd.read_csv(path, parse_dates=["date"]).sort_values("date")


def load_homicide_totals() -> pd.DataFrame:
    """Load the yearly homicide totals DataFrame."""
    path = get_processed_path("homicides_totals")
    _ensure_path_exists(path)

    df = pd.read_json(path, orient="index")
    df.index.name = "year"
    return df.reset_index()


def load_courts_flags() -> pd.DataFrame:
    """Load the courts flags DataFrame."""
    path = get_processed_path("courts_flags")
    _ensure_path_exists(path)
    return pd.read_csv(path, dtype={"dc_key": str})
