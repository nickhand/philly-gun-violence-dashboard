"""Atomic boundary-generation publication tests."""

import hashlib
import io
import json
from collections.abc import Callable
from typing import Any, cast

import pytest
from botocore.exceptions import ClientError
from geopandas import GeoDataFrame
from mypy_boto3_s3.client import S3Client

from dashboard_utils.boundary_releases import BOUNDARY_JOIN_FIELDS
from dashboard_utils.config import get_s3_settings
from etl.boundaries.publication import (
    BoundaryPublicationConflict,
    prepare_boundary_publication,
    serialize_boundary_dataset,
    write_boundary_publication,
)


def _error(code: str, operation: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, operation)


class MemoryS3:
    """Conditional-write S3 stand-in with observable publication order."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.puts: list[str] = []
        self.fail_key: str | None = None
        self.generation = 0

    def seed(self, key: str, body: bytes, etag: str) -> None:
        self.objects[key] = (body, etag)

    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        IfNoneMatch: str | None = None,
        IfMatch: str | None = None,
        **kwargs: Any,
    ) -> dict[str, str]:
        del Bucket, kwargs
        if Key == self.fail_key:
            raise _error("InternalError", "PutObject")
        current = self.objects.get(Key)
        if IfNoneMatch == "*" and current is not None:
            raise _error("PreconditionFailed", "PutObject")
        if IfMatch is not None and (current is None or current[1] != IfMatch):
            raise _error("PreconditionFailed", "PutObject")
        self.generation += 1
        etag = f'"etag-{self.generation}"'
        self.objects[Key] = (Body, etag)
        self.puts.append(Key)
        return {"ETag": etag}

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        del Bucket
        try:
            body, etag = self.objects[Key]
        except KeyError as exc:
            raise _error("NoSuchKey", "GetObject") from exc
        return {"Body": io.BytesIO(body), "ETag": etag}


@pytest.fixture(autouse=True)
def _s3_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("S3_BUCKET", "test-bucket")
    monkeypatch.setenv("S3_REFERENCE_PREFIX", "reference")
    get_s3_settings.cache_clear()
    yield
    get_s3_settings.cache_clear()


def _collection(dataset: str, label: str) -> bytes:
    join_field = BOUNDARY_JOIN_FIELDS[dataset]
    properties = {"label": label}
    if join_field is not None:
        properties[join_field] = label
    return json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [[-75.2, 39.9], [-75.1, 39.9], [-75.1, 40.0], [-75.2, 39.9]]
                        ],
                    },
                    "properties": properties,
                }
            ],
        },
        separators=(",", ":"),
    ).encode()


def _generation(**labels: str) -> dict[str, bytes]:
    return {
        dataset: _collection(dataset, labels.get(dataset, f"default-{dataset}"))
        for dataset in BOUNDARY_JOIN_FIELDS
    }


def test_serialization_rejects_an_unknown_coordinate_system() -> None:
    with pytest.raises(ValueError, match="coordinate system"):
        serialize_boundary_dataset(GeoDataFrame({"geometry": []}))


def test_same_dataset_names_with_changed_bytes_create_a_new_generation() -> None:
    first = prepare_boundary_publication(_generation(city_limits="one", neighborhoods="same"))
    changed = prepare_boundary_publication(_generation(city_limits="two", neighborhoods="same"))

    assert changed.release_id != first.release_id
    assert {item.dataset for item in changed.artifacts} == set(BOUNDARY_JOIN_FIELDS)
    assert json.loads(changed.manifest_body)["version"] == f"sha256:{changed.release_id}"


def test_publication_requires_the_exact_authoritative_inventory() -> None:
    generation = _generation()
    generation.pop("zip_codes")

    with pytest.raises(ValueError, match=r"invalid dataset inventory.*missing zip_codes"):
        prepare_boundary_publication(generation)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update(features=[]), "has no features"),
        (
            lambda value: value["features"][0].update(
                geometry={"type": "Point", "coordinates": [-75.1, 39.9]}
            ),
            "invalid polygon geometry",
        ),
        (
            lambda value: value["features"][0]["properties"].update(zip_code="  "),
            "blank or invalid zip_code",
        ),
        (
            lambda value: value["features"].append(value["features"][0]),
            "duplicate zip_code",
        ),
    ],
)
def test_publication_rejects_broken_but_well_formed_boundary_members(
    mutation: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    generation = _generation()
    zip_codes = json.loads(generation["zip_codes"])
    mutation(zip_codes)
    generation["zip_codes"] = json.dumps(zip_codes, separators=(",", ":")).encode()

    with pytest.raises(ValueError, match=message):
        prepare_boundary_publication(generation)


def test_members_precede_pointer_and_compatibility_mirrors_follow_it() -> None:
    publication = prepare_boundary_publication(
        _generation(city_limits="city", neighborhoods="hood")
    )
    s3 = MemoryS3()

    write_boundary_publication(cast(S3Client, s3), publication, expected_manifest_etag=None)

    pointer_key = "reference/boundaries_release.json"
    legacy_pointer_key = "reference/boundaries_manifest.json"
    pointer_index = s3.puts.index(pointer_key)
    assert s3.puts[:pointer_index] == [item.key for item in publication.artifacts]
    assert s3.puts[pointer_index + 1] == legacy_pointer_key
    assert s3.puts[pointer_index + 2 :] == [item.mirror_key for item in publication.artifacts]
    manifest = json.loads(s3.objects[pointer_key][0])
    for artifact in publication.artifacts:
        assert manifest["datasets"][artifact.dataset] == {
            "key": artifact.key,
            "sha256": hashlib.sha256(artifact.body).hexdigest(),
        }


def test_member_failure_never_moves_pointer_or_writes_compatibility_mirrors() -> None:
    publication = prepare_boundary_publication(
        _generation(city_limits="city", neighborhoods="hood")
    )
    s3 = MemoryS3()
    pointer_key = "reference/boundaries_release.json"
    s3.seed(pointer_key, b"old-pointer", '"old-etag"')
    s3.fail_key = publication.artifacts[1].key

    with pytest.raises(ClientError):
        write_boundary_publication(
            cast(S3Client, s3),
            publication,
            expected_manifest_etag='"old-etag"',
        )

    assert s3.objects[pointer_key] == (b"old-pointer", '"old-etag"')
    assert all(item.mirror_key not in s3.objects for item in publication.artifacts)


def test_concurrent_different_publication_cannot_overwrite_the_winner() -> None:
    first = prepare_boundary_publication(_generation(city_limits="first"))
    second = prepare_boundary_publication(_generation(city_limits="second"))
    s3 = MemoryS3()
    pointer_key = "reference/boundaries_release.json"
    s3.seed(pointer_key, b"old-pointer", '"old-etag"')

    write_boundary_publication(
        cast(S3Client, s3),
        first,
        expected_manifest_etag='"old-etag"',
    )
    with pytest.raises(BoundaryPublicationConflict, match="changed during extraction"):
        write_boundary_publication(
            cast(S3Client, s3),
            second,
            expected_manifest_etag='"old-etag"',
        )

    assert s3.objects[pointer_key][0] == first.manifest_body
    assert s3.objects[first.artifacts[0].mirror_key][0] == first.artifacts[0].body


def test_identical_concurrent_publication_is_idempotent() -> None:
    publication = prepare_boundary_publication(_generation(city_limits="same"))
    s3 = MemoryS3()

    client = cast(S3Client, s3)
    write_boundary_publication(client, publication, expected_manifest_etag=None)
    write_boundary_publication(client, publication, expected_manifest_etag=None)

    assert s3.objects["reference/boundaries_release.json"][0] == publication.manifest_body
    assert s3.objects["reference/boundaries_manifest.json"][0] == publication.legacy_manifest_body
