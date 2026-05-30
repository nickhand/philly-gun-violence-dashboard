"""Tests for shared ETL validation helpers."""

import pandas as pd
import pytest

from etl.utils.validation import require_columns, require_non_empty, require_not_older


def test_require_non_empty_rejects_empty_frame() -> None:
    with pytest.raises(ValueError, match="source is empty"):
        require_non_empty(pd.DataFrame(), "source")


def test_require_columns_reports_missing_names() -> None:
    with pytest.raises(ValueError, match="bar, baz"):
        require_columns(pd.DataFrame({"foo": [1]}), ["foo", "bar", "baz"], "source")


def test_require_not_older_rejects_stale_dates() -> None:
    with pytest.raises(ValueError, match="moved backwards"):
        require_not_older("2026-05-24", "2026-05-25", "dataset")


def test_require_not_older_allows_same_or_newer_dates() -> None:
    require_not_older("2026-05-25", "2026-05-25", "dataset")
    require_not_older("2026-05-26", "2026-05-25", "dataset")
