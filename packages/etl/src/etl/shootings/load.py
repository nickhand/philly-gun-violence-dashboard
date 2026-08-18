"""Load/save helpers for shootings data."""

import io
from typing import Final, Literal

import geopandas as gpd
import pandas as pd
from loguru import logger
from mypy_boto3_s3.client import S3Client
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from dashboard_utils.models.shootings import ShootingVictimsSchema
from dashboard_utils.processed import write_processed_geojson
from etl.public_downloads import (
    load_geographic_reference_downloads,
    prepare_public_download_publication,
    validate_geographic_reference_coverage,
    write_public_download_artifacts,
    write_public_download_manifest,
)

__all__ = ["write_shootings_dataset"]

PUBLIC_SHOOTINGS_CSV_COLUMNS: Final = (
    *ShootingVictimsSchema.model_fields,
    "latitude",
    "longitude",
)
CSV_FORMULA_PREFIXES: Final = ("=", "+", "-", "@", "\t", "\r")


def _point_coordinate(
    geometry: BaseGeometry | None,
    coordinate: Literal["x", "y"],
) -> float | None:
    """Return one coordinate from a non-empty point geometry."""
    if geometry is None or geometry.is_empty:
        return None
    if not isinstance(geometry, Point):
        raise ValueError("Public shootings CSV requires point geometries")
    return float(getattr(geometry, coordinate))


def _public_shootings_csv(df: gpd.GeoDataFrame) -> str:
    """Serialize the public record-level download from the cleaned dataset."""
    if df.crs is None:
        raise ValueError("Public shootings CSV requires a known coordinate system")

    record_columns = list(PUBLIC_SHOOTINGS_CSV_COLUMNS[:-2])
    missing = [column for column in record_columns if column not in df.columns]
    if missing:
        raise ValueError(f"Public shootings CSV is missing columns: {missing}")

    web_df = df.to_crs(epsg=4326)
    export = pd.DataFrame(web_df[record_columns].copy())
    for column in ("fatal", "has_court_case"):
        export[column] = export[column].map(
            lambda value: "" if pd.isna(value) else str(bool(value)).lower()
        )
    export["latitude"] = [_point_coordinate(geometry, "y") for geometry in web_df.geometry]
    export["longitude"] = [_point_coordinate(geometry, "x") for geometry in web_df.geometry]
    export = export[list(PUBLIC_SHOOTINGS_CSV_COLUMNS)]

    for column in export.columns:
        for value in export[column].dropna():
            if isinstance(value, str) and value.startswith(CSV_FORMULA_PREFIXES):
                raise ValueError(
                    "Public shootings CSV contains a spreadsheet-formula prefix "
                    f"in column '{column}'"
                )

    buffer = io.StringIO(newline="")
    export.to_csv(buffer, index=False, lineterminator="\n")
    return buffer.getvalue()


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
    geographic_downloads = load_geographic_reference_downloads(s3)
    validate_geographic_reference_coverage(df, geographic_downloads)
    shootings_csv_body = _public_shootings_csv(df).encode("utf-8")
    publication = prepare_public_download_publication(
        shootings_csv_body,
        geographic_downloads,
    )

    # Upload content-addressed public files first. They are inert until the
    # stable manifest pointer moves, so a failed upload leaves the current
    # public release and processed dashboard dataset unchanged.
    write_public_download_artifacts(s3, publication)
    write_processed_geojson("shootings", df, s3=s3)
    # Publish the pointer last so it never names a partial public release. S3
    # cannot transact this pointer and the separate processed object together;
    # a failed final pointer write leaves the previous public release active
    # and fails the workflow before its explicit API restart step.
    write_public_download_manifest(s3, publication)
    logger.info("Wrote shootings dataset and public downloads to S3")
