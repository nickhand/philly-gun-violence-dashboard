"""Load/save helpers for homicide statistics."""

import pandas as pd

from etl.utils.paths import processed_data_dir

__all__ = [
    "RAW_PATH",
    "PROCESSED_PATH",
    "read_homicide_database",
    "write_homicide_database",
    "write_processed_totals",
]

# Homicides data lives under processed_data_dir()/homicides
_HOMICIDES_DIR = processed_data_dir() / "homicides"
RAW_PATH = _HOMICIDES_DIR / "homicide_totals_daily.csv"
PROCESSED_PATH = _HOMICIDES_DIR / "homicide_totals.json"


def read_homicide_database(path=RAW_PATH) -> pd.DataFrame:
    """
    Load the homicide daily totals database.

    Parameters
    ----------
    path : pathlib.Path or str, optional
        CSV file path; defaults to the raw homicide totals path.

    Returns
    -------
    pandas.DataFrame
        DataFrame with columns ``date`` and ``total`` sorted ascending.
    """
    df = pd.read_csv(path, parse_dates=["date"])
    return df.sort_values("date", ascending=True)


def write_homicide_database(database: pd.DataFrame, path=RAW_PATH) -> None:
    """
    Persist the homicide daily totals database.

    Parameters
    ----------
    database : pandas.DataFrame
        DataFrame with columns ``date`` and ``total``.
    path : pathlib.Path or str, optional
        Output CSV path; defaults to the raw homicide totals path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = database.drop_duplicates(subset=["date"], keep="last")
    cleaned.to_csv(path, index=False)


def write_processed_totals(merged_totals: pd.DataFrame, path=PROCESSED_PATH) -> None:
    """
    Persist merged annual/YTD totals to JSON.

    Parameters
    ----------
    merged_totals : pandas.DataFrame
        DataFrame with columns including ``year``.
    path : pathlib.Path or str, optional
        Output JSON path; defaults to the processed homicide totals path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    merged_totals.set_index("year").to_json(path, orient="index")
