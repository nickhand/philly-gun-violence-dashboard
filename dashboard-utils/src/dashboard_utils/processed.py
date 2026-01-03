"""Helpers for reading and writing processed datasets in S3."""

from typing import Any

import geopandas as gpd
import pandas as pd
from mypy_boto3_s3.client import S3Client

from dashboard_utils.aws import (
    make_s3_client,
    read_csv_df,
    read_geojson_gdf,
    read_json,
    write_csv_df,
    write_geojson_gdf,
    write_json,
)
from dashboard_utils.env import s3_settings
from dashboard_utils.paths import get_processed_key, get_reference_key


def _client(s3: S3Client | None) -> S3Client:
    return s3 or make_s3_client()


def read_processed_geojson(name: str, *, s3: S3Client | None = None) -> gpd.GeoDataFrame:
    """Read a processed GeoJSON dataset from S3."""
    key = get_processed_key(name)
    return read_geojson_gdf(_client(s3), s3_settings.AWS_BUCKET_NAME, key)


def read_processed_geojson_json(name: str, *, s3: S3Client | None = None) -> Any:
    """Read a processed GeoJSON dataset from S3 as JSON."""
    key = get_processed_key(name)
    return read_json(_client(s3), s3_settings.AWS_BUCKET_NAME, key)


def read_processed_csv(
    name: str,
    *,
    s3: S3Client | None = None,
    **read_csv_kwargs: Any,
) -> pd.DataFrame:
    """Read a processed CSV dataset from S3."""
    key = get_processed_key(name)
    return read_csv_df(_client(s3), s3_settings.AWS_BUCKET_NAME, key, **read_csv_kwargs)


def read_processed_json(name: str, *, s3: S3Client | None = None) -> Any:
    """Read a processed JSON dataset from S3."""
    key = get_processed_key(name)
    return read_json(_client(s3), s3_settings.AWS_BUCKET_NAME, key)


def read_reference_json(name: str, *, s3: S3Client | None = None) -> Any:
    """Read a reference JSON dataset from S3."""
    key = get_reference_key(name)
    return read_json(_client(s3), s3_settings.AWS_BUCKET_NAME, key)


def write_processed_geojson(
    name: str,
    gdf: gpd.GeoDataFrame,
    *,
    s3: S3Client | None = None,
) -> None:
    """Write a processed GeoJSON dataset to S3."""
    key = get_processed_key(name)
    write_geojson_gdf(_client(s3), s3_settings.AWS_BUCKET_NAME, key, gdf)


def write_processed_csv(
    name: str,
    df: pd.DataFrame,
    *,
    s3: S3Client | None = None,
    **write_csv_kwargs: Any,
) -> None:
    """Write a processed CSV dataset to S3."""
    key = get_processed_key(name)
    write_csv_df(_client(s3), s3_settings.AWS_BUCKET_NAME, key, df, **write_csv_kwargs)


def write_processed_json(name: str, data: Any, *, s3: S3Client | None = None) -> None:
    """Write a processed JSON dataset to S3."""
    key = get_processed_key(name)
    write_json(_client(s3), s3_settings.AWS_BUCKET_NAME, key, data)
