"""Unit tests for pure data-loader functions (no S3 required)."""

import hashlib
import json
import os

os.environ.setdefault("ENV", "prod")
os.environ.setdefault("AWS_BUCKET_NAME", "test-bucket")
os.environ.setdefault("AWS_REGION", "us-east-1")

import pytest

from app.data_loader import (
    _build_shooting_version,
    _compute_version_hash,
    _decode_json,
    _extract_year,
    _flatten_feature_to_row,
    _validate_freshness,
    _validate_homicide_totals,
)

SAMPLE_FEATURE = {
    "type": "Feature",
    "geometry": {"type": "Point", "coordinates": [-75.1234, 39.9876]},
    "properties": {
        "dc_key": "202300001",
        "race": "B",
        "sex": "M",
        "fatal": False,
        "date": "2023-01-15 14:30:00",
        "age_group": "18 to 30",
        "has_court_case": None,
        "age": 25.0,
        "street_name": None,
        "block_number": None,
        "zip_code": None,
        "council_district": None,
        "police_district": None,
        "neighborhood": None,
        "school_name": None,
        "house_district": None,
        "senate_district": None,
        "segment_id": None,
    },
}


def test_json_trust_boundary_rejects_duplicate_fields() -> None:
    with pytest.raises(ValueError, match="duplicate field 'version'"):
        _decode_json(b'{"version":1,"version":2}', label="Test pointer")


class TestFlattenFeatureToRow:
    def test_coordinates_extracted(self):
        row = _flatten_feature_to_row(SAMPLE_FEATURE, 0)
        assert row["lon"] == pytest.approx(-75.1234)
        assert row["lat"] == pytest.approx(39.9876)

    def test_properties_included(self):
        row = _flatten_feature_to_row(SAMPLE_FEATURE, 0)
        assert row["dc_key"] == "202300001"
        assert row["fatal"] is False

    def test_unique_id_is_index(self):
        row = _flatten_feature_to_row(SAMPLE_FEATURE, 7)
        assert row["unique_id"] == 7

    def test_date_in_ms(self):
        # 2023-01-15 14:30:00 UTC = 1673793000000 ms
        row = _flatten_feature_to_row(SAMPLE_FEATURE, 0)
        assert row["dateInMs"] == 1673793000000

    def test_time_in_ms(self):
        # 14:30:00 = (14*3600 + 30*60) * 1000 = 52200000 ms
        row = _flatten_feature_to_row(SAMPLE_FEATURE, 0)
        assert row["timeInMs"] == 52200000

    def test_weekday_sunday_zero(self):
        # 2023-01-15 is a Sunday; frontend expects 0 for Sunday
        row = _flatten_feature_to_row(SAMPLE_FEATURE, 0)
        assert row["weekday"] == 0

    def test_weekday_monday_one(self):
        feature = {
            **SAMPLE_FEATURE,
            "properties": {
                **SAMPLE_FEATURE["properties"],
                "date": "2023-01-16 08:00:00",
            },
        }
        row = _flatten_feature_to_row(feature, 0)
        assert row["weekday"] == 1

    def test_year_extracted(self):
        row = _flatten_feature_to_row(SAMPLE_FEATURE, 0)
        assert row["year"] == 2023

    @pytest.mark.parametrize(
        "field",
        ["lon", "lat", "dateInMs", "timeInMs", "weekday", "year", "unique_id"],
    )
    def test_source_properties_cannot_override_derived_fields(self, field: str):
        feature = {
            **SAMPLE_FEATURE,
            "properties": {**SAMPLE_FEATURE["properties"], field: "untrusted"},
        }

        with pytest.raises(ValueError, match="extra_forbidden"):
            _flatten_feature_to_row(feature, 7)

    def test_validated_properties_are_normalized_before_publication(self):
        feature = {
            **SAMPLE_FEATURE,
            "properties": {**SAMPLE_FEATURE["properties"], "dc_key": "  202300001  "},
        }

        assert _flatten_feature_to_row(feature, 0)["dc_key"] == "202300001"

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("fatal", 0),
            ("fatal", "false"),
            ("age", "25"),
            ("block_number", "1200"),
        ],
    )
    def test_property_schema_rejects_coercive_values(self, field: str, value: object):
        feature = {
            **SAMPLE_FEATURE,
            "properties": {**SAMPLE_FEATURE["properties"], field: value},
        }

        with pytest.raises(ValueError, match="property schema validation"):
            _flatten_feature_to_row(feature, 0)

    def test_property_schema_rejects_malformed_domain_values(self):
        feature = {
            **SAMPLE_FEATURE,
            "properties": {**SAMPLE_FEATURE["properties"], "race": "not-a-category"},
        }

        with pytest.raises(ValueError, match="property schema validation"):
            _flatten_feature_to_row(feature, 0)

    def test_invalid_date_is_rejected_at_the_dataset_boundary(self):
        feature = {
            **SAMPLE_FEATURE,
            "properties": {**SAMPLE_FEATURE["properties"], "date": "not-a-date"},
        }
        with pytest.raises(ValueError, match="invalid date"):
            _flatten_feature_to_row(feature, 0)

    def test_missing_geometry_yields_none_coords(self):
        feature = {
            **SAMPLE_FEATURE,
            "geometry": None,
            "properties": {**SAMPLE_FEATURE["properties"], "dc_key": "202300002"},
        }
        row = _flatten_feature_to_row(feature, 0)
        assert row["lon"] is None
        assert row["lat"] is None


class TestComputeVersionHash:
    def test_returns_12_chars(self):
        assert len(_compute_version_hash({"a": 1})) == 12

    def test_deterministic(self):
        data = {"key": "value", "nested": [1, 2, 3]}
        assert _compute_version_hash(data) == _compute_version_hash(data)

    def test_matches_sha256(self):
        data = {"a": 1}
        content = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        expected = hashlib.sha256(content).hexdigest()[:12]
        assert _compute_version_hash(data) == expected

    def test_order_independent(self):
        # sort_keys=True means key order doesn't change the hash
        assert _compute_version_hash({"b": 2, "a": 1}) == _compute_version_hash({"a": 1, "b": 2})


class TestExtractYear:
    def test_valid_date(self):
        assert _extract_year("2023-01-15 14:30:00") == 2023

    def test_none_returns_none(self):
        assert _extract_year(None) is None

    def test_empty_string_returns_none(self):
        assert _extract_year("") is None

    def test_invalid_format_returns_none(self):
        assert _extract_year("not-a-date") is None


def test_shootings_snapshot_rejects_nonfinite_json_numbers():
    invalid = {
        "type": "FeatureCollection",
        "features": [
            {
                **SAMPLE_FEATURE,
                "properties": {**SAMPLE_FEATURE["properties"], "age": float("nan")},
            }
        ],
    }

    with pytest.raises(ValueError, match="non-JSON value"):
        _build_shooting_version(invalid, {"data_through": "2023-01-15"})


@pytest.mark.parametrize("value", [True, False, None])
def test_court_search_result_preserves_three_wire_states(value: bool | None):
    feature = {
        **SAMPLE_FEATURE,
        "properties": {**SAMPLE_FEATURE["properties"], "has_court_case": value},
    }

    assert _flatten_feature_to_row(feature, 0)["has_court_case"] is value


@pytest.mark.parametrize("value", [0, 1, "false", "true", ""])
def test_court_search_result_rejects_coercive_wire_values(value: object):
    feature = {
        **SAMPLE_FEATURE,
        "properties": {**SAMPLE_FEATURE["properties"], "has_court_case": value},
    }

    with pytest.raises(ValueError, match="property schema validation"):
        _flatten_feature_to_row(feature, 0)


def test_court_search_result_is_required_on_every_record():
    properties = {**SAMPLE_FEATURE["properties"]}
    del properties["has_court_case"]

    with pytest.raises(ValueError, match="property schema validation"):
        _flatten_feature_to_row({**SAMPLE_FEATURE, "properties": properties}, 0)


@pytest.mark.parametrize(
    "data_through",
    ["2023-01-15T00:00:00Z", "20230115", "2023-01-15garbage"],
)
def test_freshness_requires_an_exact_iso_date(data_through: str):
    with pytest.raises(ValueError, match="data_through"):
        _validate_freshness({"data_through": data_through}, label="Test metadata")


@pytest.mark.parametrize(
    "field,value",
    [("annual", True), ("annual", "500"), ("ytd", False), ("ytd", "100")],
)
def test_homicide_totals_reject_coercive_numbers(field: str, value: object):
    record = {"annual": 500, "ytd": 100}
    record[field] = value

    with pytest.raises(ValueError, match="schema validation"):
        _validate_homicide_totals({"2026": record})


def test_homicide_totals_returns_a_normalized_copy():
    source = {"2026": {"annual": 500, "ytd": 100}}

    result = _validate_homicide_totals(source)
    source["2026"]["annual"] = 999

    assert result == {"2026": {"annual": 500, "ytd": 100}}
