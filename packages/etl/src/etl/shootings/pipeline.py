"""Orchestration for shootings ETL."""

from datetime import UTC, datetime

import geopandas as gpd
import pandas as pd
from loguru import logger
from mypy_boto3_s3.client import S3Client

from etl.public_downloads import read_public_download_pointer
from etl.shootings.extract import fetch_shootings
from etl.shootings.load import write_shootings_dataset
from etl.shootings.transform import clean_shootings
from etl.utils.release_pointer import StablePointerSnapshot
from etl.utils.storage import build_meta, load_shootings_database
from etl.utils.validation import require_columns, require_non_empty, require_not_older

__all__ = ["update_shootings"]

RAW_SHOOTINGS_COLUMNS = {
    "officer_involved",
    "dc_key",
    "time",
    "date_",
    "race",
    "age",
    "latino",
    "fatal",
    "inside",
    "outside",
    "location",
}


def update_shootings(
    s3: S3Client,
    *,
    ignore_checks: bool = False,
    dry_run: bool = False,
) -> gpd.GeoDataFrame:
    """
    Extract, transform, and load shootings data.

    Parameters
    ----------
    ignore_checks : bool, optional
        If ``True``, skip validation checks against the existing database.
        Useful for a first-time load when no baseline data exists.
    dry_run : bool, optional
        If ``True``, perform ETL steps but skip writing outputs.

    Returns
    -------
    geopandas.GeoDataFrame
        The cleaned shootings dataset.
    """
    run_started_at = datetime.now(UTC)
    expected_pointer = (
        StablePointerSnapshot.missing() if dry_run else read_public_download_pointer(s3)
    )
    raw = fetch_shootings()
    require_non_empty(raw, "raw shootings extract")
    require_columns(raw, RAW_SHOOTINGS_COLUMNS, "raw shootings extract")

    # If the existing database is missing, skip the checks automatically
    effective_ignore = ignore_checks
    existing: gpd.GeoDataFrame | None = None
    if not ignore_checks:
        try:
            existing = load_shootings_database(s3=s3)
        except FileNotFoundError:
            logger.info("No existing shootings database found; skipping validation checks.")
            effective_ignore = True

    # Clean the shootings data
    cleaned: gpd.GeoDataFrame = clean_shootings(s3, raw, ignore_checks=effective_ignore)
    require_non_empty(cleaned, "cleaned shootings data")
    require_columns(cleaned, ["date", "dc_key"], "cleaned shootings data")

    latest_date = pd.to_datetime(cleaned["date"]).max()
    previous_latest_date = None
    previous_row_count = None
    if existing is not None and not existing.empty:
        previous_row_count = len(existing)
        previous_latest_date = pd.to_datetime(existing["date"]).max()
        if not ignore_checks:
            require_not_older(latest_date, previous_latest_date, "shootings data_through")

    # If dry run, skip writing outputs
    if dry_run:
        logger.info("Dry run complete; cleaned shootings not written.")
        return cleaned

    metadata = build_meta(
        now=run_started_at,
        data_through=latest_date,
        pipeline="shootings",
        source="opendataphilly_shootings",
        row_count=len(cleaned),
        max_event_date=latest_date,
        previous_row_count=previous_row_count,
        previous_data_through=previous_latest_date,
    )
    # The metadata and data are published as one release behind a single
    # stable pointer; neither can become visible without the other.
    write_shootings_dataset(
        s3,
        cleaned,
        metadata,
        expected_pointer=expected_pointer,
        run_started_at=run_started_at,
    )
    logger.info(f"Updated shootings dataset with {len(cleaned):,d} records")

    # Return the cleaned dataset
    return cleaned
