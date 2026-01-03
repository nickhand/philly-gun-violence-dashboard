"""Orchestration for homicide statistics ETL."""

import pandas as pd
from loguru import logger
from mypy_boto3_s3.client import S3Client

from etl.homicides.extract import extract_homicide_stats
from etl.homicides.load import write_homicide_database, write_processed_totals
from etl.homicides.transform import append_daily_total, merge_totals
from etl.utils.storage import load_homicide_database, write_meta

__all__ = ["update_homicide_totals"]


def update_homicide_totals(
    s3: S3Client,
    *,
    debug: bool = False,
    force: bool = False,
    dry_run: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Extract, transform, and load homicide totals.

    Parameters
    ----------
    s3 : S3Client
        The S3 client to use for uploading metadata.
    debug : bool, optional
        Whether to run Playwright with a visible (non-headless) browser.
    force : bool, optional
        If ``True``, skip the monotonicity check on YTD totals within a year.
    dry_run : bool, optional
        If ``True``, perform extraction and transformation but skip writing outputs.

    Returns
    -------
    tuple
        ``(database_df, merged_totals_df)`` for the updated daily database and merged totals.
    """
    # Extract homicide stats
    as_of_date, annual_totals, ytd_totals = extract_homicide_stats(debug=debug)

    # Read the homicide database and merge
    database = load_homicide_database()
    merged = merge_totals(annual_totals, ytd_totals)
    latest_ytd = ytd_totals.iloc[0]["ytd"]

    # If already up to date, log and exit early
    if (
        not database.empty
        and as_of_date == database.iloc[-1]["date"]
        and database.iloc[-1]["total"] == latest_ytd
    ):
        logger.info(
            "Homicide totals already up to date through {} (YTD={}); no changes made.",
            as_of_date.date(),
            latest_ytd,
        )
        return database, merged

    # Append the new daily total to the database and write outputs
    updated_database = append_daily_total(
        database,
        as_of_date,
        latest_ytd,
        force=force,
    )

    # Write outputs (unless dry run)
    if dry_run:
        logger.info(
            "Dry run: would update homicide totals through {} (YTD={}); no files written.",
            as_of_date.date(),
            ytd_totals.iloc[0]["ytd"],
        )
    else:
        write_processed_totals(s3, merged)
        write_homicide_database(s3, updated_database)
        write_meta(subfolder="homicides", data_through=as_of_date)
        logger.info(
            "Updated homicide totals through {} (YTD={})",
            as_of_date.date(),
            ytd_totals.iloc[0]["ytd"],
        )

    return updated_database, merged
