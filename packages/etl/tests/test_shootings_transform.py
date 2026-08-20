"""Regression tests for shooting-victim transformations and quality gates."""

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point

from etl.courts.publication import court_flags_sha256
from etl.courts.semantics import sanitize_court_search_flags
from etl.shootings.transform import boundaries as boundary_transform
from etl.shootings.transform import core


def _valid_schema_frame(has_court_case: object) -> gpd.GeoDataFrame:
    """Build one row at the final shootings schema boundary."""
    return gpd.GeoDataFrame(
        {
            "dc_key": ["202612345678"],
            "race": ["B"],
            "sex": ["M"],
            "fatal": [False],
            "date": ["2026-08-01 12:30:00"],
            "age_group": ["18 to 30"],
            "has_court_case": [has_court_case],
            "age": [25.0],
            "street_name": [None],
            "block_number": [None],
            "zip_code": [None],
            "council_district": [None],
            "police_district": [None],
            "neighborhood": [None],
            "school_name": [None],
            "house_district": [None],
            "senate_district": [None],
            "segment_id": [None],
        },
        geometry=[Point(-75.1, 40.0)],
        crs="EPSG:4326",
    )


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


def test_boundary_join_rejects_unknown_coordinate_system(monkeypatch) -> None:
    """Spatial joins must not guess the coordinate system of source points."""
    raw = gpd.GeoDataFrame(geometry=[Point(-75.1, 40.0)])

    with pytest.raises(ValueError, match="known input coordinate system"):
        boundary_transform.join_with_boundary_datasets(raw)


def test_schema_boundary_preserves_unknown_court_search_result() -> None:
    result = core._validate_against_schema(_valid_schema_frame(pd.NA))

    assert pd.isna(result["has_court_case"].iloc[0])


def test_schema_boundary_does_not_publish_unexpected_raw_fields() -> None:
    raw = _valid_schema_frame(False).assign(unexpected_source_field="source-only")

    result = core._validate_against_schema(raw)

    assert "unexpected_source_field" not in result.columns


def test_schema_boundary_still_rejects_missing_required_fields() -> None:
    raw = _valid_schema_frame(False).drop(columns="sex")

    with pytest.raises(ValueError, match=r"Missing columns for schema validation: \['sex'\]"):
        core._validate_against_schema(raw)


def test_unversioned_court_flags_keep_true_but_invalidate_false() -> None:
    result = sanitize_court_search_flags(
        pd.DataFrame(
            {
                "dc_key": ["1", "2", "3"],
                "has_court_case": [True, False, pd.NA],
            }
        )
    ).set_index("dc_key")["has_court_case"]

    assert bool(result["1"]) is True
    assert pd.isna(result["2"])
    assert pd.isna(result["3"])
    assert str(result.dtype) == "boolean"


def test_mixed_court_flag_versions_preserve_only_v2_false() -> None:
    result = sanitize_court_search_flags(
        pd.DataFrame(
            {
                "dc_key": ["1", "2", "3", "4"],
                "has_court_case": ["True", "False", "False", "False"],
                "court_search_semantics_version": [pd.NA, 2, 1, pd.NA],
            }
        )
    ).set_index("dc_key")["has_court_case"]

    assert bool(result["1"]) is True
    assert bool(result["2"]) is False
    assert pd.isna(result["3"])
    assert pd.isna(result["4"])


@pytest.mark.parametrize("value", [0, 1, "false", "true"])
def test_schema_boundary_rejects_coercive_court_search_values(value: object) -> None:
    with pytest.raises(ValueError, match="failed schema validation"):
        core._validate_against_schema(_valid_schema_frame(value))


def test_clean_shootings_keeps_post_scrape_incident_unknown(monkeypatch) -> None:
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
        },
        geometry=[Point(-75.1, 40.0), Point(-75.2, 40.1)],
        crs="EPSG:4326",
    )
    monkeypatch.setattr(core, "join_with_boundary_datasets", lambda df: df)
    monkeypatch.setattr(core, "join_with_street_blocks", lambda df, **_kwargs: df)
    courts_flags = pd.DataFrame(
        {
            "dc_key": ["1"],
            "has_court_case": [True],
            "court_search_semantics_version": [2],
        }
    )
    monkeypatch.setattr(core, "load_courts_flags", lambda **_kwargs: courts_flags)
    monkeypatch.setattr(
        core,
        "load_courts_metadata",
        lambda **_kwargs: {
            "publication_contract_version": 2,
            "run_id": "run-full",
            "selection_mode": "full",
            "coverage_complete": True,
            "candidate_count": 1,
            "input_count": 1,
            "result_count": 1,
            "missing_result_count": 0,
            "extra_result_count": 0,
            "flags_row_count": 1,
            "flags_sha256": court_flags_sha256(courts_flags),
            "court_search_semantics_version": 2,
            "result_conflict_policy_version": 1,
            "result_conflict_count": 0,
            "resolved_result_conflict_count": 0,
            "unresolved_result_conflict_count": 0,
            "invalid_result_conflict_resolution_count": 0,
            "result_conflict_evidence_sha256": "a" * 64,
        },
    )
    monkeypatch.setattr(core, "_validate_against_schema", lambda df: df)

    result = core.clean_shootings(object(), raw, ignore_checks=True)  # ty: ignore[invalid-argument-type]

    assert result["fatal"].tolist() == [False, True]
    assert result["inside"].tolist() == [False, True]
    assert result["outside"].tolist() == [True, False]
    assert result["latino"].tolist() == [False, True]
    assert result["race"].tolist() == ["W", "H"]
    assert bool(result.loc[result["dc_key"] == "1", "has_court_case"].iloc[0]) is True
    assert pd.isna(result.loc[result["dc_key"] == "2", "has_court_case"].iloc[0])
