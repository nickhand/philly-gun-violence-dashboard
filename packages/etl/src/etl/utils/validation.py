"""Small validation helpers shared by ETL pipelines."""

from collections.abc import Iterable
from typing import Any

import pandas as pd

__all__ = [
    "require_columns",
    "require_non_empty",
    "require_not_older",
]


def require_non_empty(df: pd.DataFrame, name: str) -> None:
    """Raise if a required ETL table is empty."""
    if df.empty:
        raise ValueError(f"{name} is empty")


def require_columns(df: pd.DataFrame, columns: Iterable[str], name: str) -> None:
    """Raise if a required ETL table is missing expected columns."""
    missing = sorted(set(columns) - set(df.columns))
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"{name} is missing required columns: {joined}")


def require_not_older(new_value: Any, old_value: Any, name: str) -> None:
    """Raise if a newly extracted date would move a dataset backwards."""
    if pd.isna(new_value) or pd.isna(old_value):
        return

    new_ts = pd.to_datetime(new_value)
    old_ts = pd.to_datetime(old_value)
    if new_ts < old_ts:
        raise ValueError(
            f"{name} moved backwards: new value {new_ts.date()} is older than "
            f"existing value {old_ts.date()}"
        )
