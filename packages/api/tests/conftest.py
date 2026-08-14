"""Shared fixtures for API tests.

Env vars are set at module level so they're in place before any
settings singletons are instantiated during collection.
"""

import os

os.environ.setdefault("ENV", "prod")  # skip .env file lookup
os.environ.setdefault("AWS_BUCKET_NAME", "test-bucket")
os.environ.setdefault("AWS_REGION", "us-east-1")

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Minimal fixture data that satisfies each loader's parsing logic
SHOOTINGS_GEOJSON: dict[str, Any] = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-75.1234, 39.9876]},
            "properties": {
                "dc_key": "202300001",
                "date": "2023-01-15 14:30:00",
                "fatal": 0,
                "sex": "M",
                "age": 25,
                "race": "B",
                "wound": "Graze",
                "outside_city": 0,
                "officer_involved": 0,
                "offender_injured": 0,
                "offender_deceased": 0,
                "location": "TEST LOCATION",
                "lat": 39.9876,
                "lng": -75.1234,
                "segment_id": "12345",
            },
        }
    ],
}

BOUNDARIES_MANIFEST: dict[str, Any] = {
    "datasets": {"neighborhoods": "reference/neighborhoods.json"}
}

NEIGHBORHOODS_GEOJSON: dict[str, Any] = {"type": "FeatureCollection", "features": []}

STREETS_GEOJSON: dict[str, Any] = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[-75.1, 39.9], [-75.2, 39.8]]},
            "properties": {
                "segment_id": "12345",
                "street_name": "TEST ST",
                "block_number": 1200,
                "block_label": "1200 BLOCK TEST ST",
            },
        }
    ],
}

HOMICIDES_TOTALS: dict[str, Any] = {
    "2023": {"annual": 500, "ytd": 450},
    "2024": {"annual": 480, "ytd": 400},
}


SHOOTINGS_META_SAMPLE: dict[str, Any] = {
    "last_updated": "2023-01-16T00:00:00Z",
    "data_through": "2023-01-15",
}

HOMICIDES_META_SAMPLE: dict[str, Any] = {
    "last_updated": "2023-01-17T00:00:00Z",
    "data_through": "2023-01-16",
}


def _mock_meta_read_json(name: str, s3: Any = None) -> dict[str, Any]:
    if name == "shootings_meta":
        return SHOOTINGS_META_SAMPLE
    if name == "homicides_meta":
        return HOMICIDES_META_SAMPLE
    return {}


def _mock_read_geojson(name: str, s3: Any = None) -> dict[str, Any]:
    if name == "shootings":
        return SHOOTINGS_GEOJSON
    if name == "street_blocks":
        return STREETS_GEOJSON
    return {"type": "FeatureCollection", "features": []}


def _mock_read_json(name: str, s3: Any = None) -> dict[str, Any]:
    if name == "homicides_totals":
        return HOMICIDES_TOTALS
    if name == "shootings_meta":
        return SHOOTINGS_META_SAMPLE
    if name == "homicides_meta":
        return HOMICIDES_META_SAMPLE
    return {}


def _mock_read_reference(name: str, s3: Any = None) -> dict[str, Any]:
    if "boundaries_manifest" in name:
        return BOUNDARIES_MANIFEST
    if "neighborhoods" in name:
        return NEIGHBORHOODS_GEOJSON
    return {}


@pytest.fixture(scope="module")
def client():
    """TestClient with mocked S3. Module-scoped so startup runs once per file."""
    from app.main import app

    mock_s3 = MagicMock()
    mock_s3.head_object.return_value = {"ETag": '"test-etag-abc123"'}

    with (
        patch("app.main.make_s3_client", return_value=mock_s3),
        patch("app.data_loader.read_processed_geojson_json", side_effect=_mock_read_geojson),
        patch("app.data_loader.read_processed_json", side_effect=_mock_read_json),
        patch("app.data_loader.read_reference_json", side_effect=_mock_read_reference),
        patch("app.routers.meta.read_processed_json", side_effect=_mock_meta_read_json),
        TestClient(app) as c,
    ):
        yield c
