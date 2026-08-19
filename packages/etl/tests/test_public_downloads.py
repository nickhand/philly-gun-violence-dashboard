"""Tests for curated public geographic reference downloads."""

import hashlib
import io
import json
from datetime import UTC, datetime
from typing import Any, cast

import pandas as pd
import pytest
from botocore.exceptions import ClientError
from mypy_boto3_s3.client import S3Client

from etl import public_downloads
from etl.utils.release_pointer import StablePointerRegression


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


class ConditionalPublicS3:
    """In-memory S3 with exact object bodies and conditional pointer writes."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.put_count = 0

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        assert Bucket == "test-bucket"
        try:
            body, etag = self.objects[Key]
        except KeyError as exc:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "missing"}},
                "GetObject",
            ) from exc
        return {"Body": io.BytesIO(body), "ETag": etag}

    def put_object(self, **kwargs: Any) -> None:
        assert kwargs["Bucket"] == "test-bucket"
        key = cast(str, kwargs["Key"])
        current = self.objects.get(key)
        if kwargs.get("IfNoneMatch") == "*" and current is not None:
            raise ClientError(
                {"Error": {"Code": "PreconditionFailed", "Message": "stale"}},
                "PutObject",
            )
        if "IfMatch" in kwargs and (current is None or current[1] != kwargs["IfMatch"]):
            raise ClientError(
                {"Error": {"Code": "PreconditionFailed", "Message": "stale"}},
                "PutObject",
            )
        self.put_count += 1
        self.objects[key] = (cast(bytes, kwargs["Body"]), f'"etag-{self.put_count}"')


def test_publication_type_rejects_partial_application_release() -> None:
    with pytest.raises(ValueError, match="published together"):
        public_downloads.PublicDownloadPublication(
            release_id="a" * 64,
            artifacts=(),
            manifest_body=b"{}",
            application_data_body=b"{}",
        )


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
        expected_pointer=public_downloads.StablePointerSnapshot.missing(),
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


def test_public_manifest_is_also_the_atomic_application_release_pointer(monkeypatch) -> None:
    _, downloads = _matching_downloads()
    monkeypatch.setattr(
        public_downloads,
        "get_s3_settings",
        lambda: type(
            "Settings",
            (),
            {"s3_bucket": "test-bucket", "s3_processed_prefix": "processed"},
        )(),
    )
    data_body = b'{"type":"FeatureCollection","features":[]}'
    metadata_body = b'{"data_through":"2026-08-17"}'

    publication = public_downloads.prepare_public_download_publication(
        b"dc_key\n123\n",
        downloads,
        application_data_body=data_body,
        application_metadata_body=metadata_body,
    )
    manifest = json.loads(publication.manifest_body)
    application = manifest["application_data"]

    assert application == {
        "schema_version": 1,
        "data": {
            "key": (f"processed/shootings/releases/{publication.release_id}/shootings.geojson"),
            "sha256": hashlib.sha256(data_body).hexdigest(),
        },
        "metadata": {
            "key": f"processed/shootings/releases/{publication.release_id}/meta.json",
            "sha256": hashlib.sha256(metadata_body).hexdigest(),
        },
    }

    changed_metadata = public_downloads.prepare_public_download_publication(
        b"dc_key\n123\n",
        downloads,
        application_data_body=data_body,
        application_metadata_body=b'{"data_through":"2026-08-18"}',
        previous_application_data=application,
    )
    assert changed_metadata.release_id != publication.release_id
    assert json.loads(changed_metadata.manifest_body)["previous_application_data"] == application


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
        public_downloads.write_public_download_publication(
            cast(S3Client, fake_s3),
            publication,
            expected_pointer=public_downloads.StablePointerSnapshot.missing(),
        )

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
            expected_pointer=public_downloads.StablePointerSnapshot.missing(),
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
    boundary_calls: list[object] = []
    processed_calls: list[str] = []

    expected_boundaries = {
        item.dataset: {"source": item.dataset}
        for item in public_downloads.GEOGRAPHIC_REFERENCE_DOWNLOADS
        if item.source == "reference"
    }

    def read_boundaries(*, s3: object) -> dict[str, dict[str, str]]:
        boundary_calls.append(s3)
        return expected_boundaries

    def read_processed(name: str, *, s3: object) -> dict[str, str]:
        processed_calls.append(name)
        return {"source": name}

    monkeypatch.setattr(public_downloads, "read_boundary_snapshot_json", read_boundaries)
    monkeypatch.setattr(public_downloads, "read_processed_geojson_json", read_processed)

    s3 = cast(S3Client, object())
    result = public_downloads.load_geographic_reference_downloads(s3)

    assert processed_calls == ["street_blocks"]
    assert "street_blocks" in result
    assert boundary_calls == [s3]
    assert {name: value for name, value in result.items() if name != "street_blocks"} == (
        expected_boundaries
    )


def _application_publication(
    downloads: dict[str, object],
    *,
    data_through: str,
    run_started_at: datetime,
) -> public_downloads.PublicDownloadPublication:
    metadata_body = json.dumps(
        {
            "data_through": data_through,
            "last_updated": run_started_at.isoformat(),
        },
        separators=(",", ":"),
    ).encode()
    return public_downloads.prepare_public_download_publication(
        f"dc_key\n{data_through}\n".encode(),
        downloads,
        published_at=run_started_at,
        application_data_body=json.dumps({"generation": data_through}).encode(),
        application_metadata_body=metadata_body,
    )


def _write_application_members(
    s3: ConditionalPublicS3,
    publication: public_downloads.PublicDownloadPublication,
) -> None:
    manifest = json.loads(publication.manifest_body)
    application = manifest["application_data"]
    assert publication.application_data_body is not None
    assert publication.application_metadata_body is not None
    s3.put_object(
        Bucket="test-bucket",
        Key=application["data"]["key"],
        Body=publication.application_data_body,
    )
    s3.put_object(
        Bucket="test-bucket",
        Key=application["metadata"]["key"],
        Body=publication.application_metadata_body,
    )


def test_stale_shootings_publisher_cannot_regress_shared_public_pointer(monkeypatch) -> None:
    _, downloads = _matching_downloads()
    monkeypatch.setattr(
        public_downloads,
        "get_s3_settings",
        lambda: type(
            "Settings",
            (),
            {"s3_bucket": "test-bucket", "s3_processed_prefix": "processed"},
        )(),
    )
    s3 = ConditionalPublicS3()
    client = cast(S3Client, s3)

    baseline = _application_publication(
        downloads,
        data_through="2026-08-16",
        run_started_at=datetime(2026, 8, 16, 8, tzinfo=UTC),
    )
    _write_application_members(s3, baseline)
    public_downloads.write_public_download_publication(
        client,
        baseline,
        expected_pointer=public_downloads.StablePointerSnapshot.missing(),
    )
    shared_start = public_downloads.read_public_download_pointer(client)

    newer = _application_publication(
        downloads,
        data_through="2026-08-18",
        run_started_at=datetime(2026, 8, 18, 8, tzinfo=UTC),
    )
    _write_application_members(s3, newer)
    public_downloads.write_public_download_publication(
        client,
        newer,
        expected_pointer=shared_start,
    )
    newer_pointer = s3.objects[public_downloads.PUBLIC_DOWNLOAD_MANIFEST_KEY][0]

    stale = _application_publication(
        downloads,
        data_through="2026-08-17",
        run_started_at=datetime(2026, 8, 17, 8, tzinfo=UTC),
    )
    _write_application_members(s3, stale)
    with pytest.raises(StablePointerRegression, match="equal or newer"):
        public_downloads.write_public_download_publication(
            client,
            stale,
            expected_pointer=shared_start,
        )

    assert s3.objects[public_downloads.PUBLIC_DOWNLOAD_MANIFEST_KEY][0] == newer_pointer
