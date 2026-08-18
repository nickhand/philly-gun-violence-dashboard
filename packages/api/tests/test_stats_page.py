"""Unit tests for statistics aggregation, rendering, and cache invalidation."""

import os

os.environ.setdefault("ENV", "prod")
os.environ.setdefault("AWS_BUCKET_NAME", "test-bucket")
os.environ.setdefault("AWS_REGION", "us-east-1")

import pytest
from fastapi import FastAPI

from app.stats_page import (
    build_stats_snapshot,
    get_stats_page_cache,
    render_stats_page,
)


def _app_with_data() -> FastAPI:
    app = FastAPI()
    app.state.shootings_rows_by_year = {
        2022: [
            {"date": "2022-01-01 12:00:00", "fatal": 0},
            {"date": "2022-02-01 12:00:00", "fatal": 1},
            {"date": "2022-03-01 12:00:00", "fatal": 0},
        ],
        2023: [
            {"date": "2023-04-01 12:00:00", "fatal": "true"},
            {"date": "2023-04-02 12:00:00", "fatal": "0"},
        ],
    }
    app.state.homicides_totals = {
        "2022": {"annual": 500, "ytd": 100},
        "2023": {"annual": None, "ytd": 80},
    }
    app.state.shootings_freshness = {"data_through": "2023-04-02"}
    app.state.homicides_freshness = {"data_through": "2023-04-03"}
    app.state.shootings_version = "shootings-v1"
    app.state.dataset_etags = {"shootings": "shoot-etag", "homicides": "hom-etag"}
    return app


def test_snapshot_matches_loaded_api_data() -> None:
    snapshot = build_stats_snapshot(_app_with_data())

    assert snapshot.current_year == 2023
    assert snapshot.total_victims_all_years == 5
    assert snapshot.current_total == 2
    assert snapshot.current_fatal == 1
    assert snapshot.current_nonfatal == 1
    assert snapshot.shootings_previous_ytd == 3
    assert snapshot.shooting_percent_change == -33
    assert snapshot.homicides_ytd == 80
    assert snapshot.homicides_previous_ytd == 100
    assert snapshot.homicide_percent_change == -20
    assert snapshot.peak.year == 2022
    assert snapshot.peak.victims == 3


def test_rendered_page_preserves_distinct_dataset_dates() -> None:
    html = render_stats_page(build_stats_snapshot(_app_with_data()))

    assert "Shootings through April 2, 2023 · Homicides through April 3, 2023" in html
    assert "As of April 2, 2023, there have been 2 shooting victims" in html
    assert "As of April 3, 2023, Philadelphia has recorded 80 homicides" in html
    assert '"dateModified": "2023-04-02"' in html
    assert "dashboard data page" in html
    assert "public JSON API" not in html
    assert "/docs" not in html
    assert '"contentUrl"' not in html
    assert "{{" not in html


def test_single_year_uses_current_year_as_peak() -> None:
    app = _app_with_data()
    app.state.shootings_rows_by_year = {2023: app.state.shootings_rows_by_year[2023]}

    snapshot = build_stats_snapshot(app)

    assert snapshot.peak.year == 2023
    assert snapshot.peak.victims == 2
    assert snapshot.shootings_previous_ytd is None
    assert snapshot.shooting_percent_change is None


def test_shooting_comparison_uses_inclusive_same_calendar_cutoff() -> None:
    app = _app_with_data()
    app.state.shootings_rows_by_year[2022] = [
        {"date": "2022-04-02 23:59:59", "fatal": 0},
        {"date": "2022-04-03 00:00:00", "fatal": 0},
    ]

    snapshot = build_stats_snapshot(app)

    assert snapshot.shootings_previous_ytd == 1
    assert snapshot.shooting_percent_change == 100


def test_shooting_comparison_clamps_leap_day_to_february_28() -> None:
    app = _app_with_data()
    app.state.shootings_rows_by_year = {
        2023: [
            {"date": "2023-02-28 23:59:59", "fatal": 0},
            {"date": "2023-03-01 00:00:00", "fatal": 0},
        ],
        2024: [{"date": "2024-02-29 12:00:00", "fatal": 0}],
    }
    app.state.shootings_freshness = {"data_through": "2024-02-29"}

    snapshot = build_stats_snapshot(app)

    assert snapshot.shootings_previous_ytd == 1
    assert snapshot.shooting_percent_change == 0


@pytest.mark.parametrize("year", [2022, 2023])
def test_shooting_comparison_fails_closed_on_invalid_row_dates(year: int) -> None:
    app = _app_with_data()
    app.state.shootings_rows_by_year[year][0]["date"] = "not-a-date"

    snapshot = build_stats_snapshot(app)

    assert snapshot.shootings_previous_ytd is None
    assert snapshot.shooting_percent_change is None


def test_shooting_comparison_fails_closed_on_cutoff_year_mismatch() -> None:
    app = _app_with_data()
    app.state.shootings_freshness = {"data_through": "2022-04-02"}

    snapshot = build_stats_snapshot(app)

    assert snapshot.shootings_previous_ytd is None
    assert snapshot.shooting_percent_change is None


@pytest.mark.parametrize("freshness", [None, {"data_through": "not-a-date"}])
def test_shooting_comparison_requires_authoritative_cutoff(freshness: object) -> None:
    app = _app_with_data()
    app.state.shootings_freshness = freshness

    snapshot = build_stats_snapshot(app)

    assert snapshot.shootings_previous_ytd is None
    assert snapshot.shooting_percent_change is None


def test_shooting_comparison_fails_closed_when_current_row_exceeds_cutoff() -> None:
    app = _app_with_data()
    app.state.shootings_rows_by_year[2023].append({"date": "2023-04-03 00:00:00", "fatal": 0})

    snapshot = build_stats_snapshot(app)

    assert snapshot.shootings_previous_ytd is None
    assert snapshot.shooting_percent_change is None


def test_shooting_comparison_omits_percent_when_previous_count_is_zero() -> None:
    app = _app_with_data()
    app.state.shootings_rows_by_year[2022] = []

    snapshot = build_stats_snapshot(app)

    assert snapshot.shootings_previous_ytd == 0
    assert snapshot.shooting_percent_change is None


def test_zero_previous_homicides_omits_percentage() -> None:
    app = _app_with_data()
    app.state.homicides_totals["2022"]["ytd"] = 0

    assert build_stats_snapshot(app).homicide_percent_change is None


def test_empty_shootings_are_rejected_explicitly() -> None:
    app = _app_with_data()
    app.state.shootings_rows_by_year = {}

    with pytest.raises(ValueError, match="without shooting records"):
        build_stats_snapshot(app)


def test_cache_reuses_render_and_invalidates_on_dataset_version() -> None:
    app = _app_with_data()

    first = get_stats_page_cache(app)
    second = get_stats_page_cache(app)
    app.state.shootings_version = "shootings-v2"
    third = get_stats_page_cache(app)

    assert second is first
    assert third is not first
    assert third.source_key != first.source_key
