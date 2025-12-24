"""Load/save helpers for homicide statistics."""

import pandas as pd

from etl.utils.aws import mirror_to_s3
from etl.utils.paths import get_processed_path

__all__ = ["write_homicide_database", "write_processed_totals"]


def write_homicide_database(database: pd.DataFrame) -> None:
    """
    Persist the homicide daily totals database.

    Parameters
    ----------
    database : pandas.DataFrame
        DataFrame with columns ``date`` and ``total``.
    path : pathlib.Path or str, optional
        Output CSV path; defaults to the raw homicide totals path.
    """
    database_path = get_processed_path("homicides_daily")
    database_path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = database.drop_duplicates(subset=["date"], keep="last")
    cleaned.to_csv(database_path, index=False)
    mirror_to_s3(database_path)


def write_processed_totals(merged_totals: pd.DataFrame) -> None:
    """
    Persist merged annual/YTD totals to JSON.

    Parameters
    ----------
    merged_totals : pandas.DataFrame
        DataFrame with columns including ``year``.
    path : pathlib.Path or str, optional
        Output JSON path; defaults to the processed homicide totals path.
    """
    totals_path = get_processed_path("homicides_totals")
    totals_path.parent.mkdir(parents=True, exist_ok=True)
    merged_totals.set_index("year").to_json(totals_path, orient="index")
    mirror_to_s3(totals_path)
