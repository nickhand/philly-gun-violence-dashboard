"""Tests for curated public geographic reference downloads."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, cast

import pandas as pd
import pytest
from mypy_boto3_s3.client import S3Client

from etl import public_downloads


class RecordingS3:
    """Small S3 stand-in that records object writes."""

    def __init__(self) -> None:
        self.puts: list[dict[str, Any]] = []

    def put_object(self, **kwargs: Any) -> None:
        self.puts.append(kwargs)


class FailingS3(RecordingS3):
    """S3 stand-in that fails before a configured object can be written."""

    def __init__(self, *, fail_on_put: int) -> None:
        super().__init__()
        self.fail_on_put = fail_on_put

    def put_object(self, **kwargs: Any) -> None:
        if len(self.puts) + 1 == self.fail_on_put:
            raise RuntimeError("simulated upload failure")
        super().put_object(**kwargs)


def _collection(field: str, value: str) -> dict[str, object]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-75.16, 39.95]},
                "properties": {field: value},
            }
        ],
    }


def _matching_downloads() -> tuple[pd.DataFrame, dict[str, object]]:
    row: dict[str, str] = {}
    downloads: dict[str, object] = {}
    for item in public_downloads.GEOGRAPHIC_REFERENCE_DOWNLOADS:
        value = f"value-{item.dataset}"
        row[item.join_field] = value
        downloads[item.dataset] = _collection(item.join_field, value)
    return pd.DataFrame([row]), downloads


def test_manifest_describes_one_immutable_release_and_is_written_last(monkeypatch) -> None:
    shootings, downloads = _matching_downloads()
    fake_s3 = RecordingS3()
    csv_body = b"dc_key,zip_code\n123,19106\n"
    monkeypatch.setattr(
        public_downloads,
        "get_s3_settings",
        lambda: type("Settings", (), {"s3_bucket": "test-bucket"})(),
    )

    public_downloads.validate_geographic_reference_coverage(shootings, downloads)
    publication = public_downloads.prepare_public_download_publication(
        csv_body,
        downloads,
        published_at=datetime(2026, 8, 17, 15, 30, 45, tzinfo=UTC),
    )
    public_downloads.write_public_download_publication(
        cast(S3Client, fake_s3),
        publication,
    )

    assert len(publication.artifacts) == 9
    assert len(fake_s3.puts) == 10
    assert fake_s3.puts[-1]["Key"] == "public/downloads/manifest.json"

    manifest_put = fake_s3.puts[-1]
    assert manifest_put["Bucket"] == "test-bucket"
    assert manifest_put["ContentType"] == "application/json; charset=utf-8"
    assert manifest_put["CacheControl"] == public_downloads.PUBLIC_DOWNLOAD_MANIFEST_CACHE_CONTROL
    assert "ContentDisposition" not in manifest_put
    assert "ACL" not in manifest_put

    manifest = json.loads(manifest_put["Body"])
    assert manifest["schema_version"] == 2
    assert manifest["published_at"] == "2026-08-17T15:30:45Z"
    assert manifest["version"] == f"sha256:{publication.release_id}"
    assert len(publication.release_id) == 64
    assert len(manifest["downloads"]) == 9

    puts_by_key = {put["Key"]: put for put in fake_s3.puts[:-1]}
    for entry in manifest["downloads"]:
        key = f"public/downloads/{entry['path']}"
        put = puts_by_key[key]
        assert put["Bucket"] == "test-bucket"
        assert put["ContentType"] == entry["media_type"]
        assert put["ContentDisposition"] == f'attachment; filename="{entry["filename"]}"'
        assert put["CacheControl"] == public_downloads.PUBLIC_DOWNLOAD_RELEASE_CACHE_CONTROL
        assert len(put["Body"]) == entry["byte_size"]
        assert hashlib.sha256(put["Body"]).hexdigest() == entry["sha256"]
        assert entry["path"].startswith(f"releases/{publication.release_id}/")
        assert "ACL" not in put

    csv_entry = manifest["downloads"][0]
    assert csv_entry == {
        "id": "shooting_victims",
        "kind": "records",
        "label": "Philadelphia shooting-victim records",
        "filename": "philadelphia-shooting-victims.csv",
        "path": (f"releases/{publication.release_id}/philadelphia-shooting-victims.csv"),
        "media_type": "text/csv; charset=utf-8",
        "byte_size": len(csv_body),
        "sha256": hashlib.sha256(csv_body).hexdigest(),
        "row_count": 1,
    }
    csv_key = f"public/downloads/{csv_entry['path']}"
    assert puts_by_key[csv_key]["Body"] == csv_body

    expected_geography_paths = {
        f"releases/{publication.release_id}/geography/{item.filename}"
        for item in public_downloads.GEOGRAPHIC_REFERENCE_DOWNLOADS
    }
    assert {entry["path"] for entry in manifest["downloads"][1:]} == expected_geography_paths
    entries_by_id = {entry["id"]: entry for entry in manifest["downloads"]}
    for item in public_downloads.GEOGRAPHIC_REFERENCE_DOWNLOADS:
        entry = entries_by_id[item.dataset]
        assert entry["kind"] == "geography"
        assert entry["label"] == item.label
        assert entry["dataset"] == item.dataset
        assert entry["join_field"] == item.join_field
        assert entry["row_count"] == 1

    stable_data_keys = {
        "public/downloads/philadelphia-shooting-victims.csv",
        *{
            f"public/downloads/geography/{item.filename}"
            for item in public_downloads.GEOGRAPHIC_REFERENCE_DOWNLOADS
        },
    }
    assert puts_by_key.keys().isdisjoint(stable_data_keys)


def test_preparation_rejects_invalid_geojson_before_public_writes(monkeypatch) -> None:
    _, downloads = _matching_downloads()
    invalid = cast(dict[str, Any], downloads["zip_codes"])
    feature = cast(dict[str, Any], cast(list[Any], invalid["features"])[0])
    geometry = cast(dict[str, Any], feature["geometry"])
    geometry["coordinates"] = [float("nan"), 39.95]
    fake_s3 = RecordingS3()
    monkeypatch.setattr(
        public_downloads,
        "get_s3_settings",
        lambda: type("Settings", (), {"s3_bucket": "test-bucket"})(),
    )

    with pytest.raises(ValueError, match="zip_codes.*invalid geometry.*index 0"):
        publication = public_downloads.prepare_public_download_publication(b"header\n", downloads)
        public_downloads.write_public_download_publication(cast(S3Client, fake_s3), publication)

    assert fake_s3.puts == []


def test_publication_version_uses_artifact_content_not_timestamp() -> None:
    _, downloads = _matching_downloads()
    first = public_downloads.prepare_public_download_publication(
        b"header\n",
        downloads,
        published_at=datetime(2026, 8, 17, tzinfo=UTC),
    )
    second = public_downloads.prepare_public_download_publication(
        b"header\n",
        downloads,
        published_at=datetime(2026, 8, 18, tzinfo=UTC),
    )
    changed = public_downloads.prepare_public_download_publication(
        b"changed\n",
        downloads,
        published_at=datetime(2026, 8, 18, tzinfo=UTC),
    )

    first_manifest = json.loads(first.manifest_body)
    second_manifest = json.loads(second.manifest_body)
    changed_manifest = json.loads(changed.manifest_body)
    assert first_manifest["version"] == second_manifest["version"]
    assert first_manifest["version"] != changed_manifest["version"]
    assert first.release_id == second.release_id
    assert first.release_id != changed.release_id
    assert {entry["path"] for entry in first_manifest["downloads"]} == {
        entry["path"] for entry in second_manifest["downloads"]
    }
    assert {entry["path"] for entry in first_manifest["downloads"]}.isdisjoint(
        {entry["path"] for entry in changed_manifest["downloads"]}
    )


def test_failed_release_does_not_move_stable_manifest(monkeypatch) -> None:
    _, downloads = _matching_downloads()
    publication = public_downloads.prepare_public_download_publication(
        b"header\nrecord\n",
        downloads,
    )
    fake_s3 = FailingS3(fail_on_put=5)
    monkeypatch.setattr(
        public_downloads,
        "get_s3_settings",
        lambda: type("Settings", (), {"s3_bucket": "test-bucket"})(),
    )

    with pytest.raises(RuntimeError, match="simulated upload failure"):
        public_downloads.write_public_download_publication(
            cast(S3Client, fake_s3),
            publication,
        )

    assert fake_s3.puts
    assert all(put["Key"] != public_downloads.PUBLIC_DOWNLOAD_MANIFEST_KEY for put in fake_s3.puts)
    assert all(
        put["Key"].startswith(f"public/downloads/releases/{publication.release_id}/")
        for put in fake_s3.puts
    )


def test_different_releases_never_share_mutable_artifact_paths() -> None:
    _, downloads = _matching_downloads()
    first = public_downloads.prepare_public_download_publication(
        b"header\nfirst\n",
        downloads,
    )
    second = public_downloads.prepare_public_download_publication(
        b"header\nsecond\n",
        downloads,
    )

    first_manifest = json.loads(first.manifest_body)
    second_manifest = json.loads(second.manifest_body)
    first_paths = {entry["path"] for entry in first_manifest["downloads"]}
    second_paths = {entry["path"] for entry in second_manifest["downloads"]}

    assert first_paths.isdisjoint(second_paths)
    assert all(path.startswith(f"releases/{first.release_id}/") for path in first_paths)
    assert all(path.startswith(f"releases/{second.release_id}/") for path in second_paths)


def test_public_geographic_downloads_reject_an_unmatched_shooting_value() -> None:
    shootings, downloads = _matching_downloads()
    shootings.loc[0, "segment_id"] = "missing-segment"

    with pytest.raises(ValueError, match="street_blocks.*segment_id.*missing-segment"):
        public_downloads.validate_geographic_reference_coverage(shootings, downloads)


def test_public_geographic_downloads_reject_duplicate_join_values() -> None:
    shootings, downloads = _matching_downloads()
    collection = cast(dict[str, Any], downloads["zip_codes"])
    feature = cast(dict[str, Any], cast(list[Any], collection["features"])[0])
    cast(list[Any], collection["features"]).append(dict(feature))

    with pytest.raises(ValueError, match="zip_codes.*duplicate.*zip_code"):
        public_downloads.validate_geographic_reference_coverage(shootings, downloads)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_public_geographic_downloads_reject_blank_join_values(value: object) -> None:
    shootings, downloads = _matching_downloads()
    collection = cast(dict[str, Any], downloads["zip_codes"])
    feature = cast(dict[str, Any], cast(list[Any], collection["features"])[0])
    properties = cast(dict[str, Any], feature["properties"])
    properties["zip_code"] = value

    with pytest.raises(ValueError, match="zip_codes.*blank.*zip_code"):
        public_downloads.validate_geographic_reference_coverage(shootings, downloads)


def test_public_geographic_downloads_reject_null_geometry() -> None:
    shootings, downloads = _matching_downloads()
    collection = cast(dict[str, Any], downloads["zip_codes"])
    feature = cast(dict[str, Any], cast(list[Any], collection["features"])[0])
    feature["geometry"] = None

    with pytest.raises(ValueError, match="zip_codes.*geometry.*index 0"):
        public_downloads.validate_geographic_reference_coverage(shootings, downloads)


def test_public_geographic_downloads_reject_invalid_geometry() -> None:
    shootings, downloads = _matching_downloads()
    collection = cast(dict[str, Any], downloads["zip_codes"])
    feature = cast(dict[str, Any], cast(list[Any], collection["features"])[0])
    feature["geometry"] = {
        "type": "Polygon",
        "coordinates": [
            [
                [-75.2, 39.9],
                [-75.1, 40.0],
                [-75.2, 40.0],
                [-75.1, 39.9],
                [-75.2, 39.9],
            ]
        ],
    }

    with pytest.raises(ValueError, match="zip_codes.*invalid geometry.*index 0"):
        public_downloads.validate_geographic_reference_coverage(shootings, downloads)


def test_geographic_download_loader_uses_processed_street_blocks(monkeypatch) -> None:
    reference_calls: list[str] = []
    processed_calls: list[str] = []

    def read_reference(name: str, *, s3: object) -> dict[str, str]:
        reference_calls.append(name)
        return {"source": name}

    def read_processed(name: str, *, s3: object) -> dict[str, str]:
        processed_calls.append(name)
        return {"source": name}

    monkeypatch.setattr(public_downloads, "read_reference_json", read_reference)
    monkeypatch.setattr(public_downloads, "read_processed_geojson_json", read_processed)

    result = public_downloads.load_geographic_reference_downloads(cast(S3Client, object()))

    assert processed_calls == ["street_blocks"]
    assert "street_blocks" in result
    assert set(reference_calls) == {
        f"{item.dataset}.geojson"
        for item in public_downloads.GEOGRAPHIC_REFERENCE_DOWNLOADS
        if item.source == "reference"
    }
