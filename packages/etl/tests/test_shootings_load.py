"""Tests for shooting-victim dataset outputs."""

import csv
import io
from typing import Any, cast

import geopandas as gpd
import pytest
from mypy_boto3_s3.client import S3Client
from shapely.geometry import Point

from dashboard_utils.models.shootings import ShootingVictimsSchema
from etl.shootings import load


class RecordingS3:
    """Small S3 stand-in that records object writes."""

    def __init__(self) -> None:
        self.puts: list[dict[str, Any]] = []

    def put_object(self, **kwargs: Any) -> None:
        self.puts.append(kwargs)


def _cleaned_shootings() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "dc_key": ["123", "456"],
            "race": ["B", "Other/Unknown"],
            "sex": ["M", "F"],
            "fatal": [False, True],
            "date": ["2026-08-01 12:30:00", "2026-08-02 00:00:00"],
            "age_group": ["18 to 30", "Unknown"],
            "has_court_case": [True, False],
            "age": [25.0, None],
            "street_name": ["MARKET ST", None],
            "block_number": [100, None],
            "zip_code": ["19106", None],
            "council_district": ["1", None],
            "police_district": ["6", None],
            "neighborhood": ["Old City", None],
            "school_name": ["Example School", None],
            "house_district": ["175", None],
            "senate_district": ["1", None],
            "segment_id": ["789", None],
        },
        geometry=[Point(-75.145, 39.95), Point()],
        crs="EPSG:4326",
    )


def test_write_shootings_dataset_adds_stable_public_csv(monkeypatch) -> None:
    internal_writes: list[tuple[str, gpd.GeoDataFrame, object]] = []
    publication_calls: list[tuple[str, object]] = []
    geographic_downloads = {"test": {"type": "FeatureCollection", "features": []}}
    prepared_publication = object()
    prepared_csv_body = b""

    def record_processed_write(
        name: str,
        df: gpd.GeoDataFrame,
        *,
        s3: object,
    ) -> None:
        internal_writes.append((name, df, s3))

    monkeypatch.setattr(load, "write_processed_geojson", record_processed_write)
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

    def prepare_publication(body: bytes, downloads: object) -> object:
        nonlocal prepared_csv_body
        prepared_csv_body = body
        publication_calls.append(("prepare", downloads))
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
        "write_public_download_manifest",
        lambda s3, publication: publication_calls.append(("manifest", publication)),
    )
    fake_s3 = RecordingS3()
    cleaned = _cleaned_shootings()

    load.write_shootings_dataset(cast(S3Client, fake_s3), cleaned)

    assert internal_writes == [("shootings", cleaned, fake_s3)]
    assert publication_calls == [
        ("validate", geographic_downloads),
        ("prepare", geographic_downloads),
        ("artifacts", prepared_publication),
        ("manifest", prepared_publication),
    ]
    assert fake_s3.puts == []

    rows = list(csv.DictReader(io.StringIO(prepared_csv_body.decode("utf-8"))))
    assert len(rows) == 2
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
    assert "geometry" not in rows[0]


def test_write_shootings_dataset_prepares_every_public_file_before_writing(monkeypatch) -> None:
    internal_writes: list[str] = []
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
        lambda body, refs: (_ for _ in ()).throw(ValueError("invalid public artifact")),
    )
    monkeypatch.setattr(
        load,
        "write_processed_geojson",
        lambda name, df, *, s3: internal_writes.append(name),
    )
    monkeypatch.setattr(
        load,
        "write_public_download_artifacts",
        lambda s3, publication: public_writes.append(publication),
    )
    monkeypatch.setattr(load, "write_public_download_manifest", lambda s3, publication: None)

    with pytest.raises(ValueError, match="invalid public artifact"):
        load.write_shootings_dataset(cast(S3Client, object()), cleaned)

    assert internal_writes == []
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
        lambda body, refs: publication,
    )
    monkeypatch.setattr(
        load,
        "write_public_download_artifacts",
        lambda s3, value: events.append("artifacts"),
    )
    monkeypatch.setattr(
        load,
        "write_processed_geojson",
        lambda name, df, *, s3: events.append("processed"),
    )
    monkeypatch.setattr(
        load,
        "write_public_download_manifest",
        lambda s3, value: events.append("manifest"),
    )

    load.write_shootings_dataset(cast(S3Client, object()), cleaned)

    assert events == ["artifacts", "processed", "manifest"]


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
        lambda body, refs: object(),
    )

    def fail_artifacts(s3: object, publication: object) -> None:
        raise RuntimeError("artifact upload failed")

    monkeypatch.setattr(load, "write_public_download_artifacts", fail_artifacts)
    monkeypatch.setattr(
        load,
        "write_processed_geojson",
        lambda name, df, *, s3: events.append("processed"),
    )
    monkeypatch.setattr(
        load,
        "write_public_download_manifest",
        lambda s3, value: events.append("manifest"),
    )

    with pytest.raises(RuntimeError, match="artifact upload failed"):
        load.write_shootings_dataset(cast(S3Client, object()), cleaned)

    assert events == []


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
