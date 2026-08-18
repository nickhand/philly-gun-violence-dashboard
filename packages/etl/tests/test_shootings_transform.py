"""Regression tests for shooting-victim transformations and quality gates."""

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point

from etl.shootings.transform import core


def _binary_frame(values: list[object]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {column: values for column in core.BINARY_COLUMNS},
        geometry=[Point(index, index) for index in range(len(values))],
        crs="EPSG:4326",
    )


def test_normalize_binary_columns_accepts_numeric_and_string_flags() -> None:
    raw = _binary_frame(["0", "1", 0, 1, 0.0, 1.0, False, True, "no", "yes"])

    result = core._normalize_binary_columns(raw)

    expected = [False, True, False, True, False, True, False, True, False, True]
    for column in core.BINARY_COLUMNS:
        assert result[column].tolist() == expected
        assert result[column].dtype == bool


@pytest.mark.parametrize("bad_value", [None, "", "unknown", 2])
def test_normalize_binary_columns_rejects_unknown_values(bad_value: object) -> None:
    raw = _binary_frame(["0", bad_value])

    with pytest.raises(ValueError, match="Raw shootings column 'fatal'"):
        core._normalize_binary_columns(raw)


@pytest.mark.parametrize(
    ("fatal_values", "expected_message"),
    [
        ([False, False], "0 fatal and 2 nonfatal"),
        ([True, True], "2 fatal and 0 nonfatal"),
    ],
)
def test_require_plausible_outcomes_rejects_single_outcome_dataset(
    fatal_values: list[bool], expected_message: str
) -> None:
    with pytest.raises(ValueError, match=expected_message):
        core._require_plausible_outcomes(pd.DataFrame({"fatal": fatal_values}))


def test_run_checks_rejects_large_fatal_count_decrease(monkeypatch) -> None:
    old = gpd.GeoDataFrame({"fatal": [True] * 100 + [False] * 100})
    new = gpd.GeoDataFrame({"fatal": [True] * 80 + [False] * 120})
    monkeypatch.setattr(core, "load_shootings_database", lambda **_kwargs: old)

    with pytest.raises(ValueError, match="implausible decrease in fatal shooting victims"):
        core._run_checks(new)


def test_clean_shootings_uses_normalized_flags_before_race_mapping(monkeypatch) -> None:
    raw = gpd.GeoDataFrame(
        {
            "officer_involved": ["N", "N"],
            "dc_key": [1, 2],
            "time": ["12:00:00", "13:00:00"],
            "date_": ["2025-01-01", "2025-01-02"],
            "race": ["B", "W"],
            "age": [25, 30],
            "latino": ["1", "0"],
            "fatal": ["1", "0"],
            "inside": ["1", "0"],
            "outside": ["0", "1"],
            "location": ["100 BLOCK TEST ST", "200 BLOCK TEST ST"],
            "point_x": [0, 0],
            "point_y": [0, 0],
            "objectid": [1, 2],
            "cartodb_id": [1, 2],
        },
        geometry=[Point(-75.1, 40.0), Point(-75.2, 40.1)],
        crs="EPSG:4326",
    )
    monkeypatch.setattr(core, "join_with_boundary_datasets", lambda df: df)
    monkeypatch.setattr(core, "join_with_street_blocks", lambda df, **_kwargs: df)
    monkeypatch.setattr(
        core,
        "load_courts_flags",
        lambda **_kwargs: pd.DataFrame({"dc_key": ["1", "2"], "has_court_case": [False, False]}),
    )
    monkeypatch.setattr(core, "_validate_against_schema", lambda df: df)

    result = core.clean_shootings(object(), raw, ignore_checks=True)  # ty: ignore[invalid-argument-type]

    assert result["fatal"].tolist() == [False, True]
    assert result["inside"].tolist() == [False, True]
    assert result["outside"].tolist() == [True, False]
    assert result["latino"].tolist() == [False, True]
    assert result["race"].tolist() == ["W", "H"]
