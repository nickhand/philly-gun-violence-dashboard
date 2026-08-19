"""Tests for shooting-victim dataset outputs."""

import csv
import io
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import geopandas as gpd
import pandas as pd
import pytest
from mypy_boto3_s3.client import S3Client
from shapely.geometry import Point

from dashboard_utils.config import get_s3_settings
from dashboard_utils.models.shootings import ShootingVictimsSchema
from etl.shootings import load
from etl.utils.release_pointer import ReleaseOrder, StablePointerSnapshot

previous_application_data = load._previous_application_data
RUN_STARTED_AT = datetime(2026, 8, 18, 12, tzinfo=UTC)


class RecordingS3:
    """Small S3 stand-in that records object writes."""

    def __init__(self) -> None:
        self.puts: list[dict[str, Any]] = []

    def put_object(self, **kwargs: Any) -> None:
        self.puts.append(kwargs)


def _captured_pointer(manifest: dict[str, object]) -> StablePointerSnapshot:
    return StablePointerSnapshot(
        etag='"captured"',
        body=json.dumps(manifest).encode(),
        version=f"sha256:{'f' * 64}",
        order=ReleaseOrder(data_through=None, run_started_at=RUN_STARTED_AT),
    )


def _cleaned_shootings() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "dc_key": ["123", "456", "789"],
            "race": ["B", "Other/Unknown", "W"],
            "sex": ["M", "F", "M"],
            "fatal": [False, True, False],
            "date": [
                "2026-08-01 12:30:00",
                "2026-08-02 00:00:00",
                "2026-08-03 08:00:00",
            ],
            "age_group": ["18 to 30", "Unknown", "31 to 45"],
            "has_court_case": pd.array([True, False, pd.NA], dtype="boolean"),
            "age": [25.0, None, 36.0],
            "street_name": ["MARKET ST", None, "BROAD ST"],
            "block_number": [100, None, 200],
            "zip_code": ["19106", None, "19107"],
            "council_district": ["1", None, "1"],
            "police_district": ["6", None, "6"],
            "neighborhood": ["Old City", None, "Center City"],
            "school_name": ["Example School", None, "Other School"],
            "house_district": ["175", None, "182"],
            "senate_district": ["1", None, "1"],
            "segment_id": ["789", None, "1011"],
        },
        geometry=[Point(-75.145, 39.95), Point(), Point(-75.16, 39.96)],
        crs="EPSG:4326",
    )


def _application_pointer(data_sha: str, metadata_sha: str, release: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "data": {
            "key": f"processed/shootings/releases/{release}/shootings.geojson",
            "sha256": data_sha,
        },
        "metadata": {
            "key": f"processed/shootings/releases/{release}/meta.json",
            "sha256": metadata_sha,
        },
    }


def test_metadata_only_release_preserves_last_distinct_application_pointer() -> None:
    current = _application_pointer("b" * 64, "c" * 64, "current")
    previous = _application_pointer("a" * 64, "d" * 64, "previous")
    pointer = _captured_pointer(
        {
            "application_data": current,
            "previous_application_data": previous,
        }
    )

    result = previous_application_data(
        pointer,
        new_data_sha256="b" * 64,
    )

    assert result == previous


def test_changed_data_moves_current_application_pointer_to_n_minus_one() -> None:
    current = _application_pointer("b" * 64, "c" * 64, "current")
    previous = _application_pointer("a" * 64, "d" * 64, "previous")
    pointer = _captured_pointer(
        {
            "application_data": current,
            "previous_application_data": previous,
        }
    )

    result = previous_application_data(
        pointer,
        new_data_sha256="e" * 64,
    )

    assert result == current


def test_first_metadata_only_release_does_not_create_duplicate_n_minus_one() -> None:
    current = _application_pointer("b" * 64, "c" * 64, "current")
    pointer = _captured_pointer({"application_data": current})

    result = previous_application_data(
        pointer,
        new_data_sha256="b" * 64,
    )

    assert result is None


def test_write_shootings_dataset_adds_stable_public_csv(monkeypatch) -> None:
    publication_calls: list[tuple[str, object]] = []
    geographic_downloads = {"test": {"type": "FeatureCollection", "features": []}}
    prepared_publication = object()
    prepared_csv_body = b""

    monkeypatch.setattr(
        load,
        "load_geographic_reference_downloads",
        lambda s3: geographic_downloads,
    )
    monkeypatch.setattr(
        load,
        "validate_geographic_reference_coverage",
        lambda df, downloads: publication_calls.append(("validate", downloads)),
    )

    def prepare_publication(body: bytes, downloads: object, **kwargs: object) -> object:
        nonlocal prepared_csv_body
        prepared_csv_body = body
        publication_calls.append(("prepare", downloads))
        assert isinstance(kwargs["application_data_body"], bytes)
        assert isinstance(kwargs["application_metadata_body"], bytes)
        return prepared_publication

    monkeypatch.setattr(
        load,
        "prepare_public_download_publication",
        prepare_publication,
    )
    monkeypatch.setattr(
        load,
        "write_public_download_artifacts",
        lambda s3, publication: publication_calls.append(("artifacts", publication)),
    )
    monkeypatch.setattr(
        load,
        "_write_application_release",
        lambda s3, publication: publication_calls.append(("application", publication)),
    )
    monkeypatch.setattr(
        load,
        "write_public_download_manifest",
        lambda s3, publication, **kwargs: publication_calls.append(("manifest", publication)),
    )
    monkeypatch.setattr(
        load,
        "_write_compatibility_mirrors",
        lambda s3, publication: publication_calls.append(("compatibility", publication)),
    )
    fake_s3 = RecordingS3()
    cleaned = _cleaned_shootings()

    load.write_shootings_dataset(
        cast(S3Client, fake_s3),
        cleaned,
        {"data_through": "2026-08-02"},
        expected_pointer=StablePointerSnapshot.missing(),
        run_started_at=RUN_STARTED_AT,
    )

    assert publication_calls == [
        ("validate", geographic_downloads),
        ("prepare", geographic_downloads),
        ("artifacts", prepared_publication),
        ("application", prepared_publication),
        ("manifest", prepared_publication),
        ("compatibility", prepared_publication),
    ]
    assert fake_s3.puts == []

    rows = list(csv.DictReader(io.StringIO(prepared_csv_body.decode("utf-8"))))
    assert len(rows) == 3
    assert list(rows[0]) == [*ShootingVictimsSchema.model_fields, "latitude", "longitude"]
    assert rows[0]["dc_key"] == "123"
    assert rows[0]["fatal"] == "false"
    assert rows[0]["has_court_case"] == "true"
    assert rows[0]["latitude"] == "39.95"
    assert rows[0]["longitude"] == "-75.145"
    assert rows[1]["dc_key"] == "456"
    assert rows[1]["fatal"] == "true"
    assert rows[1]["has_court_case"] == "false"
    assert rows[1]["latitude"] == ""
    assert rows[1]["longitude"] == ""
    assert rows[2]["has_court_case"] == ""
    assert "geometry" not in rows[0]

    geojson = json.loads(load._shootings_geojson_body(cleaned))
    assert geojson["features"][0]["properties"]["has_court_case"] is True
    assert geojson["features"][1]["properties"]["has_court_case"] is False
    assert geojson["features"][2]["properties"]["has_court_case"] is None


def test_write_shootings_dataset_prepares_every_public_file_before_writing(monkeypatch) -> None:
    public_writes: list[object] = []
    cleaned = _cleaned_shootings()

    monkeypatch.setattr(
        load,
        "load_geographic_reference_downloads",
        lambda s3: {"loaded": True},
    )
    monkeypatch.setattr(load, "validate_geographic_reference_coverage", lambda df, refs: None)
    monkeypatch.setattr(
        load,
        "prepare_public_download_publication",
        lambda body, refs, **kwargs: (_ for _ in ()).throw(ValueError("invalid public artifact")),
    )
    monkeypatch.setattr(
        load,
        "write_public_download_artifacts",
        lambda s3, publication: public_writes.append(publication),
    )
    monkeypatch.setattr(
        load,
        "write_public_download_manifest",
        lambda s3, publication, **kwargs: None,
    )

    with pytest.raises(ValueError, match="invalid public artifact"):
        load.write_shootings_dataset(
            cast(S3Client, object()),
            cleaned,
            {"data_through": "2026-08-02"},
            expected_pointer=StablePointerSnapshot.missing(),
            run_started_at=RUN_STARTED_AT,
        )

    assert public_writes == []


def test_write_shootings_dataset_moves_manifest_only_after_processed_write(monkeypatch) -> None:
    events: list[str] = []
    cleaned = _cleaned_shootings()
    publication = object()

    monkeypatch.setattr(
        load,
        "load_geographic_reference_downloads",
        lambda s3: {"loaded": True},
    )
    monkeypatch.setattr(load, "validate_geographic_reference_coverage", lambda df, refs: None)
    monkeypatch.setattr(
        load,
        "prepare_public_download_publication",
        lambda body, refs, **kwargs: publication,
    )
    monkeypatch.setattr(
        load,
        "write_public_download_artifacts",
        lambda s3, value: events.append("artifacts"),
    )
    monkeypatch.setattr(
        load,
        "_write_application_release",
        lambda s3, value: events.append("application"),
    )
    monkeypatch.setattr(
        load,
        "write_public_download_manifest",
        lambda s3, value, **kwargs: events.append("manifest"),
    )
    monkeypatch.setattr(
        load,
        "_write_compatibility_mirrors",
        lambda s3, value: events.append("compatibility"),
    )

    load.write_shootings_dataset(
        cast(S3Client, object()),
        cleaned,
        {"data_through": "2026-08-02"},
        expected_pointer=StablePointerSnapshot.missing(),
        run_started_at=RUN_STARTED_AT,
    )

    assert events == ["artifacts", "application", "manifest", "compatibility"]


def test_failed_public_artifact_upload_does_not_write_processed_or_manifest(monkeypatch) -> None:
    events: list[str] = []
    cleaned = _cleaned_shootings()

    monkeypatch.setattr(
        load,
        "load_geographic_reference_downloads",
        lambda s3: {"loaded": True},
    )
    monkeypatch.setattr(load, "validate_geographic_reference_coverage", lambda df, refs: None)
    monkeypatch.setattr(
        load,
        "prepare_public_download_publication",
        lambda body, refs, **kwargs: object(),
    )

    def fail_artifacts(s3: object, publication: object) -> None:
        raise RuntimeError("artifact upload failed")

    monkeypatch.setattr(load, "write_public_download_artifacts", fail_artifacts)
    monkeypatch.setattr(
        load,
        "_write_application_release",
        lambda s3, value: events.append("application"),
    )
    monkeypatch.setattr(
        load,
        "write_public_download_manifest",
        lambda s3, value, **kwargs: events.append("manifest"),
    )
    monkeypatch.setattr(
        load,
        "_write_compatibility_mirrors",
        lambda s3, value: events.append("compatibility"),
    )

    with pytest.raises(RuntimeError, match="artifact upload failed"):
        load.write_shootings_dataset(
            cast(S3Client, object()),
            cleaned,
            {"data_through": "2026-08-02"},
            expected_pointer=StablePointerSnapshot.missing(),
            run_started_at=RUN_STARTED_AT,
        )

    assert events == []


def test_failed_pointer_write_does_not_mutate_legacy_mirrors(monkeypatch) -> None:
    events: list[str] = []
    cleaned = _cleaned_shootings()
    monkeypatch.setattr(load, "load_geographic_reference_downloads", lambda s3: {})
    monkeypatch.setattr(load, "validate_geographic_reference_coverage", lambda df, refs: None)
    monkeypatch.setattr(
        load,
        "prepare_public_download_publication",
        lambda body, refs, **kwargs: object(),
    )
    monkeypatch.setattr(load, "write_public_download_artifacts", lambda s3, value: None)
    monkeypatch.setattr(load, "_write_application_release", lambda s3, value: None)

    def fail_pointer(s3: object, publication: object, **kwargs: object) -> None:
        raise RuntimeError("pointer write failed")

    monkeypatch.setattr(load, "write_public_download_manifest", fail_pointer)
    monkeypatch.setattr(
        load,
        "_write_compatibility_mirrors",
        lambda s3, value: events.append("compatibility"),
    )

    with pytest.raises(RuntimeError, match="pointer write failed"):
        load.write_shootings_dataset(
            cast(S3Client, object()),
            cleaned,
            {"data_through": "2026-08-02"},
            expected_pointer=StablePointerSnapshot.missing(),
            run_started_at=RUN_STARTED_AT,
        )

    assert events == []


def test_compatibility_failure_is_reported_as_committed(monkeypatch) -> None:
    cleaned = _cleaned_shootings()
    publication = SimpleNamespace(release_id="release-1")
    monkeypatch.setattr(load, "load_geographic_reference_downloads", lambda s3: {})
    monkeypatch.setattr(load, "validate_geographic_reference_coverage", lambda df, refs: None)
    monkeypatch.setattr(
        load,
        "prepare_public_download_publication",
        lambda body, refs, **kwargs: publication,
    )
    monkeypatch.setattr(load, "write_public_download_artifacts", lambda s3, value: None)
    monkeypatch.setattr(load, "_write_application_release", lambda s3, value: None)
    monkeypatch.setattr(
        load,
        "write_public_download_manifest",
        lambda s3, value, **kwargs: None,
    )
    monkeypatch.setattr(
        load,
        "_write_compatibility_mirrors",
        lambda s3, value: (_ for _ in ()).throw(RuntimeError("mirror failed")),
    )

    with pytest.raises(load.ShootingsReleaseCommittedError, match="release-1 committed"):
        load.write_shootings_dataset(
            cast(S3Client, object()),
            cleaned,
            {"data_through": "2026-08-02"},
            expected_pointer=StablePointerSnapshot.missing(),
            run_started_at=RUN_STARTED_AT,
        )


def test_application_release_writes_immutable_objects_and_legacy_mirrors(monkeypatch) -> None:
    monkeypatch.setenv("S3_BUCKET", "test-bucket")
    monkeypatch.setenv("S3_PROCESSED_PREFIX", "processed")
    get_s3_settings.cache_clear()
    s3 = RecordingS3()
    publication = load.PublicDownloadPublication(
        release_id="a" * 64,
        artifacts=(),
        manifest_body=b"{}",
        application_data_body=b'{"type":"FeatureCollection","features":[]}',
        application_metadata_body=b'{"data_through":"2026-08-17"}',
    )

    load._write_application_release(cast(S3Client, s3), publication)
    load._write_compatibility_mirrors(cast(S3Client, s3), publication)

    keys = [put["Key"] for put in s3.puts]
    assert keys == [
        f"processed/shootings/releases/{'a' * 64}/shootings.geojson",
        f"processed/shootings/releases/{'a' * 64}/meta.json",
        "processed/shootings/shootings.geojson",
        "processed/shootings/meta.json",
    ]
    assert s3.puts[0]["CacheControl"] == "public,max-age=31536000,immutable"
    assert "CacheControl" not in s3.puts[-1]
    get_s3_settings.cache_clear()


def test_public_shootings_csv_excludes_browser_only_fields() -> None:
    cleaned = _cleaned_shootings().assign(
        dateInMs=1,
        lat=2,
        lon=3,
        timeInMs=4,
        unique_id=5,
        weekday=6,
        year=2026,
    )

    rows = list(csv.DictReader(io.StringIO(load._public_shootings_csv(cleaned))))

    assert rows
    for field in ("dateInMs", "lat", "lon", "timeInMs", "unique_id", "weekday", "year"):
        assert field not in rows[0]


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r"])
def test_public_shootings_csv_rejects_spreadsheet_formula_prefixes(prefix: str) -> None:
    cleaned = _cleaned_shootings()
    cleaned.loc[0, "street_name"] = f"{prefix}unsafe"

    with pytest.raises(ValueError, match="spreadsheet-formula prefix.*street_name"):
        load._public_shootings_csv(cleaned)
