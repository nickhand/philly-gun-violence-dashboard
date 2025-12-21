"""Transform helpers for homicide statistics."""

import pandas as pd
from loguru import logger

__all__ = ["merge_totals", "append_daily_total"]


def merge_totals(annual_totals: pd.DataFrame, ytd_totals: pd.DataFrame) -> pd.DataFrame:
    """
    Merge annual and YTD totals on year.

    Parameters
    ----------
    annual_totals : pandas.DataFrame
        DataFrame with columns ``year`` and ``annual``.
    ytd_totals : pandas.DataFrame
        DataFrame with columns ``year`` and ``ytd``.

    Returns
    -------
    pandas.DataFrame
        Merged table with columns ``year``, ``annual``, and ``ytd``.
    """
    return pd.merge(annual_totals, ytd_totals, on="year", how="outer")


def append_daily_total(
    database: pd.DataFrame,
    as_of_date: pd.Timestamp,
    ytd_value: int,
    *,
    force: bool = False,
) -> pd.DataFrame:
    """
    Append the latest YTD total to the database with sanity checks.

    Parameters
    ----------
    database : pandas.DataFrame
        Existing database with columns ``date`` and ``total`` sorted ascending.
    as_of_date : pandas.Timestamp
        Date associated with the new YTD total.
    ytd_value : int
        New YTD homicide total.
    force : bool, optional
        If ``True``, skip the monotonicity check within the same year.

    Returns
    -------
    pandas.DataFrame
        Updated database with duplicates removed and sorted by date.

    Raises
    ------
    ValueError
        If the new total is less than the previous total for the same year and ``force`` is False.
    """
    db = database.copy()
    if not db.empty and as_of_date == db.iloc[-1]["date"]:
        db = db.drop(index=db.index[-1])

    # Add new record
    N = len(db)
    db.loc[N, "date"] = as_of_date
    db.loc[N, "total"] = ytd_value

    if len(db) >= 2:
        new_total = db.iloc[-1]["total"]
        old_total = db.iloc[-2]["total"]
        new_year = db.iloc[-1]["date"].year
        old_year = db.iloc[-2]["date"].year
        if not force and new_total < old_total and new_year == old_year:
            raise ValueError(
                f"New YTD homicide total ({new_total}) is less than previous YTD total ({old_total})"
            )

    db = db.drop_duplicates(subset=["date"], keep="last").sort_values(
        "date", ascending=True
    )
    logger.debug("Updated homicide database now has {} rows", len(db))
    return db
