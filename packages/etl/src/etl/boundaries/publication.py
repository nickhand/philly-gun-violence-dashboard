"""Atomic, content-addressed publication for geographic boundaries."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

import geopandas as gpd
from botocore.exceptions import ClientError
from mypy_boto3_s3.client import S3Client

from dashboard_utils.boundary_releases import (
    BOUNDARY_RELEASE_POINTER_FILENAME,
    BOUNDARY_RELEASE_SCHEMA_VERSION,
    LEGACY_BOUNDARY_MANIFEST_FILENAME,
    BoundaryReleaseManifest,
    BoundaryReleaseObject,
    boundary_release_key,
    compute_boundary_release_id,
    require_complete_boundary_dataset_set,
    validate_boundary_collection,
)
from dashboard_utils.config import get_s3_settings
from dashboard_utils.paths import get_reference_key

BOUNDARY_MANIFEST_CACHE_CONTROL: Final = "no-cache"
BOUNDARY_RELEASE_CACHE_CONTROL: Final = "public,max-age=31536000,immutable"


class BoundaryPublicationConflict(RuntimeError):
    """The stable pointer changed after this publication began."""


@dataclass(frozen=True, slots=True)
class BoundaryArtifact:
    """One exact serialized member of an immutable boundary release."""

    dataset: str
    key: str
    mirror_key: str
    body: bytes
    sha256: str


@dataclass(frozen=True, slots=True)
class BoundaryPublication:
    """A complete boundary generation and its stable pointer body."""

    release_id: str
    artifacts: tuple[BoundaryArtifact, ...]
    manifest_body: bytes
    legacy_manifest_body: bytes


def serialize_boundary_dataset(gdf: gpd.GeoDataFrame) -> bytes:
    """Serialize one GeoDataFrame to deterministic WGS84 GeoJSON bytes."""
    if gdf.crs is None:
        raise ValueError("Boundary serialization requires a known coordinate system")
    if gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    value = json.loads(gdf.to_json(drop_id=True))
    if not isinstance(value, dict) or value.get("type") != "FeatureCollection":
        raise ValueError("Boundary serialization did not produce a FeatureCollection")
    return json.dumps(
        value,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def prepare_boundary_publication(serialized: Mapping[str, bytes]) -> BoundaryPublication:
    """Validate all exact member bytes and build one deterministic pointer."""
    require_complete_boundary_dataset_set(serialized)

    bodies: dict[str, bytes] = {}
    checksums: dict[str, str] = {}
    for dataset, body in sorted(serialized.items()):
        if not isinstance(body, bytes):
            raise TypeError(f"Boundary dataset '{dataset}' must be serialized as bytes")
        try:
            value: Any = json.loads(body, parse_constant=_reject_json_constant)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Boundary dataset '{dataset}' is not valid UTF-8 JSON") from exc
        validate_boundary_collection(dataset, value)
        bodies[dataset] = body
        checksums[dataset] = hashlib.sha256(body).hexdigest()

    release_id = compute_boundary_release_id(checksums)
    settings = get_s3_settings()
    artifacts = tuple(
        BoundaryArtifact(
            dataset=dataset,
            key=boundary_release_key(settings.s3_reference_prefix, release_id, dataset),
            mirror_key=get_reference_key(f"{dataset}.geojson"),
            body=bodies[dataset],
            sha256=checksums[dataset],
        )
        for dataset in sorted(bodies)
    )
    manifest = BoundaryReleaseManifest(
        schema_version=BOUNDARY_RELEASE_SCHEMA_VERSION,
        version=f"sha256:{release_id}",
        datasets={
            artifact.dataset: BoundaryReleaseObject(
                key=artifact.key,
                sha256=artifact.sha256,
            )
            for artifact in artifacts
        },
    )
    manifest_body = (
        json.dumps(
            manifest.model_dump(mode="json"),
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    reference_prefix = f"{settings.s3_reference_prefix.rstrip('/')}/"
    legacy_datasets: dict[str, str] = {}
    for artifact in artifacts:
        if not artifact.key.startswith(reference_prefix):
            raise ValueError("Boundary release key is outside the configured reference prefix")
        legacy_datasets[artifact.dataset] = artifact.key[len(reference_prefix) :]
    legacy_manifest = {
        "datasets": legacy_datasets,
    }
    legacy_manifest_body = (
        json.dumps(legacy_manifest, allow_nan=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    return BoundaryPublication(
        release_id=release_id,
        artifacts=artifacts,
        manifest_body=manifest_body,
        legacy_manifest_body=legacy_manifest_body,
    )


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Boundary JSON contains non-finite number {value}")


def _is_not_found(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}


def _is_precondition_failed(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") in {
        "PreconditionFailed",
        "ConditionalRequestConflict",
        "409",
        "412",
    }


def read_boundary_manifest_etag(s3: S3Client) -> str | None:
    """Read the pointer identity before expensive extraction begins."""
    try:
        response = s3.head_object(
            Bucket=get_s3_settings().s3_bucket,
            Key=get_reference_key(BOUNDARY_RELEASE_POINTER_FILENAME),
        )
    except ClientError as exc:
        if _is_not_found(exc):
            return None
        raise
    etag = response.get("ETag")
    if not isinstance(etag, str) or not etag:
        raise ValueError("Boundary manifest head response is missing its ETag")
    return etag


def _read_exact_bytes(s3: S3Client, key: str) -> bytes:
    response = s3.get_object(Bucket=get_s3_settings().s3_bucket, Key=key)
    body = response["Body"].read()
    if not isinstance(body, bytes):
        raise TypeError(f"S3 object body for '{key}' did not return bytes")
    return body


def _put_immutable_artifact(s3: S3Client, artifact: BoundaryArtifact) -> None:
    bucket = get_s3_settings().s3_bucket
    try:
        s3.put_object(
            Bucket=bucket,
            Key=artifact.key,
            Body=artifact.body,
            ContentType="application/geo+json",
            CacheControl=BOUNDARY_RELEASE_CACHE_CONTROL,
            IfNoneMatch="*",
        )
    except ClientError as exc:
        if not _is_precondition_failed(exc):
            raise
        if _read_exact_bytes(s3, artifact.key) != artifact.body:
            raise RuntimeError(
                f"Immutable boundary release object already exists with different bytes: "
                f"{artifact.key}"
            ) from exc


def _move_manifest_pointer(
    s3: S3Client,
    publication: BoundaryPublication,
    *,
    expected_manifest_etag: str | None,
) -> None:
    bucket = get_s3_settings().s3_bucket
    key = get_reference_key(BOUNDARY_RELEASE_POINTER_FILENAME)
    try:
        if expected_manifest_etag is None:
            s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=publication.manifest_body,
                ContentType="application/json; charset=utf-8",
                CacheControl=BOUNDARY_MANIFEST_CACHE_CONTROL,
                IfNoneMatch="*",
            )
        else:
            s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=publication.manifest_body,
                ContentType="application/json; charset=utf-8",
                CacheControl=BOUNDARY_MANIFEST_CACHE_CONTROL,
                IfMatch=expected_manifest_etag,
            )
    except ClientError as exc:
        if not _is_precondition_failed(exc):
            raise
        try:
            current = _read_exact_bytes(s3, key)
        except ClientError:
            current = None
        if current != publication.manifest_body:
            raise BoundaryPublicationConflict(
                "Boundary manifest changed during extraction; refusing to overwrite it"
            ) from exc


def write_boundary_publication(
    s3: S3Client,
    publication: BoundaryPublication,
    *,
    expected_manifest_etag: str | None,
) -> None:
    """Upload a whole generation, CAS its pointer, then update legacy mirrors."""
    for artifact in publication.artifacts:
        _put_immutable_artifact(s3, artifact)

    _move_manifest_pointer(
        s3,
        publication,
        expected_manifest_etag=expected_manifest_etag,
    )

    # Preserve the original manifest schema for old API instances and rollback
    # builds. Its values name the same immutable release members, so replacing
    # this small object is an atomic compatibility pointer rather than a mixed
    # stable-key view.
    s3.put_object(
        Bucket=get_s3_settings().s3_bucket,
        Key=get_reference_key(LEGACY_BOUNDARY_MANIFEST_FILENAME),
        Body=publication.legacy_manifest_body,
        ContentType="application/json; charset=utf-8",
        CacheControl=BOUNDARY_MANIFEST_CACHE_CONTROL,
    )

    # Stable members are retained only for older consumers. The API trusts the
    # checksummed release above, so a compatibility-write failure cannot expose
    # a mixed generation to API requests.
    bucket = get_s3_settings().s3_bucket
    for artifact in publication.artifacts:
        s3.put_object(
            Bucket=bucket,
            Key=artifact.mirror_key,
            Body=artifact.body,
            ContentType="application/geo+json",
            CacheControl="no-cache",
        )
