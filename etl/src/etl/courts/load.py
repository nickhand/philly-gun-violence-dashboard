"""
Load/save helpers for courts portal scraping results.
"""

import pandas as pd

from etl.utils.paths import processed_data_dir

__all__ = ["DATA_PATH", "read_existing_flags", "write_flags"]

DATA_PATH = processed_data_dir() / "courts" / "scraped_courts_data.csv"


def read_existing_flags(path=DATA_PATH) -> pd.DataFrame:
    """Read existing dc_key/has_court_case flags if present."""
    if not path.exists():
        return pd.DataFrame(columns=["dc_key", "has_court_case"])
    return pd.read_csv(path, dtype={"dc_key": str})


def write_flags(df: pd.DataFrame, path=DATA_PATH) -> None:
    """Persist flags to CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
