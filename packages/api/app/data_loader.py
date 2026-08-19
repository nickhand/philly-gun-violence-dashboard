"""Typed, atomic S3 dataset loading for API startup and lazy refresh."""

import hashlib
import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from posixpath import join as posix_join
from threading import Lock
from typing import Annotated, Any, Literal, Never

from botocore.exceptions import ClientError
from fastapi import FastAPI, Request
from loguru import logger
from mypy_boto3_s3.client import S3Client
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StrictFloat,
    StrictInt,
    ValidationError,
)

from app.config import settings
from dashboard_utils.boundary_releases import (
    BOUNDARY_RELEASE_POINTER_FILENAME,
    LEGACY_BOUNDARY_MANIFEST_FILENAME,
    BoundaryReleaseManifest,
    validate_boundary_collection,
    validate_boundary_release_manifest,
    validate_legacy_boundary_datasets,
)
from dashboard_utils.constants import DATE_FORMAT
from dashboard_utils.models.shootings import ShootingVictimsSchema
from dashboard_utils.paths import get_processed_key, get_reference_key
from dashboard_utils.processed import (
    read_processed_geojson_json,
    read_processed_json,
    read_reference_json,
)

PUBLIC_DOWNLOAD_MANIFEST_KEY = "public/downloads/manifest.json"
SHOOTINGS_RELEASE_SCHEMA_VERSION = 1
HOMICIDES_RELEASE_SCHEMA_VERSION = 1
SHA256_PATTERN = r"^[a-f0-9]{64}$"
RELEASE_VERSION_PATTERN = re.compile(r"sha256:([a-f0-9]{64})")

JsonObject = dict[str, Any]
SourceToken = tuple[str, ...]
ReleaseToken = tuple[str, str, str, str]


class FrozenJsonObject(dict[str, Any]):
    """A JSON-compatible mapping that refuses in-place mutation."""

    @staticmethod
    def _immutable(*args: Any, **kwargs: Any) -> Never:
        del args, kwargs
        raise TypeError("Published snapshot data is immutable")

    def __setitem__(self, key: str, value: Any) -> Never:
        self._immutable(key, value)

    def __delitem__(self, key: str) -> Never:
        self._immutable(key)

    def __ior__(self, value: Any) -> Never:
        self._immutable(value)

    def clear(self) -> Never:
        self._immutable()

    def pop(self, *args: Any) -> Never:
        self._immutable(*args)

    def popitem(self) -> Never:
        self._immutable()

    def setdefault(self, *args: Any) -> Never:
        self._immutable(*args)

    def update(self, *args: Any, **kwargs: Any) -> Never:
        self._immutable(*args, **kwargs)


def _freeze_json(value: Any) -> Any:
    """Recursively freeze validated JSON while retaining JSON serialization."""
    if isinstance(value, dict):
        return FrozenJsonObject({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze_json(item) for item in value)
    return value


class _ReleaseObject(BaseModel):
    """One immutable S3 object named by a release pointer."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)


class _ShootingsRelease(BaseModel):
    """Application-data section embedded in the public download manifest."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    data: _ReleaseObject
    metadata: _ReleaseObject


class _HomicidesRelease(BaseModel):
    """Stable pointer to one immutable homicide totals release."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    version: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    totals: _ReleaseObject
    metadata: _ReleaseObject


class _HomicideRecord(BaseModel):
    """One validated year of homicide totals."""

    model_config = ConfigDict(extra="forbid")

    annual: Annotated[StrictInt | StrictFloat, Field(ge=0)] | None
    ytd: Annotated[StrictInt | StrictFloat, Field(ge=0)]


class _HomicideTotals(RootModel[dict[str, _HomicideRecord]]):
    """Validated homicide totals indexed by four-digit year."""


@dataclass(frozen=True, slots=True)
class ShootingVersionSnapshot:
    """One immutable version of the shooting rows and its manifest."""

    version: str
    years: tuple[int, ...]
    rows_by_year: dict[int, tuple[JsonObject, ...]]
    meta: JsonObject
    release_token: ReleaseToken | None = None
    freshness: JsonObject | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "rows_by_year", _freeze_json(self.rows_by_year))
        object.__setattr__(self, "meta", _freeze_json(self.meta))
        if self.release_token is not None and self.freshness is None:
            raise ValueError("A release-backed shooting version must include freshness metadata")
        if self.freshness is not None:
            object.__setattr__(self, "freshness", _freeze_json(self.freshness))


@dataclass(frozen=True, slots=True)
class ShootingsSnapshot:
    """Current shootings release plus a bounded N-1 rollover version."""

    current: ShootingVersionSnapshot
    previous: ShootingVersionSnapshot | None
    freshness: JsonObject
    source_kind: Literal["release", "legacy"]
    source_token: SourceToken

    def __post_init__(self) -> None:
        object.__setattr__(self, "freshness", _freeze_json(self.freshness))

    def find_version(self, version: str) -> ShootingVersionSnapshot | None:
        """Return the current or immediately previous immutable version."""
        if self.current.version == version:
            return self.current
        if self.previous is not None and self.previous.version == version:
            return self.previous
        return None


@dataclass(frozen=True, slots=True)
class HomicidesSnapshot:
    """One validated homicide totals and freshness release."""

    totals: JsonObject
    freshness: JsonObject
    source_kind: Literal["release", "legacy"]
    source_token: SourceToken

    def __post_init__(self) -> None:
        object.__setattr__(self, "totals", _freeze_json(self.totals))
        object.__setattr__(self, "freshness", _freeze_json(self.freshness))


@dataclass(frozen=True, slots=True)
class StreetsSnapshot:
    """Street collection and its precomputed segment lookup."""

    collection: JsonObject
    by_segment_id: dict[str, JsonObject]
    source_token: SourceToken

    def __post_init__(self) -> None:
        object.__setattr__(self, "collection", _freeze_json(self.collection))
        object.__setattr__(self, "by_segment_id", _freeze_json(self.by_segment_id))


@dataclass(frozen=True, slots=True)
class BoundariesSnapshot:
    """All boundary collections loaded from one manifest revision."""

    datasets: dict[str, JsonObject]
    source_kind: Literal["release", "legacy"]
    source_token: SourceToken

    def __post_init__(self) -> None:
        object.__setattr__(self, "datasets", _freeze_json(self.datasets))


@dataclass(frozen=True, slots=True)
class AppDataSnapshot:
    """Single pointer to every dataset visible to API request handlers."""

    shootings: ShootingsSnapshot | None = None
    homicides: HomicidesSnapshot | None = None
    streets: StreetsSnapshot | None = None
    boundaries: BoundariesSnapshot | None = None


def get_data_snapshot(app: FastAPI) -> AppDataSnapshot:
    """Return the application's current atomic data pointer."""
    snapshot = getattr(app.state, "data_snapshot", None)
    if not isinstance(snapshot, AppDataSnapshot):
        raise RuntimeError("Application data has not been initialized.")
    return snapshot


def require_shootings(snapshot: AppDataSnapshot) -> ShootingsSnapshot:
    """Return loaded shooting data or fail explicitly during invalid startup."""
    if snapshot.shootings is None:
        raise RuntimeError("Shootings data has not been initialized.")
    return snapshot.shootings


def require_homicides(snapshot: AppDataSnapshot) -> HomicidesSnapshot:
    """Return loaded homicide data or fail explicitly during invalid startup."""
    if snapshot.homicides is None:
        raise RuntimeError("Homicide data has not been initialized.")
    return snapshot.homicides


def require_streets(snapshot: AppDataSnapshot) -> StreetsSnapshot:
    """Return loaded street data or fail explicitly during invalid startup."""
    if snapshot.streets is None:
        raise RuntimeError("Street data has not been initialized.")
    return snapshot.streets


def require_boundaries(snapshot: AppDataSnapshot) -> BoundariesSnapshot:
    """Return loaded boundary data or fail explicitly during invalid startup."""
    if snapshot.boundaries is None:
        raise RuntimeError("Boundary data has not been initialized.")
    return snapshot.boundaries


def _extract_year(value: str | None) -> int | None:
    """Extract a year from a date string using the published source format."""
    if not value:
        return None
    try:
        return datetime.strptime(value, DATE_FORMAT).year
    except ValueError:
        return None


def _not_found(error: ClientError) -> bool:
    """Return whether an S3 error means the requested object is absent."""
    return error.response.get("Error", {}).get("Code") in {"NoSuchKey", "404", "NotFound"}


def _get_s3_etag(s3: S3Client, key: str) -> str:
    """Return the ETag for an S3 object key."""
    response = s3.head_object(Bucket=settings.s3_bucket, Key=key)
    return _validated_etag(response.get("ETag"), key=key)


def _validated_etag(value: object, *, key: str) -> str:
    """Require the S3 revision token used by atomic refresh decisions."""
    if not isinstance(value, str) or not value.strip('"'):
        raise ValueError(f"S3 response for '{key}' is missing its ETag")
    return value.strip('"')


def _get_optional_s3_etag(s3: S3Client, key: str) -> str | None:
    """Return an ETag, distinguishing absence from transient S3 failures."""
    try:
        return _get_s3_etag(s3, key)
    except ClientError as exc:
        if _not_found(exc):
            return None
        raise


def _get_object_bytes(s3: S3Client, key: str) -> tuple[bytes, str]:
    """Read an S3 object and return its exact bytes and response ETag."""
    try:
        response = s3.get_object(Bucket=settings.s3_bucket, Key=key)
    except ClientError as exc:
        if _not_found(exc):
            raise FileNotFoundError(f"S3 object not found: {key}") from exc
        raise
    body = response["Body"].read()
    if not isinstance(body, bytes):
        raise TypeError(f"S3 object body for '{key}' did not return bytes")
    etag = _validated_etag(response.get("ETag"), key=key)
    return body, etag


def _decode_json(body: bytes, *, label: str) -> JsonObject:
    """Decode a JSON object and reject non-object top-level values."""

    def reject_constant(value: str) -> None:
        raise ValueError(f"{label} contains non-finite JSON number {value}")

    def unique_object(pairs: list[tuple[str, Any]]) -> JsonObject:
        value: JsonObject = {}
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


def _ensure_strict_json(value: object, *, label: str) -> None:
    """Reject non-JSON values and NaN/infinity in legacy decoded objects."""
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} contains a non-JSON value") from exc


def _read_verified_json(s3: S3Client, obj: _ReleaseObject, *, label: str) -> JsonObject:
    """Read and checksum one immutable JSON object named by a pointer."""
    body, _ = _get_object_bytes(s3, obj.key)
    actual = hashlib.sha256(body).hexdigest()
    if actual != obj.sha256:
        raise ValueError(f"{label} checksum mismatch: expected {obj.sha256}, got {actual}")
    return _decode_json(body, label=label)


def _version_release_id(value: object, *, label: str) -> str:
    """Return the content digest from an exact ``sha256:<64hex>`` version."""
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a sha256 release version")
    match = RELEASE_VERSION_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError(f"{label} must be a sha256 release version")
    return match.group(1)


def _release_key_id(
    key: str,
    *,
    dataset: Literal["shootings", "homicides"],
    filename: str,
    label: str,
) -> str:
    """Validate one immutable object key and return its release directory."""
    release_prefix = posix_join(settings.s3_processed_prefix, dataset, "releases")
    prefix = f"{release_prefix}/"
    if not key.startswith(prefix):
        raise ValueError(f"{label} has an invalid configured release prefix")
    relative_key = key[len(prefix) :]
    parts = relative_key.split("/")
    if len(parts) != 2 or parts[1] != filename:
        raise ValueError(f"{label} must end with an exact release filename")
    release_id = parts[0]
    if re.fullmatch(SHA256_PATTERN, release_id) is None:
        raise ValueError(f"{label} release directory must be 64 lowercase hex characters")
    return release_id


def _validate_shootings_release_keys(
    release: _ShootingsRelease,
    *,
    label: str,
    expected_release_id: str | None = None,
) -> None:
    """Constrain a shootings pointer to one exact content-addressed directory."""
    data_release_id = _release_key_id(
        release.data.key,
        dataset="shootings",
        filename="shootings.geojson",
        label=f"{label} data key",
    )
    metadata_release_id = _release_key_id(
        release.metadata.key,
        dataset="shootings",
        filename="meta.json",
        label=f"{label} metadata key",
    )
    if data_release_id != metadata_release_id:
        raise ValueError(f"{label} data and metadata must use the same release directory")
    if expected_release_id is not None and data_release_id != expected_release_id:
        raise ValueError(f"{label} release directory does not match the manifest version")


def _validate_homicides_release_keys(release: _HomicidesRelease) -> None:
    """Constrain a homicide pointer to its exact versioned object pair."""
    expected_release_id = _version_release_id(release.version, label="Homicides release version")
    totals_release_id = _release_key_id(
        release.totals.key,
        dataset="homicides",
        filename="homicide_totals.json",
        label="Homicides totals key",
    )
    metadata_release_id = _release_key_id(
        release.metadata.key,
        dataset="homicides",
        filename="meta.json",
        label="Homicides metadata key",
    )
    if totals_release_id != metadata_release_id:
        raise ValueError("Homicides totals and metadata must use the same release directory")
    if totals_release_id != expected_release_id:
        raise ValueError("Homicides release directory does not match the pointer version")


def init_dataset_keys(app: FastAPI) -> None:
    """Initialize keys, the atomic pointer, and refresh synchronization."""
    app.state.dataset_keys = {
        "shootings": get_processed_key("shootings"),
        "shootings_meta": get_processed_key("shootings_meta"),
        "shootings_release": PUBLIC_DOWNLOAD_MANIFEST_KEY,
        "streets": get_processed_key("street_blocks"),
        "homicides": get_processed_key("homicides_totals"),
        "homicides_meta": get_processed_key("homicides_meta"),
        "homicides_release": get_processed_key("homicides_release"),
        "boundaries_manifest": get_reference_key(BOUNDARY_RELEASE_POINTER_FILENAME),
    }
    app.state.data_snapshot = AppDataSnapshot()
    app.state.dataset_last_checked = {}
    app.state.dataset_last_failed = {}
    app.state.dataset_refresh_lock = Lock()
    app.state.stats_page_cache = None


def _compute_version_hash(data: Any) -> str:
    """Compute a short, deterministic content hash for URL versioning."""
    content = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(content).hexdigest()[:12]


def _flatten_feature_to_row(feature: JsonObject, index: int) -> JsonObject:
    """Flatten one validated GeoJSON point feature for Arquero."""
    properties = feature.get("properties")
    if not isinstance(properties, dict):
        raise ValueError(f"Shooting feature {index} has invalid properties")
    try:
        validated_properties = ShootingVictimsSchema.model_validate(properties)
    except ValidationError as exc:
        raise ValueError(
            f"Shooting feature {index} failed property schema validation: {exc}"
        ) from exc
    props = validated_properties.model_dump(mode="json")
    geometry = feature.get("geometry")
    coords: list[Any] = []
    if geometry is not None:
        if not isinstance(geometry, dict) or geometry.get("type") != "Point":
            raise ValueError(f"Shooting feature {index} must use Point geometry")
        raw_coords = geometry.get("coordinates")
        if not isinstance(raw_coords, list) or len(raw_coords) < 2:
            raise ValueError(f"Shooting feature {index} has invalid Point coordinates")
        coords = raw_coords

    lon = coords[0] if coords else None
    lat = coords[1] if coords else None
    if lon is not None and (
        isinstance(lon, bool) or not isinstance(lon, (int, float)) or not math.isfinite(lon)
    ):
        raise ValueError(f"Shooting feature {index} has a nonnumeric longitude")
    if lat is not None and (
        isinstance(lat, bool) or not isinstance(lat, (int, float)) or not math.isfinite(lat)
    ):
        raise ValueError(f"Shooting feature {index} has a nonnumeric latitude")

    date_str = props.get("date")
    if not isinstance(date_str, str):
        raise ValueError(f"Shooting feature {index} is missing a date string")
    try:
        parsed = datetime.strptime(date_str, DATE_FORMAT)
    except ValueError as exc:
        raise ValueError(f"Shooting feature {index} has an invalid date") from exc

    return {
        **props,
        "lon": lon,
        "lat": lat,
        "dateInMs": int(parsed.replace(tzinfo=UTC).timestamp() * 1000),
        "timeInMs": (
            (parsed.hour * 3600 + parsed.minute * 60 + parsed.second) * 1000
            + parsed.microsecond // 1000
        ),
        "weekday": (parsed.weekday() + 1) % 7,
        "year": parsed.year,
        "unique_id": index,
    }


def _validate_freshness(value: JsonObject, *, label: str) -> JsonObject:
    """Require a valid ISO data-through date at the S3 boundary."""
    _ensure_strict_json(value, label=label)
    data_through = value.get("data_through")
    if not isinstance(data_through, str):
        raise ValueError(f"{label} must contain a string data_through value")
    try:
        parsed_date = date.fromisoformat(data_through)
    except ValueError as exc:
        raise ValueError(f"{label} has an invalid data_through date") from exc
    if parsed_date.isoformat() != data_through:
        raise ValueError(f"{label} data_through must use YYYY-MM-DD")
    last_updated = value.get("last_updated")
    if last_updated is not None:
        if not isinstance(last_updated, str):
            raise ValueError(f"{label} has a non-string last_updated timestamp")
        try:
            timestamp = datetime.fromisoformat(last_updated)
        except ValueError as exc:
            raise ValueError(f"{label} has an invalid last_updated timestamp") from exc
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError(f"{label} last_updated timestamp must include a timezone")
    return value


def _build_shooting_version(
    geojson: JsonObject,
    freshness: JsonObject,
    *,
    release_token: ReleaseToken | None = None,
) -> ShootingVersionSnapshot:
    """Validate and fully build a shooting version without mutating app state."""
    if geojson.get("type") != "FeatureCollection":
        raise ValueError("Shootings data must be a GeoJSON FeatureCollection")
    _ensure_strict_json(geojson, label="Shootings data")
    features = geojson.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError("Shootings data must contain at least one feature")

    rows: dict[int, list[JsonObject]] = {}
    for index, raw_feature in enumerate(features):
        if not isinstance(raw_feature, dict) or raw_feature.get("type") != "Feature":
            raise ValueError(f"Shootings feature {index} is invalid")
        row = _flatten_feature_to_row(raw_feature, index)
        year = row["year"]
        if not isinstance(year, int):
            raise ValueError(f"Shootings feature {index} did not produce a year")
        rows.setdefault(year, []).append(row)

    rows_by_year = {year: tuple(year_rows) for year, year_rows in rows.items()}
    years = tuple(sorted(rows_by_year))
    if sum(len(year_rows) for year_rows in rows_by_year.values()) != len(features):
        raise ValueError("Every shooting feature must belong to exactly one year")

    version = _compute_version_hash(geojson)
    generated_at = freshness.get("last_updated")
    if not isinstance(generated_at, str) or not generated_at:
        generated_at = datetime.now(UTC).isoformat()
    years_meta = {
        year: {
            "rows": len(rows_by_year[year]),
            "rows_url": f"/shootings/rows/{version}/{year}.ndjson",
        }
        for year in years
    }
    meta: JsonObject = {
        "version": version,
        "generated_at": generated_at,
        "rows": len(features),
        "years": list(years),
        "years_meta": years_meta,
    }
    return ShootingVersionSnapshot(
        version=version,
        years=years,
        rows_by_year=rows_by_year,
        meta=meta,
        release_token=release_token,
        freshness=freshness,
    )


def _shootings_release_token(release: _ShootingsRelease) -> ReleaseToken:
    """Return the immutable object identity for one shootings release."""
    return (
        release.data.key,
        release.data.sha256,
        release.metadata.key,
        release.metadata.sha256,
    )


def _load_shooting_release_version(
    s3: S3Client,
    release: _ShootingsRelease,
    *,
    candidates: tuple[ShootingVersionSnapshot, ...],
    label: str,
) -> ShootingVersionSnapshot:
    """Reuse a validated immutable release or build it exactly once."""
    release_token = _shootings_release_token(release)
    for candidate in candidates:
        if candidate.release_token == release_token:
            return candidate

    geojson = _read_verified_json(s3, release.data, label=f"{label} data")
    freshness = _validate_freshness(
        _read_verified_json(s3, release.metadata, label=f"{label} metadata"),
        label=f"{label} metadata",
    )
    return _build_shooting_version(
        geojson,
        freshness,
        release_token=release_token,
    )


def _shootings_pointer(
    s3: S3Client,
) -> tuple[_ShootingsRelease | None, _ShootingsRelease | None, str | None]:
    """Read the common public pointer, accepting its pre-release schema."""
    try:
        body, etag = _get_object_bytes(s3, PUBLIC_DOWNLOAD_MANIFEST_KEY)
    except FileNotFoundError:
        return None, None, None
    manifest = _decode_json(body, label="Public download manifest")
    application = manifest.get("application_data")
    if application is None:
        if manifest.get("previous_application_data") is not None:
            raise ValueError("Public manifest has N-1 application data without a current release")
        return None, None, etag
    try:
        manifest_release_id = _version_release_id(
            manifest.get("version"),
            label="Public download manifest version",
        )
        current = _ShootingsRelease.model_validate(application)
        previous_value = manifest.get("previous_application_data")
        previous = (
            _ShootingsRelease.model_validate(previous_value) if previous_value is not None else None
        )
        _validate_shootings_release_keys(
            current,
            label="Current shootings",
            expected_release_id=manifest_release_id,
        )
        if previous is not None:
            _validate_shootings_release_keys(previous, label="Previous shootings")
        return current, previous, etag
    except ValidationError as exc:
        raise ValueError("Public download manifest has invalid application release data") from exc


def _legacy_shootings_source(
    app: FastAPI,
    pointer_etag: str | None,
) -> tuple[JsonObject, JsonObject, SourceToken]:
    """Read legacy stable objects during the backward-compatible rollout."""
    s3 = app.state.s3
    geojson = read_processed_geojson_json("shootings", s3=s3)
    freshness = read_processed_json("shootings_meta", s3=s3)
    if not isinstance(geojson, dict) or not isinstance(freshness, dict):
        raise ValueError("Legacy shootings objects must contain JSON objects")
    if freshness.get("release_pointer_schema_version") is not None:
        raise RuntimeError("Shootings release pointer is required but unavailable")
    data_etag = _get_s3_etag(s3, app.state.dataset_keys["shootings"])
    meta_etag = _get_s3_etag(s3, app.state.dataset_keys["shootings_meta"])
    return geojson, freshness, ("legacy", pointer_etag or "", data_etag, meta_etag)


def _build_shootings_snapshot(app: FastAPI) -> ShootingsSnapshot:
    """Build the current shootings release entirely off-state."""
    s3 = app.state.s3
    existing = get_data_snapshot(app).shootings
    release, previous_release, pointer_etag = _shootings_pointer(s3)
    if release is None:
        if existing is not None and existing.source_kind == "release":
            raise RuntimeError("Published shootings release pointer disappeared")
        geojson, freshness, source_token = _legacy_shootings_source(app, pointer_etag)
        source_kind: Literal["release", "legacy"] = "legacy"
        freshness = _validate_freshness(freshness, label="Shootings metadata")
        current_version = _build_shooting_version(geojson, freshness)
    else:
        candidates = (
            ()
            if existing is None
            else tuple(
                candidate
                for candidate in (existing.current, existing.previous)
                if candidate is not None
            )
        )
        current_version = _load_shooting_release_version(
            s3,
            release,
            candidates=candidates,
            label="Shootings release",
        )
        if current_version.freshness is None:
            raise RuntimeError("Release-backed shootings data is missing freshness metadata")
        freshness = current_version.freshness
        source_token = ("release", pointer_etag or "")
        source_kind = "release"

    previous = None
    if previous_release is not None:
        previous_candidates = (
            current_version,
            *(
                ()
                if existing is None
                else tuple(
                    candidate
                    for candidate in (existing.current, existing.previous)
                    if candidate is not None
                )
            ),
        )
        pointed_previous = _load_shooting_release_version(
            s3,
            previous_release,
            candidates=previous_candidates,
            label="Previous shootings release",
        )
        if pointed_previous.version != current_version.version:
            previous = pointed_previous
    elif existing is not None:
        previous = existing.previous
        if existing.current.version != current_version.version:
            previous = existing.current
    return ShootingsSnapshot(
        current=current_version,
        previous=previous,
        freshness=freshness,
        source_kind=source_kind,
        source_token=source_token,
    )


def _install_snapshot(app: FastAPI, snapshot: AppDataSnapshot) -> None:
    """Atomically publish one fully constructed application snapshot."""
    app.state.data_snapshot = snapshot
    app.state.stats_page_cache = None


def load_shootings_data(app: FastAPI) -> None:
    """Build, validate, and atomically swap shooting data."""
    shootings = _build_shootings_snapshot(app)
    _install_snapshot(app, replace(get_data_snapshot(app), shootings=shootings))


def _validate_boundary_release_keys(release: BoundaryReleaseManifest) -> None:
    """Constrain every member to one content-addressed reference directory."""
    validate_boundary_release_manifest(
        release,
        reference_prefix=settings.s3_reference_prefix,
    )


def _boundary_pointer(
    s3: S3Client,
) -> tuple[BoundaryReleaseManifest | None, JsonObject | None, str]:
    """Read and validate either the atomic pointer or its rollout predecessor."""
    try:
        body, etag = _get_object_bytes(s3, get_reference_key(BOUNDARY_RELEASE_POINTER_FILENAME))
    except FileNotFoundError:
        body, etag = _get_object_bytes(s3, get_reference_key(LEGACY_BOUNDARY_MANIFEST_FILENAME))
        legacy = _decode_json(body, label="Legacy boundaries manifest")
        datasets = legacy.get("datasets")
        legacy["datasets"] = validate_legacy_boundary_datasets(datasets)
        return None, legacy, etag
    manifest = _decode_json(body, label="Boundaries release manifest")
    try:
        release = BoundaryReleaseManifest.model_validate(manifest)
    except ValidationError as exc:
        raise ValueError("Boundaries release manifest is invalid") from exc
    _validate_boundary_release_keys(release)
    return release, None, etag


def _validate_boundary_collection(value: JsonObject, *, dataset: str) -> None:
    validate_boundary_collection(dataset, value)
    _ensure_strict_json(value, label=f"Boundary dataset '{dataset}'")


def _build_boundaries_snapshot(app: FastAPI) -> BoundariesSnapshot:
    s3 = app.state.s3
    release, legacy, pointer_etag = _boundary_pointer(s3)
    existing = get_data_snapshot(app).boundaries
    if release is None and existing is not None and existing.source_kind == "release":
        raise RuntimeError("Published boundary release pointer was replaced by a legacy manifest")

    datasets: dict[str, JsonObject] = {}
    if release is not None:
        for dataset, member in release.datasets.items():
            collection = _read_verified_json(
                s3,
                _ReleaseObject(key=member.key, sha256=member.sha256),
                label=f"Boundary dataset '{dataset}'",
            )
            _validate_boundary_collection(collection, dataset=dataset)
            datasets[dataset] = collection
        source_kind: Literal["release", "legacy"] = "release"
    else:
        if legacy is None:
            raise RuntimeError("Boundary pointer parser returned no manifest")
        legacy_datasets = legacy["datasets"]
        if not isinstance(legacy_datasets, dict):
            raise ValueError("Legacy boundaries manifest must contain datasets")
        for dataset, key in legacy_datasets.items():
            if not isinstance(dataset, str) or not isinstance(key, str):
                raise ValueError("Legacy boundary manifest names and keys must be strings")
            collection = read_reference_json(key, s3=s3)
            if not isinstance(collection, dict):
                raise ValueError(f"Legacy boundary dataset '{dataset}' must be an object")
            _validate_boundary_collection(collection, dataset=dataset)
            datasets[dataset] = collection
        source_kind = "legacy"
    return BoundariesSnapshot(
        datasets=datasets,
        source_kind=source_kind,
        source_token=(source_kind, pointer_etag),
    )


def load_boundary_data(app: FastAPI) -> None:
    """Build, validate, and atomically swap all boundary data."""
    boundaries = _build_boundaries_snapshot(app)
    _install_snapshot(app, replace(get_data_snapshot(app), boundaries=boundaries))


def _build_streets_snapshot(app: FastAPI) -> StreetsSnapshot:
    s3 = app.state.s3
    streets_key = app.state.dataset_keys["streets"]
    body, etag = _get_object_bytes(s3, streets_key)
    collection = _decode_json(body, label="Street data")
    if collection.get("type") != "FeatureCollection":
        raise ValueError("Street data must be a GeoJSON FeatureCollection")
    _ensure_strict_json(collection, label="Street data")
    features = collection.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError("Street data must contain a nonempty features list")
    by_segment_id: dict[str, JsonObject] = {}
    for index, feature in enumerate(features):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ValueError(f"Street feature {index} must be a GeoJSON Feature")
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            raise ValueError(f"Street feature {index} has invalid properties")
        segment_id = properties.get("segment_id")
        if not isinstance(segment_id, str) or not segment_id.strip():
            raise ValueError(f"Street feature {index} has a blank or invalid segment_id")
        normalized = segment_id.strip()
        if normalized in by_segment_id:
            raise ValueError(f"Street data has duplicate segment_id '{normalized}'")
        by_segment_id[normalized] = feature
    return StreetsSnapshot(
        collection=collection,
        by_segment_id=by_segment_id,
        source_token=("legacy", etag),
    )


def load_streets_data(app: FastAPI) -> None:
    """Build, validate, and atomically swap street blocks."""
    streets = _build_streets_snapshot(app)
    _install_snapshot(app, replace(get_data_snapshot(app), streets=streets))


def _validate_homicide_totals(value: JsonObject) -> JsonObject:
    try:
        parsed = _HomicideTotals.model_validate(value)
    except ValidationError as exc:
        raise ValueError("Homicide totals failed schema validation") from exc
    for year in parsed.root:
        if len(year) != 4 or not year.isdigit():
            raise ValueError(f"Homicide totals has invalid year key '{year}'")
    # Return Pydantic's normalized copy instead of the untrusted input object.
    # Strict numeric fields reject booleans and numeric strings at the boundary.
    return parsed.model_dump(mode="json")


def _homicides_pointer(app: FastAPI) -> tuple[_HomicidesRelease | None, str | None]:
    key = app.state.dataset_keys["homicides_release"]
    try:
        body, etag = _get_object_bytes(app.state.s3, key)
    except FileNotFoundError:
        return None, None
    try:
        release = _HomicidesRelease.model_validate(_decode_json(body, label="Homicides release"))
    except ValidationError as exc:
        raise ValueError("Homicides release pointer is invalid") from exc
    _validate_homicides_release_keys(release)
    return release, etag


def _build_homicides_snapshot(app: FastAPI) -> HomicidesSnapshot:
    s3 = app.state.s3
    release, pointer_etag = _homicides_pointer(app)
    if release is None:
        totals = read_processed_json("homicides_totals", s3=s3)
        freshness = read_processed_json("homicides_meta", s3=s3)
        if not isinstance(totals, dict) or not isinstance(freshness, dict):
            raise ValueError("Legacy homicide objects must contain JSON objects")
        if freshness.get("release_pointer_schema_version") is not None:
            raise RuntimeError("Homicide release pointer is required but unavailable")
        source_token: SourceToken = (
            "legacy",
            _get_s3_etag(s3, app.state.dataset_keys["homicides"]),
            _get_s3_etag(s3, app.state.dataset_keys["homicides_meta"]),
        )
        source_kind: Literal["release", "legacy"] = "legacy"
    else:
        totals = _read_verified_json(s3, release.totals, label="Homicide release totals")
        freshness = _read_verified_json(
            s3,
            release.metadata,
            label="Homicide release metadata",
        )
        source_token = ("release", pointer_etag or "")
        source_kind = "release"
    return HomicidesSnapshot(
        totals=_validate_homicide_totals(totals),
        freshness=_validate_freshness(freshness, label="Homicide metadata"),
        source_kind=source_kind,
        source_token=source_token,
    )


def load_homicides_data(app: FastAPI) -> None:
    """Build, validate, and atomically swap homicide totals and metadata."""
    homicides = _build_homicides_snapshot(app)
    _install_snapshot(app, replace(get_data_snapshot(app), homicides=homicides))


def _current_source_token(app: FastAPI, name: str) -> SourceToken:
    """Read only the object versions needed to decide whether to reload."""
    s3 = app.state.s3
    snapshot = get_data_snapshot(app)
    if name == "shootings":
        shootings = require_shootings(snapshot)
        pointer_etag = _get_optional_s3_etag(s3, PUBLIC_DOWNLOAD_MANIFEST_KEY)
        if shootings.source_kind == "release":
            return ("release", pointer_etag or "")
        return (
            "legacy",
            pointer_etag or "",
            _get_s3_etag(s3, app.state.dataset_keys["shootings"]),
            _get_s3_etag(s3, app.state.dataset_keys["shootings_meta"]),
        )
    if name == "homicides":
        homicides = require_homicides(snapshot)
        pointer_etag = _get_optional_s3_etag(s3, app.state.dataset_keys["homicides_release"])
        if pointer_etag is not None:
            return ("release", pointer_etag)
        if homicides.source_kind == "release":
            raise RuntimeError("Published homicide release pointer disappeared")
        return (
            "legacy",
            _get_s3_etag(s3, app.state.dataset_keys["homicides"]),
            _get_s3_etag(s3, app.state.dataset_keys["homicides_meta"]),
        )
    if name == "streets":
        return ("legacy", _get_s3_etag(s3, app.state.dataset_keys["streets"]))
    if name == "boundaries_manifest":
        release, _, pointer_etag = _boundary_pointer(s3)
        boundaries = require_boundaries(snapshot)
        source_kind: Literal["release", "legacy"] = "release" if release is not None else "legacy"
        if boundaries.source_kind == "release" and source_kind == "legacy":
            raise RuntimeError("Published boundary release pointer disappeared")
        return (source_kind, pointer_etag)
    raise KeyError(f"Unknown dataset name '{name}'")


def _loaded_source_token(snapshot: AppDataSnapshot, name: str) -> SourceToken:
    if name == "shootings":
        return require_shootings(snapshot).source_token
    if name == "homicides":
        return require_homicides(snapshot).source_token
    if name == "streets":
        return require_streets(snapshot).source_token
    if name == "boundaries_manifest":
        return require_boundaries(snapshot).source_token
    raise KeyError(f"Unknown dataset name '{name}'")


def _reload_dataset(app: FastAPI, name: str) -> None:
    if name == "shootings":
        load_shootings_data(app)
    elif name == "homicides":
        load_homicides_data(app)
    elif name == "streets":
        load_streets_data(app)
    elif name == "boundaries_manifest":
        load_boundary_data(app)
    else:
        raise KeyError(f"Unknown dataset name '{name}'")


def refresh_if_stale(app: FastAPI, names: list[str]) -> None:
    """Serialize refresh, atomically swap successes, and serve stale on failures."""
    ttl = settings.api_refresh_ttl_seconds
    lock = app.state.dataset_refresh_lock
    if not isinstance(lock, Lock):
        raise RuntimeError("Dataset refresh lock is not initialized")
    # One request performs the refresh. Concurrent requests immediately keep
    # serving the complete old snapshot instead of queueing behind S3 I/O.
    if not lock.acquire(blocking=False):
        return
    try:
        for name in names:
            now = time.monotonic()
            last_checked = app.state.dataset_last_checked.get(name)
            if last_checked is not None and now - last_checked < ttl:
                continue
            last_failed = app.state.dataset_last_failed.get(name)
            if (
                last_failed is not None
                and now - last_failed < settings.api_refresh_failure_backoff_seconds
            ):
                continue
            try:
                loaded = _loaded_source_token(get_data_snapshot(app), name)
                current = _current_source_token(app, name)
                if current != loaded:
                    _reload_dataset(app, name)
            except Exception:
                logger.exception("Dataset refresh failed; serving the previous {} snapshot", name)
                app.state.dataset_last_failed[name] = time.monotonic()
                continue
            app.state.dataset_last_failed.pop(name, None)
            app.state.dataset_last_checked[name] = time.monotonic()
    finally:
        lock.release()


def make_refresh_dependency(names: list[str]) -> Callable[[Request], None]:
    """Create a FastAPI dependency that lazily refreshes named datasets."""

    def _refresh(request: Request) -> None:
        refresh_if_stale(request.app, names)

    return _refresh
