"""Static public download artifacts derived from internal geographic data."""

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal

import pandas as pd
from mypy_boto3_s3.client import S3Client
from shapely.errors import ShapelyError
from shapely.geometry import shape

from dashboard_utils.config import get_s3_settings
from dashboard_utils.processed import (
    read_processed_geojson_json,
    read_reference_json,
)

PUBLIC_DOWNLOAD_MANIFEST_CACHE_CONTROL: Final = "public,max-age=300,stale-while-revalidate=86400"
PUBLIC_DOWNLOAD_RELEASE_CACHE_CONTROL: Final = "public,max-age=31536000,immutable"
PUBLIC_DOWNLOAD_PREFIX: Final = "public/downloads"
PUBLIC_DOWNLOAD_MANIFEST_FILENAME: Final = "manifest.json"
PUBLIC_DOWNLOAD_MANIFEST_KEY: Final = (
    f"{PUBLIC_DOWNLOAD_PREFIX}/{PUBLIC_DOWNLOAD_MANIFEST_FILENAME}"
)
PUBLIC_DOWNLOAD_RELEASES_PREFIX: Final = "releases"
PUBLIC_DOWNLOAD_MANIFEST_SCHEMA_VERSION: Final = 2
PUBLIC_SHOOTINGS_CSV_FILENAME: Final = "philadelphia-shooting-victims.csv"
PUBLIC_SHOOTINGS_CSV_MEDIA_TYPE: Final = "text/csv; charset=utf-8"


@dataclass(frozen=True)
class GeographicReferenceDownload:
    """One curated geographic file that can be joined to shooting records."""

    dataset: str
    label: str
    join_field: str
    filename: str
    source: Literal["reference", "processed"] = "reference"


@dataclass(frozen=True)
class PublicDownloadArtifact:
    """One fully serialized file ready for public upload."""

    artifact_id: str
    kind: Literal["records", "geography"]
    label: str
    filename: str
    path: str
    media_type: str
    body: bytes
    row_count: int
    dataset: str | None = None
    join_field: str | None = None


@dataclass(frozen=True)
class PublicDownloadPublication:
    """A validated immutable release and its stable manifest pointer."""

    release_id: str
    artifacts: tuple[PublicDownloadArtifact, ...]
    manifest_body: bytes


GEOGRAPHIC_REFERENCE_DOWNLOADS: Final = (
    GeographicReferenceDownload(
        dataset="zip_codes",
        label="ZIP code boundaries",
        join_field="zip_code",
        filename="philadelphia-zip-codes.geojson",
    ),
    GeographicReferenceDownload(
        dataset="neighborhoods",
        label="Neighborhood boundaries",
        join_field="neighborhood",
        filename="philadelphia-neighborhoods.geojson",
    ),
    GeographicReferenceDownload(
        dataset="police_districts",
        label="Police district boundaries",
        join_field="police_district",
        filename="philadelphia-police-districts.geojson",
    ),
    GeographicReferenceDownload(
        dataset="council_districts",
        label="City Council district boundaries",
        join_field="council_district",
        filename="philadelphia-city-council-districts.geojson",
    ),
    GeographicReferenceDownload(
        dataset="pa_house_districts",
        label="Pennsylvania House district boundaries",
        join_field="house_district",
        filename="philadelphia-pa-house-districts.geojson",
    ),
    GeographicReferenceDownload(
        dataset="pa_senate_districts",
        label="Pennsylvania Senate district boundaries",
        join_field="senate_district",
        filename="philadelphia-pa-senate-districts.geojson",
    ),
    GeographicReferenceDownload(
        dataset="school_catchments",
        label="Elementary school catchment boundaries",
        join_field="school_name",
        filename="philadelphia-elementary-school-catchments.geojson",
    ),
    GeographicReferenceDownload(
        dataset="street_blocks",
        label="Street blocks",
        join_field="segment_id",
        filename="philadelphia-street-blocks.geojson",
        source="processed",
    ),
)


def load_geographic_reference_downloads(s3: S3Client) -> dict[str, object]:
    """Load the internal geographic snapshots used for public downloads."""
    downloads: dict[str, object] = {}
    for item in GEOGRAPHIC_REFERENCE_DOWNLOADS:
        if item.source == "reference":
            collection = read_reference_json(f"{item.dataset}.geojson", s3=s3)
        else:
            collection = read_processed_geojson_json(item.dataset, s3=s3)
        downloads[item.dataset] = collection
    return downloads


def _join_values(collection: object, item: GeographicReferenceDownload) -> set[str]:
    """Validate a GeoJSON reference and return its unique join values."""
    if not isinstance(collection, dict) or collection.get("type") != "FeatureCollection":
        raise ValueError(f"Public geographic reference '{item.dataset}' is not GeoJSON")
    features = collection.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError(f"Public geographic reference '{item.dataset}' has no features")

    values: set[str] = set()
    for index, feature in enumerate(features):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ValueError(
                f"Public geographic reference '{item.dataset}' has an invalid feature "
                f"at index {index}"
            )

        geometry_value = feature.get("geometry")
        if not isinstance(geometry_value, dict):
            raise ValueError(
                f"Public geographic reference '{item.dataset}' has a missing or invalid "
                f"geometry at index {index}"
            )
        try:
            geometry = shape(geometry_value)
        except (ShapelyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"Public geographic reference '{item.dataset}' has an invalid geometry "
                f"at index {index}"
            ) from exc
        if geometry.is_empty or not geometry.is_valid:
            raise ValueError(
                f"Public geographic reference '{item.dataset}' has an empty or invalid "
                f"geometry at index {index}"
            )

        properties = feature.get("properties")
        if not isinstance(properties, dict):
            raise ValueError(
                f"Public geographic reference '{item.dataset}' has invalid properties "
                f"at index {index}"
            )
        value = properties.get(item.join_field)
        normalized_value = "" if value is None else str(value).strip()
        if not normalized_value:
            raise ValueError(
                f"Public geographic reference '{item.dataset}' has a blank "
                f"'{item.join_field}' value at index {index}"
            )
        if normalized_value in values:
            raise ValueError(
                f"Public geographic reference '{item.dataset}' has duplicate "
                f"'{item.join_field}' value '{normalized_value}'"
            )
        values.add(normalized_value)
    return values


def validate_geographic_reference_coverage(
    shootings: pd.DataFrame,
    downloads: dict[str, object],
) -> None:
    """Require every nonblank shooting join value to exist in its map file."""
    for item in GEOGRAPHIC_REFERENCE_DOWNLOADS:
        if item.join_field not in shootings.columns:
            raise ValueError(f"Public shootings data is missing join field '{item.join_field}'")
        if item.dataset not in downloads:
            raise ValueError(f"Public geographic reference '{item.dataset}' was not loaded")

        reference_values = _join_values(downloads[item.dataset], item)
        shooting_values = {
            str(value).strip()
            for value in shootings[item.join_field].dropna().tolist()
            if str(value).strip()
        }
        missing = sorted(shooting_values - reference_values)
        if missing:
            preview = ", ".join(missing[:5])
            raise ValueError(
                f"Public geographic reference '{item.dataset}' is missing "
                f"{len(missing)} '{item.join_field}' value(s): {preview}"
            )


def _serialize_geographic_reference_downloads(
    downloads: dict[str, object],
) -> tuple[PublicDownloadArtifact, ...]:
    """Serialize every curated GeoJSON before any public object is written."""
    artifacts: list[PublicDownloadArtifact] = []
    for item in GEOGRAPHIC_REFERENCE_DOWNLOADS:
        if item.dataset not in downloads:
            raise ValueError(f"Public geographic reference '{item.dataset}' was not loaded")
        collection = downloads[item.dataset]
        # Validate the collection independently of shooting-record coverage so a
        # caller cannot publish a malformed or empty geographic download.
        join_values = _join_values(collection, item)
        body = json.dumps(
            collection,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        artifacts.append(
            PublicDownloadArtifact(
                artifact_id=item.dataset,
                kind="geography",
                label=item.label,
                filename=item.filename,
                path=f"geography/{item.filename}",
                media_type="application/geo+json",
                body=body,
                row_count=len(join_values),
                dataset=item.dataset,
                join_field=item.join_field,
            )
        )
    return tuple(artifacts)


def _publication_release_id(artifacts: tuple[PublicDownloadArtifact, ...]) -> str:
    """Return the SHA-256 release id for the exact public artifact set."""
    digest = hashlib.sha256()
    for artifact in artifacts:
        digest.update(artifact.path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(artifact.body)
        digest.update(b"\0")
    return digest.hexdigest()


def _artifact_sha256(artifact: PublicDownloadArtifact) -> str:
    """Return the SHA-256 checksum for one artifact's exact bytes."""
    return hashlib.sha256(artifact.body).hexdigest()


def _csv_row_count(body: bytes) -> int:
    """Count data rows in the exact UTF-8 CSV body included in a release."""
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Public shootings CSV must be valid UTF-8") from exc

    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ValueError("Public shootings CSV is empty") from exc
    if not header or any(not column.strip() for column in header):
        raise ValueError("Public shootings CSV has an invalid header")
    return sum(1 for row in reader if row)


def _published_at(value: datetime | None) -> str:
    """Return a normalized RFC 3339 UTC publication timestamp."""
    timestamp = value or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("Public download publication timestamp must include a timezone")
    return timestamp.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def prepare_public_download_publication(
    shootings_csv_body: bytes,
    geographic_downloads: dict[str, object],
    *,
    published_at: datetime | None = None,
) -> PublicDownloadPublication:
    """Serialize all files and build a manifest from their exact uploaded bytes."""
    if not shootings_csv_body:
        raise ValueError("Public shootings CSV is empty")

    csv_artifact = PublicDownloadArtifact(
        artifact_id="shooting_victims",
        kind="records",
        label="Philadelphia shooting-victim records",
        filename=PUBLIC_SHOOTINGS_CSV_FILENAME,
        path=PUBLIC_SHOOTINGS_CSV_FILENAME,
        media_type=PUBLIC_SHOOTINGS_CSV_MEDIA_TYPE,
        body=shootings_csv_body,
        row_count=_csv_row_count(shootings_csv_body),
    )
    artifacts = (
        csv_artifact,
        *_serialize_geographic_reference_downloads(geographic_downloads),
    )

    paths = [artifact.path for artifact in artifacts]
    if len(paths) != len(set(paths)):
        raise ValueError("Public download paths must be unique")

    release_id = _publication_release_id(artifacts)
    manifest = {
        "schema_version": PUBLIC_DOWNLOAD_MANIFEST_SCHEMA_VERSION,
        "version": f"sha256:{release_id}",
        "published_at": _published_at(published_at),
        "downloads": [
            {
                "id": artifact.artifact_id,
                "kind": artifact.kind,
                "label": artifact.label,
                "filename": artifact.filename,
                "path": (f"{PUBLIC_DOWNLOAD_RELEASES_PREFIX}/{release_id}/{artifact.path}"),
                "media_type": artifact.media_type,
                "byte_size": len(artifact.body),
                "sha256": _artifact_sha256(artifact),
                "row_count": artifact.row_count,
                **(
                    {
                        "dataset": artifact.dataset,
                        "join_field": artifact.join_field,
                    }
                    if artifact.kind == "geography"
                    else {}
                ),
            }
            for artifact in artifacts
        ],
    }
    manifest_body = (
        json.dumps(manifest, allow_nan=False, indent=2, separators=(",", ": ")) + "\n"
    ).encode("utf-8")
    return PublicDownloadPublication(
        release_id=release_id,
        artifacts=artifacts,
        manifest_body=manifest_body,
    )


def write_public_download_artifacts(
    s3: S3Client,
    publication: PublicDownloadPublication,
) -> None:
    """Upload every immutable artifact for one validated release."""
    bucket = get_s3_settings().s3_bucket
    for artifact in publication.artifacts:
        s3.put_object(
            Bucket=bucket,
            Key=(
                f"{PUBLIC_DOWNLOAD_PREFIX}/{PUBLIC_DOWNLOAD_RELEASES_PREFIX}/"
                f"{publication.release_id}/{artifact.path}"
            ),
            Body=artifact.body,
            ContentType=artifact.media_type,
            ContentDisposition=f'attachment; filename="{artifact.filename}"',
            CacheControl=PUBLIC_DOWNLOAD_RELEASE_CACHE_CONTROL,
        )


def write_public_download_manifest(
    s3: S3Client,
    publication: PublicDownloadPublication,
) -> None:
    """Atomically move the stable manifest pointer to a complete release."""
    bucket = get_s3_settings().s3_bucket
    # S3 replaces one object atomically. Because every path in this pointer is
    # immutable and has already uploaded successfully, readers see either the
    # complete previous release or the complete new release. Failed and
    # overlapping jobs cannot expose a manifest that mixes artifact versions.
    s3.put_object(
        Bucket=bucket,
        Key=PUBLIC_DOWNLOAD_MANIFEST_KEY,
        Body=publication.manifest_body,
        ContentType="application/json; charset=utf-8",
        CacheControl=PUBLIC_DOWNLOAD_MANIFEST_CACHE_CONTROL,
    )


def write_public_download_publication(
    s3: S3Client,
    publication: PublicDownloadPublication,
) -> None:
    """Upload an immutable release, then atomically move the stable manifest."""
    write_public_download_artifacts(s3, publication)
    write_public_download_manifest(s3, publication)
