"""Fail-closed reporting-period tests for the homicide pipeline."""

from datetime import date
from typing import cast

import pandas as pd
import pytest
from mypy_boto3_s3.client import S3Client

from etl.homicides import extract, pipeline


def _source_tables(selected_year: int = 2026) -> tuple[pd.DataFrame, pd.DataFrame]:
    annual_years = list(range(selected_year - 1, 2006, -1))
    ytd_years = list(range(selected_year, 2006, -1))
    return (
        pd.DataFrame(
            {
                "year": annual_years,
                "annual": [250 + index for index, _ in enumerate(annual_years)],
            }
        ),
        pd.DataFrame(
            {
                "year": ytd_years,
                "ytd": [116 + index for index, _ in enumerate(ytd_years)],
            }
        ),
    )


@pytest.fixture(autouse=True)
def fixed_source_today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extract, "_source_today", lambda: date(2026, 8, 18))


@pytest.mark.parametrize("force", [False, True])
def test_pipeline_rejects_ytd_year_drift_before_storage_reads(
    monkeypatch: pytest.MonkeyPatch,
    force: bool,
) -> None:
    annual, ytd = _source_tables()
    ytd = pd.concat(
        [
            ytd.iloc[[0]],
            pd.DataFrame({"year": [2027], "ytd": [1]}),
            ytd.iloc[1:],
        ],
        ignore_index=True,
    )
    monkeypatch.setattr(
        pipeline,
        "extract_homicide_stats",
        lambda debug=False: (pd.Timestamp("2026-08-16 11:59:00"), annual, ytd),
    )
    monkeypatch.setattr(
        pipeline,
        "load_homicide_database",
        lambda **kwargs: pytest.fail("storage must not be read for an invalid snapshot"),
    )

    with pytest.raises(ValueError, match="as-of year 2026.*latest YTD row year 2027"):
        pipeline.update_homicide_totals(
            cast(S3Client, object()),
            force=force,
            dry_run=True,
        )


def test_pipeline_rejects_future_as_of_before_storage_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    annual, ytd = _source_tables()
    monkeypatch.setattr(
        pipeline,
        "extract_homicide_stats",
        lambda debug=False: (pd.Timestamp("2026-08-19 11:59:00"), annual, ytd),
    )
    monkeypatch.setattr(
        pipeline,
        "load_homicide_database",
        lambda **kwargs: pytest.fail("storage must not be read for an invalid snapshot"),
    )

    with pytest.raises(ValueError, match="in the future"):
        pipeline.update_homicide_totals(cast(S3Client, object()), dry_run=True)


def test_pipeline_selects_the_max_ytd_year_instead_of_source_row_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    annual, ytd = _source_tables()
    ytd = ytd.sort_values("year", ascending=True).reset_index(drop=True)
    monkeypatch.setattr(
        pipeline,
        "extract_homicide_stats",
        lambda debug=False: (pd.Timestamp("2026-08-16 11:59:00"), annual, ytd),
    )
    monkeypatch.setattr(
        pipeline,
        "load_homicide_database",
        lambda **kwargs: pd.DataFrame(columns=["date", "total"]),
    )

    updated, _ = pipeline.update_homicide_totals(
        cast(S3Client, object()),
        dry_run=True,
    )

    assert updated.iloc[-1]["date"] == pd.Timestamp("2026-08-16 11:59:00")
    assert updated.iloc[-1]["total"] == 116
