"""Orchestration for homicide statistics ETL."""

import pandas as pd
from loguru import logger
from mypy_boto3_s3.client import S3Client

from etl.homicides.extract import extract_homicide_stats
from etl.homicides.load import write_homicide_database, write_processed_totals
from etl.homicides.transform import append_daily_total, merge_totals
from etl.utils.storage import load_homicide_database, write_meta
from etl.utils.validation import require_columns, require_non_empty, require_not_older

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
    require_non_empty(annual_totals, "annual homicide totals")
    require_columns(annual_totals, ["year", "annual"], "annual homicide totals")
    require_non_empty(ytd_totals, "YTD homicide totals")
    require_columns(ytd_totals, ["year", "ytd"], "YTD homicide totals")

    # Read the homicide database and merge
    database = load_homicide_database(s3=s3)
    merged = merge_totals(annual_totals, ytd_totals)
    require_non_empty(merged, "merged homicide totals")
    require_columns(merged, ["year", "annual", "ytd"], "merged homicide totals")

    latest_ytd = ytd_totals.iloc[0]["ytd"]
    if latest_ytd < 0:
        raise ValueError(f"YTD homicide total cannot be negative: {latest_ytd}")

    previous_row_count = len(database)
    previous_data_through = None
    if not database.empty:
        previous_data_through = pd.to_datetime(database["date"]).max()
        if not force:
            require_not_older(as_of_date, previous_data_through, "homicides data_through")

    # Determine whether the daily database needs an update
    needs_daily_update = not (
        not database.empty
        and as_of_date == database.iloc[-1]["date"]
        and database.iloc[-1]["total"] == latest_ytd
    )

    # Append the new daily total only when needed
    updated_database = database
    if needs_daily_update:
        updated_database = append_daily_total(
            database,
            as_of_date,
            latest_ytd,
            force=force,
        )
    else:
        logger.info(
            "Homicide daily database already up to date through {} (YTD={}); "
            "skipping daily update.",
            as_of_date.date(),
            latest_ytd,
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
        write_meta(
            subfolder="homicides",
            data_through=as_of_date,
            s3=s3,
            pipeline="homicides",
            source="philly_police_homicide_statistics",
            row_count=len(updated_database),
            totals_count=len(merged),
            daily_updated=needs_daily_update,
            ytd_total=latest_ytd,
            previous_row_count=previous_row_count,
            previous_data_through=previous_data_through,
        )
        if needs_daily_update:
            write_homicide_database(s3, updated_database)
        logger.info(
            "Updated homicide totals through {} (YTD={})",
            as_of_date.date(),
            ytd_totals.iloc[0]["ytd"],
        )

    return updated_database, merged
