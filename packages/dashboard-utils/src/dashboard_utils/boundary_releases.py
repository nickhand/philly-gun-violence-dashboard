"""Typed content-addressed releases for geographic boundary datasets."""

import hashlib
import json
import re
from collections.abc import Mapping
from posixpath import join as posix_join
from typing import Annotated, Any, Final, Literal, cast

import geopandas as gpd
from mypy_boto3_s3.client import S3Client
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from shapely.errors import ShapelyError
from shapely.geometry import shape

from dashboard_utils.aws import make_s3_client, read_bytes
from dashboard_utils.config import get_s3_settings
from dashboard_utils.constants import REFERENCE_CRS
from dashboard_utils.paths import get_reference_key

BOUNDARY_RELEASE_SCHEMA_VERSION = 1
BOUNDARY_RELEASE_POINTER_FILENAME = "boundaries_release.json"
LEGACY_BOUNDARY_MANIFEST_FILENAME = "boundaries_manifest.json"
SHA256_PATTERN = r"^[a-f0-9]{64}$"
BOUNDARY_DATASET_PATTERN = r"^[a-z][a-z0-9_]*$"
BOUNDARY_JOIN_FIELDS: Final[dict[str, str | None]] = {
    "city_limits": None,
    "council_districts": "council_district",
    "neighborhoods": "neighborhood",
    "pa_house_districts": "house_district",
    "pa_senate_districts": "senate_district",
    "police_districts": "police_district",
    "school_catchments": "school_name",
    "zip_codes": "zip_code",
}
EXPECTED_BOUNDARY_DATASETS: Final = frozenset(BOUNDARY_JOIN_FIELDS)

BoundaryDatasetName = Annotated[
    str,
    StringConstraints(pattern=BOUNDARY_DATASET_PATTERN, strict=True),
]


class BoundaryReleaseObject(BaseModel):
    """One immutable GeoJSON object referenced by a boundary release."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    key: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)


class BoundaryReleaseManifest(BaseModel):
    """Stable pointer to one complete, immutable boundary generation."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1]
    version: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    datasets: dict[BoundaryDatasetName, BoundaryReleaseObject] = Field(min_length=1)


def require_complete_boundary_dataset_set(datasets: Mapping[str, object]) -> None:
    """Require the exact authoritative boundary inventory."""
    actual = set(datasets)
    missing = sorted(EXPECTED_BOUNDARY_DATASETS - actual)
    unexpected = sorted(actual - EXPECTED_BOUNDARY_DATASETS)
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected {', '.join(unexpected)}")
        raise ValueError(
            f"Boundary generation has an invalid dataset inventory: {'; '.join(details)}"
        )


def validate_boundary_collection(dataset: str, value: object) -> None:
    """Validate one nonempty polygon collection and its required join values."""
    if dataset not in BOUNDARY_JOIN_FIELDS:
        raise ValueError(f"Unknown boundary dataset '{dataset}'")
    if not isinstance(value, dict) or value.get("type") != "FeatureCollection":
        raise ValueError(f"Boundary dataset '{dataset}' is not a FeatureCollection")
    features = value.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError(f"Boundary dataset '{dataset}' has no features")

    join_field = BOUNDARY_JOIN_FIELDS[dataset]
    seen_values: set[str] = set()
    for index, feature in enumerate(features):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ValueError(f"Boundary dataset '{dataset}' has an invalid feature at {index}")
        geometry_value = feature.get("geometry")
        if not isinstance(geometry_value, dict):
            raise ValueError(f"Boundary dataset '{dataset}' has no geometry at {index}")
        try:
            geometry = shape(geometry_value)
        except (ShapelyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"Boundary dataset '{dataset}' has invalid geometry at {index}"
            ) from exc
        if (
            geometry.geom_type not in {"Polygon", "MultiPolygon"}
            or geometry.is_empty
            or not geometry.is_valid
        ):
            raise ValueError(
                f"Boundary dataset '{dataset}' has invalid polygon geometry at {index}"
            )

        properties = feature.get("properties")
        if not isinstance(properties, dict):
            raise ValueError(f"Boundary dataset '{dataset}' has invalid properties at {index}")
        if join_field is None:
            continue
        join_value = properties.get(join_field)
        if not isinstance(join_value, str) or not join_value.strip():
            raise ValueError(
                f"Boundary dataset '{dataset}' has a blank or invalid {join_field} at {index}"
            )
        normalized = join_value.strip()
        if normalized in seen_values:
            raise ValueError(
                f"Boundary dataset '{dataset}' has duplicate {join_field} '{normalized}'"
            )
        seen_values.add(normalized)


def compute_boundary_release_id(checksums: Mapping[str, str]) -> str:
    """Hash an exact set of dataset names and member checksums."""
    if not checksums:
        raise ValueError("A boundary release must contain at least one dataset")
    for dataset, checksum in checksums.items():
        if re.fullmatch(BOUNDARY_DATASET_PATTERN, dataset) is None:
            raise ValueError(f"Invalid boundary dataset name '{dataset}'")
        if re.fullmatch(SHA256_PATTERN, checksum) is None:
            raise ValueError(f"Invalid checksum for boundary dataset '{dataset}'")
    descriptor = {
        "schema_version": BOUNDARY_RELEASE_SCHEMA_VERSION,
        "datasets": dict(sorted(checksums.items())),
    }
    body = json.dumps(descriptor, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def boundary_release_key(reference_prefix: str, release_id: str, dataset: str) -> str:
    """Return the only valid immutable key for one boundary release member."""
    if re.fullmatch(SHA256_PATTERN, release_id) is None:
        raise ValueError("Boundary release id must be 64 lowercase hexadecimal characters")
    if re.fullmatch(BOUNDARY_DATASET_PATTERN, dataset) is None:
        raise ValueError(f"Invalid boundary dataset name '{dataset}'")
    return posix_join(
        reference_prefix,
        "boundaries",
        "releases",
        release_id,
        f"{dataset}.geojson",
    )


def validate_boundary_release_manifest(
    release: BoundaryReleaseManifest,
    *,
    reference_prefix: str,
) -> str:
    """Validate inventory, content-derived version, and every exact member key."""
    require_complete_boundary_dataset_set(release.datasets)
    match = re.fullmatch(r"sha256:([a-f0-9]{64})", release.version)
    if match is None:
        raise ValueError("Boundary release version must be a SHA-256 digest")
    release_id = match.group(1)
    calculated = compute_boundary_release_id(
        {dataset: member.sha256 for dataset, member in release.datasets.items()}
    )
    if calculated != release_id:
        raise ValueError("Boundary release version does not match its dataset checksums")
    for dataset, member in release.datasets.items():
        expected = boundary_release_key(reference_prefix, release_id, dataset)
        if member.key != expected:
            raise ValueError(f"Boundary dataset '{dataset}' does not use its exact release key")
    return release_id


def validate_legacy_boundary_datasets(value: object) -> dict[str, str]:
    """Validate the original string-valued boundary-manifest schema."""
    if not isinstance(value, dict):
        raise ValueError("Legacy boundary manifest must contain a datasets object")
    require_complete_boundary_dataset_set(value)
    validated: dict[str, str] = {}
    for dataset, relative_key in value.items():
        if not isinstance(dataset, str) or not isinstance(relative_key, str):
            raise ValueError("Legacy boundary manifest entries must be strings")
        stable_key = f"{dataset}.geojson"
        release_pattern = rf"boundaries/releases/[a-f0-9]{{64}}/{re.escape(dataset)}\.geojson"
        if relative_key != stable_key and re.fullmatch(release_pattern, relative_key) is None:
            raise ValueError(f"Legacy boundary dataset '{dataset}' has an invalid key")
        validated[dataset] = relative_key
    return validated


def _decode_json_object(body: bytes, *, label: str) -> dict[str, object]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"{label} contains non-finite number {value}")

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"{label} contains duplicate field '{key}'")
            value[key] = item
        return value

    try:
        value = json.loads(
            body,
            parse_constant=reject_constant,
            object_pairs_hook=unique_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _read_release_collections(
    s3: S3Client,
    release: BoundaryReleaseManifest,
) -> dict[str, dict[str, object]]:
    settings = get_s3_settings()
    validate_boundary_release_manifest(
        release,
        reference_prefix=settings.s3_reference_prefix,
    )
    datasets: dict[str, dict[str, object]] = {}
    for dataset, member in release.datasets.items():
        body = read_bytes(s3, settings.s3_bucket, member.key)
        if hashlib.sha256(body).hexdigest() != member.sha256:
            raise ValueError(f"Boundary dataset '{dataset}' checksum mismatch")
        value = _decode_json_object(body, label=f"Boundary dataset '{dataset}'")
        validate_boundary_collection(dataset, value)
        datasets[dataset] = value
    return datasets


def _read_legacy_collections(
    s3: S3Client,
    manifest: dict[str, object],
) -> dict[str, dict[str, object]]:
    raw_datasets = manifest.get("datasets")
    datasets_manifest = validate_legacy_boundary_datasets(raw_datasets)
    settings = get_s3_settings()
    datasets: dict[str, dict[str, object]] = {}
    for dataset, relative_key in datasets_manifest.items():
        body = read_bytes(s3, settings.s3_bucket, get_reference_key(relative_key))
        value = _decode_json_object(body, label=f"Legacy boundary dataset '{dataset}'")
        validate_boundary_collection(dataset, value)
        datasets[dataset] = value
    return datasets


def read_boundary_snapshot_json(
    *,
    s3: S3Client | None = None,
) -> dict[str, dict[str, object]]:
    """Read one complete release generation, with legacy rollout fallback."""
    client = s3 or make_s3_client()
    settings = get_s3_settings()
    try:
        pointer_body = read_bytes(
            client,
            settings.s3_bucket,
            get_reference_key(BOUNDARY_RELEASE_POINTER_FILENAME),
        )
    except FileNotFoundError:
        legacy_body = read_bytes(
            client,
            settings.s3_bucket,
            get_reference_key(LEGACY_BOUNDARY_MANIFEST_FILENAME),
        )
        return _read_legacy_collections(
            client,
            _decode_json_object(legacy_body, label="Legacy boundary manifest"),
        )
    try:
        release = BoundaryReleaseManifest.model_validate_json(pointer_body)
    except ValueError as exc:
        raise ValueError("Boundary release manifest is invalid") from exc
    return _read_release_collections(client, release)


def read_boundary_snapshot_gdfs(
    *,
    s3: S3Client | None = None,
) -> dict[str, gpd.GeoDataFrame]:
    """Read one complete boundary generation as projected GeoDataFrames."""
    collections = read_boundary_snapshot_json(s3=s3)
    snapshots: dict[str, gpd.GeoDataFrame] = {}
    for dataset, value in collections.items():
        # ``read_boundary_snapshot_json`` has already performed the runtime
        # FeatureCollection validation; make that narrowed shape explicit to
        # the GeoPandas type checker at this conversion boundary.
        features = cast(list[dict[str, Any]], value["features"])
        snapshots[dataset] = gpd.GeoDataFrame.from_features(
            features,
            crs="EPSG:4326",
        ).to_crs(REFERENCE_CRS)
    return snapshots
