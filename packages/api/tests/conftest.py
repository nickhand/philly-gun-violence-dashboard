"""Shared fixtures for API tests.

Env vars are set at module level so they're in place before any
settings singletons are instantiated during collection.
"""

import hashlib
import io
import json
import os

os.environ.setdefault("ENV", "prod")  # skip .env file lookup
os.environ.setdefault("AWS_BUCKET_NAME", "test-bucket")
os.environ.setdefault("AWS_REGION", "us-east-1")

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
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
                "fatal": False,
                "has_court_case": None,
                "sex": "M",
                "race": "B",
                "age_group": "18 to 30",
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
                "segment_id": "12345",
            },
        }
    ],
}

BOUNDARY_JOIN_FIELDS = {
    "city_limits": None,
    "council_districts": "council_district",
    "neighborhoods": "neighborhood",
    "pa_house_districts": "house_district",
    "pa_senate_districts": "senate_district",
    "police_districts": "police_district",
    "school_catchments": "school_name",
    "zip_codes": "zip_code",
}
BOUNDARY_GEOJSON = {
    dataset: {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[-75.2, 39.9], [-75.1, 39.9], [-75.1, 40.0], [-75.2, 39.9]]],
                },
                "properties": {} if field is None else {field: f"test-{dataset}"},
            }
        ],
    }
    for dataset, field in BOUNDARY_JOIN_FIELDS.items()
}
BOUNDARY_BODIES = {
    dataset: json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    for dataset, value in BOUNDARY_GEOJSON.items()
}
BOUNDARY_CHECKSUMS = {
    dataset: hashlib.sha256(body).hexdigest() for dataset, body in BOUNDARY_BODIES.items()
}
BOUNDARY_RELEASE_DESCRIPTOR = json.dumps(
    {
        "schema_version": 1,
        "datasets": BOUNDARY_CHECKSUMS,
    },
    sort_keys=True,
    separators=(",", ":"),
).encode()
BOUNDARY_RELEASE_ID = hashlib.sha256(BOUNDARY_RELEASE_DESCRIPTOR).hexdigest()
BOUNDARY_KEYS = {
    dataset: f"reference/boundaries/releases/{BOUNDARY_RELEASE_ID}/{dataset}.geojson"
    for dataset in BOUNDARY_GEOJSON
}
BOUNDARIES_MANIFEST: dict[str, Any] = {
    "schema_version": 1,
    "version": f"sha256:{BOUNDARY_RELEASE_ID}",
    "datasets": {
        dataset: {"key": BOUNDARY_KEYS[dataset], "sha256": BOUNDARY_CHECKSUMS[dataset]}
        for dataset in BOUNDARY_GEOJSON
    },
}

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
    for dataset, value in BOUNDARY_GEOJSON.items():
        if dataset in name:
            return value
    return {}


@pytest.fixture(scope="module")
def client():
    """TestClient with mocked S3. Module-scoped so startup runs once per file."""
    from app.main import app

    mock_s3 = MagicMock()

    def object_not_found(operation: str) -> ClientError:
        return ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "Not found"}},
            operation,
        )

    def get_object(*, Bucket: str, Key: str):
        del Bucket
        if Key == "public/downloads/manifest.json":
            body = json.dumps(
                {
                    "schema_version": 2,
                    "version": f"sha256:{'a' * 64}",
                    "published_at": "2023-01-16T00:00:00Z",
                    "downloads": [],
                }
            ).encode()
            return {"Body": io.BytesIO(body), "ETag": '"public-manifest-etag"'}
        if Key == "reference/boundaries_release.json":
            body = json.dumps(BOUNDARIES_MANIFEST, separators=(",", ":")).encode()
            return {"Body": io.BytesIO(body), "ETag": '"boundaries-manifest-etag"'}
        if Key.endswith("/streets/street_blocks.geojson"):
            body = json.dumps(STREETS_GEOJSON, separators=(",", ":")).encode()
            return {"Body": io.BytesIO(body), "ETag": '"streets-etag"'}
        for dataset, boundary_key in BOUNDARY_KEYS.items():
            if Key == boundary_key:
                return {
                    "Body": io.BytesIO(BOUNDARY_BODIES[dataset]),
                    "ETag": f'"{dataset}-etag"',
                }
        if Key.endswith("/homicides/release.json"):
            raise object_not_found("GetObject")
        raise AssertionError(f"Unexpected direct S3 object read: {Key}")

    def head_object(*, Bucket: str, Key: str):
        del Bucket
        if Key.endswith("/homicides/release.json"):
            raise object_not_found("HeadObject")
        if Key == "public/downloads/manifest.json":
            return {"ETag": '"public-manifest-etag"'}
        if Key == "reference/boundaries_release.json":
            return {"ETag": '"boundaries-manifest-etag"'}
        return {"ETag": f'"etag-{Key}"'}

    mock_s3.get_object.side_effect = get_object
    mock_s3.head_object.side_effect = head_object

    with (
        patch("app.main.make_s3_client", return_value=mock_s3),
        patch("app.data_loader.read_processed_geojson_json", side_effect=_mock_read_geojson),
        patch("app.data_loader.read_processed_json", side_effect=_mock_read_json),
        patch("app.data_loader.read_reference_json", side_effect=_mock_read_reference),
        patch("app.routers.meta.read_processed_json", side_effect=_mock_meta_read_json),
        TestClient(app) as c,
    ):
        yield c
