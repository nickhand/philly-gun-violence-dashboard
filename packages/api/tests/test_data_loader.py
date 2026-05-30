"""Unit tests for pure data-loader functions (no S3 required)."""

import hashlib
import json
import os

os.environ.setdefault("ENV", "prod")
os.environ.setdefault("AWS_BUCKET_NAME", "test-bucket")
os.environ.setdefault("AWS_REGION", "us-east-1")

import pytest

from app.data_loader import _compute_version_hash, _extract_year, _flatten_feature_to_row

SAMPLE_FEATURE = {
    "type": "Feature",
    "geometry": {"type": "Point", "coordinates": [-75.1234, 39.9876]},
    "properties": {
        "dc_key": "202300001",
        "date": "2023-01-15 14:30:00",
        "fatal": 0,
        "sex": "M",
    },
}


class TestFlattenFeatureToRow:
    def test_coordinates_extracted(self):
        row = _flatten_feature_to_row(SAMPLE_FEATURE, 0)
        assert row["lon"] == pytest.approx(-75.1234)
        assert row["lat"] == pytest.approx(39.9876)

    def test_properties_included(self):
        row = _flatten_feature_to_row(SAMPLE_FEATURE, 0)
        assert row["dc_key"] == "202300001"
        assert row["fatal"] == 0

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
        feature = {**SAMPLE_FEATURE, "properties": {**SAMPLE_FEATURE["properties"], "date": "2023-01-16 08:00:00"}}
        row = _flatten_feature_to_row(feature, 0)
        assert row["weekday"] == 1

    def test_year_extracted(self):
        row = _flatten_feature_to_row(SAMPLE_FEATURE, 0)
        assert row["year"] == 2023

    def test_invalid_date_yields_none_fields(self):
        feature = {**SAMPLE_FEATURE, "properties": {"date": "not-a-date"}}
        row = _flatten_feature_to_row(feature, 0)
        assert row["dateInMs"] is None
        assert row["timeInMs"] is None
        assert row["weekday"] is None
        assert row["year"] is None

    def test_missing_geometry_yields_none_coords(self):
        feature = {"type": "Feature", "geometry": None, "properties": {"date": "2023-01-15 00:00:00"}}
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
        from app.data_loader import _extract_year
        assert _extract_year("2023-01-15 14:30:00") == 2023

    def test_none_returns_none(self):
        from app.data_loader import _extract_year
        assert _extract_year(None) is None

    def test_empty_string_returns_none(self):
        from app.data_loader import _extract_year
        assert _extract_year("") is None

    def test_invalid_format_returns_none(self):
        from app.data_loader import _extract_year
        assert _extract_year("not-a-date") is None
