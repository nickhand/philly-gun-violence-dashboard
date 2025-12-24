"""Orchestration for shootings ETL."""

import geopandas as gpd
import pandas as pd
from loguru import logger

from etl.shootings.extract import fetch_shootings
from etl.shootings.load import write_shootings_dataset
from etl.shootings.transform import clean_shootings
from etl.utils.storage import load_shootings_database, write_meta

__all__ = ["update_shootings"]


def update_shootings(
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
    raw = fetch_shootings()

    # If the existing database is missing, skip the checks automatically
    effective_ignore = ignore_checks
    if not ignore_checks:
        try:
            _ = load_shootings_database()
        except FileNotFoundError:
            logger.info("No existing shootings database found; skipping validation checks.")
            effective_ignore = True

    # Clean the shootings data
    cleaned: gpd.GeoDataFrame = clean_shootings(raw, ignore_checks=effective_ignore)

    # If dry run, skip writing outputs
    if dry_run:
        logger.info("Dry run complete; cleaned shootings not written.")
        return cleaned

    # Write the cleaned shootings dataset
    write_shootings_dataset(cleaned)

    # The dates are stored as strings; convert to datetime to find latest
    latest_date = pd.to_datetime(cleaned["date"]).max() if not cleaned.empty else None

    # Save metadata about the update
    write_meta("shootings", data_through=latest_date)
    logger.info(f"Updated shootings dataset with {len(cleaned):,d} records")

    # Return the cleaned dataset
    return cleaned
