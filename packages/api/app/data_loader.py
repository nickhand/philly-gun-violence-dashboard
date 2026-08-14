"""Data loading utilities for API startup and refresh."""

import hashlib
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from mypy_boto3_s3.client import S3Client

from app.config import settings
from dashboard_utils.constants import DATE_FORMAT
from dashboard_utils.paths import get_processed_key, get_reference_key
from dashboard_utils.processed import (
    read_processed_geojson_json,
    read_processed_json,
    read_reference_json,
)


def _extract_year(value: str | None) -> int | None:
    """Extract a year from a date-like string.

    Parameters
    ----------
    value : str | None
        The date string (expected to begin with a 4-digit year).

    Returns
    -------
    int | None
        The parsed year if available and valid; otherwise None.
    """
    if not value:
        return None
    try:
        return datetime.strptime(value, DATE_FORMAT).year
    except ValueError:
        return None


def _get_s3_etag(s3: S3Client, key: str) -> str:
    """Return the ETag for an S3 object key."""
    response = s3.head_object(Bucket=settings.s3_bucket, Key=key)
    return str(response.get("ETag", "")).strip('"')


def init_dataset_keys(app: FastAPI) -> None:
    """Initialize dataset keys for refresh checks."""
    # Keep dataset names centralized so refresh logic stays consistent.
    app.state.dataset_keys = {
        "shootings": get_processed_key("shootings"),
        "streets": get_processed_key("street_blocks"),
        "homicides": get_processed_key("homicides_totals"),
        "boundaries_manifest": get_reference_key("boundaries_manifest.json"),
    }
    # Track the last-seen ETag to detect upstream changes cheaply.
    app.state.dataset_etags = {}
    app.state.dataset_last_checked = {}


def _compute_version_hash(data: Any) -> str:
    """Compute a short content hash for versioning.

    Parameters
    ----------
    data : Any
        The data to hash (will be JSON-serialized).

    Returns
    -------
    str
        A 12-character hex hash.
    """
    content = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(content).hexdigest()[:12]


def _flatten_feature_to_row(feature: dict[str, Any], index: int) -> dict[str, Any]:
    """Flatten a GeoJSON feature to a tabular row for Arquero.

    Adds derived time fields matching the frontend's normalizeShootingsData:
    - `dateInMs`: Timestamp of the incident date
    - `timeInMs`: Milliseconds since midnight of the incident date
    - `weekday`: Day of the week (0=Sunday, 6=Saturday)
    - `unique_id`: Unique identifier for each feature

    Parameters
    ----------
    feature : dict[str, Any]
        A GeoJSON Feature with geometry and properties.
    index : int
        The index of the feature in the collection (used for unique_id).

    Returns
    -------
    dict[str, Any]
        Flattened row with lon, lat, derived time fields, and all properties.
    """
    props = feature.get("properties", {}).copy()
    geometry = feature.get("geometry", {})
    coords = geometry.get("coordinates", [None, None]) if geometry else [None, None]

    # Extract lon/lat from Point geometry
    lon = coords[0] if coords and len(coords) >= 1 else None
    lat = coords[1] if coords and len(coords) >= 2 else None

    # Parse date and compute derived time fields (matching frontend normalizeShootingsData)
    date_str = props.get("date")
    date_in_ms: int | None = None
    time_in_ms: int | None = None
    weekday: int | None = None
    year: int | None = None

    if date_str:
        try:
            dt = datetime.strptime(date_str, DATE_FORMAT)
            # dateInMs: Unix timestamp in milliseconds (UTC)
            date_in_ms = int(dt.replace(tzinfo=UTC).timestamp() * 1000)
            # timeInMs: Milliseconds since midnight
            time_in_ms = (dt.hour * 3600 + dt.minute * 60 + dt.second) * 1000
            # weekday: Day of week (0=Monday in Python, but frontend expects 0=Sunday)
            # Python weekday(): Monday=0, Sunday=6
            # JS getDay(): Sunday=0, Saturday=6
            # Convert: (python_weekday + 1) % 7
            time_in_ms += dt.microsecond // 1000
            weekday = (dt.weekday() + 1) % 7
            year = dt.year
        except ValueError:
            pass

    row = {
        "lon": lon,
        "lat": lat,
        "dateInMs": date_in_ms,
        "timeInMs": time_in_ms,
        "weekday": weekday,
        "year": year,
        "unique_id": index,
        **props,
    }
    return row


def load_shootings_data(app: FastAPI) -> None:
    """Load shootings data into application state.

    Parameters
    ----------
    app : fastapi.FastAPI
        The FastAPI application instance.
    """
    s3 = app.state.s3
    shootings_key = app.state.dataset_keys["shootings"]
    shootings_geojson = read_processed_geojson_json("shootings", s3=s3)
    shootings_features = list(shootings_geojson.get("features", []))

    # Store rows indexed by year for per-year endpoints
    shootings_rows_by_year: dict[int, list[dict[str, Any]]] = {}

    for idx, feature in enumerate(shootings_features):
        year = _extract_year(feature.get("properties", {}).get("date"))
        if year is not None:
            # Flatten feature to row for NDJSON endpoint (pass index for unique_id)
            row = _flatten_feature_to_row(feature, idx)
            shootings_rows_by_year.setdefault(year, []).append(row)

    shootings_years = sorted(shootings_rows_by_year.keys())

    # Compute content-based version hash
    version = _compute_version_hash(shootings_geojson)
    generated_at = datetime.now(UTC).isoformat()

    # Build per-year URLs for efficient loading
    years_meta = {
        year: {
            "rows": len(shootings_rows_by_year.get(year, [])),
            "rows_url": f"/shootings/rows/{version}/{year}.ndjson",
        }
        for year in shootings_years
    }

    # Build metadata
    shootings_meta = {
        "version": version,
        "generated_at": generated_at,
        "rows": len(shootings_features),
        "years": shootings_years,
        "years_meta": years_meta,
    }

    app.state.shootings_years = shootings_years
    app.state.shootings_rows_by_year = shootings_rows_by_year
    app.state.shootings_meta = shootings_meta
    app.state.shootings_version = version
    app.state.shootings_freshness = read_processed_json("shootings_meta", s3=s3)
    app.state.dataset_etags["shootings"] = _get_s3_etag(s3, shootings_key)
    app.state.stats_page_cache = None


def load_boundary_data(app: FastAPI) -> None:
    """Load boundary GeoJSON data into application state.

    Parameters
    ----------
    app : fastapi.FastAPI
        The FastAPI application instance.
    """
    s3 = app.state.s3
    manifest_key = app.state.dataset_keys["boundaries_manifest"]
    manifest = read_reference_json("boundaries_manifest.json", s3=s3)
    datasets = manifest.get("datasets", {})
    boundaries = {dataset: read_reference_json(key, s3=s3) for dataset, key in datasets.items()}
    app.state.boundaries = boundaries
    app.state.dataset_etags["boundaries_manifest"] = _get_s3_etag(s3, manifest_key)


def load_streets_data(app: FastAPI) -> None:
    """Load street blocks data into application state.

    Parameters
    ----------
    app : fastapi.FastAPI
        The FastAPI application instance.
    """
    s3 = app.state.s3
    streets_key = app.state.dataset_keys["streets"]
    streets_geojson = read_processed_geojson_json("street_blocks", s3=s3)
    # Build a lookup to avoid scanning the full feature list per request.
    streets_by_segment_id = {}
    for feature in streets_geojson.get("features", []):
        segment_id = feature.get("properties", {}).get("segment_id")
        if segment_id is None:
            continue
        streets_by_segment_id[str(segment_id)] = feature
    app.state.streets_geojson = streets_geojson
    app.state.streets_by_segment_id = streets_by_segment_id
    app.state.dataset_etags["streets"] = _get_s3_etag(s3, streets_key)


def load_homicides_data(app: FastAPI) -> None:
    """Load homicide totals data into application state.

    Parameters
    ----------
    app : fastapi.FastAPI
        The FastAPI application instance.
    """
    s3 = app.state.s3
    homicides_key = app.state.dataset_keys["homicides"]
    app.state.homicides_totals = read_processed_json("homicides_totals", s3=s3)
    app.state.homicides_freshness = read_processed_json("homicides_meta", s3=s3)
    app.state.dataset_etags["homicides"] = _get_s3_etag(s3, homicides_key)
    app.state.stats_page_cache = None


def refresh_if_stale(app: FastAPI, names: list[str]) -> None:
    """Refresh cached datasets if their TTL has expired and ETags changed."""
    s3 = app.state.s3
    # TTL controls how often we check S3 for updates per dataset.
    ttl = settings.api_refresh_ttl_seconds
    now = time.time()
    # Use ETag checks to avoid reloading unchanged objects.
    for name in names:
        key = app.state.dataset_keys.get(name)
        if key is None:
            continue
        last_checked = app.state.dataset_last_checked.get(name, 0)
        if now - last_checked < ttl:
            continue
        app.state.dataset_last_checked[name] = now
        etag = _get_s3_etag(s3, key)
        if etag == app.state.dataset_etags.get(name):
            continue
        if name == "shootings":
            load_shootings_data(app)
        elif name == "streets":
            load_streets_data(app)
        elif name == "homicides":
            load_homicides_data(app)
        elif name == "boundaries_manifest":
            load_boundary_data(app)


def make_refresh_dependency(names: list[str]) -> Callable[[Request], None]:
    """Create a FastAPI dependency that refreshes datasets lazily."""

    def _refresh(request: Request) -> None:
        refresh_if_stale(request.app, names)

    return _refresh
