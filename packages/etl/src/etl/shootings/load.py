"""Load/save helpers for shootings data."""

import hashlib
import io
import json
from datetime import datetime
from typing import Final, Literal

import geopandas as gpd
import pandas as pd
from loguru import logger
from mypy_boto3_s3.client import S3Client
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from dashboard_utils.config import get_s3_settings
from dashboard_utils.models.shootings import ShootingVictimsSchema
from etl.public_downloads import (
    PublicDownloadPublication,
    _validate_application_pointer,
    load_geographic_reference_downloads,
    prepare_public_download_publication,
    validate_geographic_reference_coverage,
    write_public_download_artifacts,
    write_public_download_manifest,
)
from etl.utils.release_pointer import StablePointerSnapshot, decode_json_object

__all__ = ["ShootingsReleaseCommittedError", "write_shootings_dataset"]

PUBLIC_SHOOTINGS_CSV_COLUMNS: Final = (
    *ShootingVictimsSchema.model_fields,
    "latitude",
    "longitude",
)
CSV_FORMULA_PREFIXES: Final = ("=", "+", "-", "@", "\t", "\r")
PROCESSED_RELEASE_CACHE_CONTROL: Final = "public,max-age=31536000,immutable"


class ShootingsReleaseCommittedError(RuntimeError):
    """The authoritative release moved but a legacy mirror did not."""


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


def _shootings_geojson_body(df: gpd.GeoDataFrame) -> bytes:
    """Serialize the exact application GeoJSON before any object is written."""
    web_df = df if df.crs is None or df.crs.to_epsg() == 4326 else df.to_crs(epsg=4326)
    value = json.loads(web_df.to_json(drop_id=True))
    return json.dumps(value, allow_nan=False, separators=(",", ":")).encode("utf-8")


def _metadata_body(metadata: dict[str, object]) -> bytes:
    """Serialize processed metadata deterministically for checksumming."""
    payload = {**metadata, "release_pointer_schema_version": 1}
    return (
        json.dumps(payload, allow_nan=False, indent=2, sort_keys=True, separators=(",", ": "))
        + "\n"
    ).encode("utf-8")


def _write_application_release(s3: S3Client, publication: PublicDownloadPublication) -> None:
    """Write immutable application objects before the shared pointer moves."""
    data_body = publication.application_data_body
    metadata_body = publication.application_metadata_body
    if data_body is None or metadata_body is None:
        raise ValueError("Shootings publication is missing application data")

    settings = get_s3_settings()
    release_prefix = f"{settings.s3_processed_prefix}/shootings/releases/{publication.release_id}"
    s3.put_object(
        Bucket=settings.s3_bucket,
        Key=f"{release_prefix}/shootings.geojson",
        Body=data_body,
        ContentType="application/geo+json",
        CacheControl=PROCESSED_RELEASE_CACHE_CONTROL,
    )
    s3.put_object(
        Bucket=settings.s3_bucket,
        Key=f"{release_prefix}/meta.json",
        Body=metadata_body,
        ContentType="application/json; charset=utf-8",
        CacheControl=PROCESSED_RELEASE_CACHE_CONTROL,
    )


def _write_compatibility_mirrors(s3: S3Client, publication: PublicDownloadPublication) -> None:
    """Update mutable objects used only by legacy API/ETL builds."""
    data_body = publication.application_data_body
    metadata_body = publication.application_metadata_body
    if data_body is None or metadata_body is None:
        raise ValueError("Shootings publication is missing application data")
    settings = get_s3_settings()

    # The pointer has already moved before these writes. A pointer-aware API
    # therefore cannot observe a mixed pair during the first migration.
    s3.put_object(
        Bucket=settings.s3_bucket,
        Key=f"{settings.s3_processed_prefix}/shootings/shootings.geojson",
        Body=data_body,
        ContentType="application/geo+json",
    )
    s3.put_object(
        Bucket=settings.s3_bucket,
        Key=f"{settings.s3_processed_prefix}/shootings/meta.json",
        Body=metadata_body,
        ContentType="application/json; charset=utf-8",
    )


def _previous_application_data(
    pointer: StablePointerSnapshot,
    *,
    new_data_sha256: str,
) -> dict[str, object] | None:
    """Derive N-1 from the same pointer revision used for the final CAS."""
    if pointer.body is None:
        return None
    manifest = decode_json_object(pointer.body, label="Captured public download manifest")
    current = manifest.get("application_data")
    if current is None:
        return None
    if not isinstance(current, dict) or any(not isinstance(key, str) for key in current):
        raise ValueError("Existing manifest has invalid application_data")
    _validate_application_pointer(current)
    current_data = current.get("data")
    if isinstance(current_data, dict) and current_data.get("sha256") == new_data_sha256:
        previous = manifest.get("previous_application_data")
        if previous is None:
            return None
        if not isinstance(previous, dict) or any(not isinstance(key, str) for key in previous):
            raise ValueError("Existing manifest has invalid previous_application_data")
        _validate_application_pointer(previous)
        return previous
    return current


def write_shootings_dataset(
    s3: S3Client,
    df: gpd.GeoDataFrame,
    metadata: dict[str, object],
    *,
    expected_pointer: StablePointerSnapshot,
    run_started_at: datetime,
) -> None:
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
    application_data_body = _shootings_geojson_body(df)
    application_metadata_body = _metadata_body(metadata)
    previous_application_data = _previous_application_data(
        expected_pointer,
        new_data_sha256=hashlib.sha256(application_data_body).hexdigest(),
    )
    publication = prepare_public_download_publication(
        shootings_csv_body,
        geographic_downloads,
        published_at=run_started_at,
        application_data_body=application_data_body,
        application_metadata_body=application_metadata_body,
        previous_application_data=previous_application_data,
    )

    # Upload content-addressed public files first. They are inert until the
    # stable manifest pointer moves, so a failed upload leaves the current
    # public release and processed dashboard dataset unchanged.
    write_public_download_artifacts(s3, publication)
    _write_application_release(s3, publication)
    # This one object is both the public-download and API-data release pointer.
    # It moves only after every immutable object exists.
    write_public_download_manifest(
        s3,
        publication,
        expected_pointer=expected_pointer,
    )
    try:
        _write_compatibility_mirrors(s3, publication)
    except Exception as exc:
        logger.exception(
            "Shootings release {} committed, but compatibility mirror update failed",
            publication.release_id,
        )
        raise ShootingsReleaseCommittedError(
            f"Shootings release {publication.release_id} committed; "
            "compatibility mirror update failed"
        ) from exc
    logger.info("Wrote shootings dataset and public downloads to S3")
