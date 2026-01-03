"""Data loading utilities for API startup and refresh."""

import time
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from mypy_boto3_s3.client import S3Client

from app.config import settings
from dashboard_utils.aws import read_json
from dashboard_utils.constants import DATE_FORMAT
from dashboard_utils.paths import data_dir, get_processed_path


def _s3_key_from_path(path: str) -> str:
    """Convert a local or s3:// path into an S3 object key.

    Parameters
    ----------
    path : str
        A local filesystem path under the data directory or an s3:// URI.

    Returns
    -------
    str
        The S3 key relative to the bucket root.
    """
    candidate = Path(path)
    if candidate.parts and candidate.parts[0] == "s3:":
        return "/".join(candidate.parts[2:])
    return str(candidate.relative_to(Path(data_dir())))


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


def _get_processed_key(name: str) -> str:
    """Return the S3 key for a processed dataset name."""
    return _s3_key_from_path(str(get_processed_path(name)))


def _get_s3_etag(s3: S3Client, key: str) -> str:
    """Return the ETag for an S3 object key."""
    response = s3.head_object(Bucket=settings.AWS_BUCKET_NAME, Key=key)
    return str(response.get("ETag", "")).strip('"')


def init_dataset_keys(app: FastAPI) -> None:
    """Initialize dataset keys for refresh checks."""
    # Keep dataset names centralized so refresh logic stays consistent.
    app.state.dataset_keys = {
        "shootings": _get_processed_key("shootings"),
        "streets": _get_processed_key("street_blocks"),
        "homicides": _get_processed_key("homicides_totals"),
        "boundaries_manifest": "reference/boundaries_manifest.json",
    }
    # Track the last-seen ETag to detect upstream changes cheaply.
    app.state.dataset_etags = {}
    app.state.dataset_last_checked = {}


def load_shootings_data(app: FastAPI) -> None:
    """Load shootings data into application state.

    Parameters
    ----------
    app : fastapi.FastAPI
        The FastAPI application instance.
    """
    s3 = app.state.s3
    shootings_key = app.state.dataset_keys["shootings"]
    shootings_geojson = read_json(
        s3,
        settings.AWS_BUCKET_NAME,
        shootings_key,
    )
    # Keep a stable list of features and build an index for fast year filtering.
    shootings_features = list(shootings_geojson.get("features", []))
    shootings_year_index: dict[int, list[int]] = {}
    for idx, feature in enumerate(shootings_features):
        year = _extract_year(feature.get("properties", {}).get("date"))
        if year is None:
            continue
        shootings_year_index.setdefault(year, []).append(idx)
    shootings_years = sorted(shootings_year_index)
    app.state.shootings_geojson = shootings_geojson
    app.state.shootings_features = shootings_features
    app.state.shootings_year_index = shootings_year_index
    app.state.shootings_years = shootings_years
    app.state.dataset_etags["shootings"] = _get_s3_etag(s3, shootings_key)


def load_boundary_data(app: FastAPI) -> None:
    """Load boundary GeoJSON data into application state.

    Parameters
    ----------
    app : fastapi.FastAPI
        The FastAPI application instance.
    """
    s3 = app.state.s3
    manifest_key = app.state.dataset_keys["boundaries_manifest"]
    manifest = read_json(
        s3,
        settings.AWS_BUCKET_NAME,
        manifest_key,
    )
    datasets = manifest.get("datasets", {})
    boundaries = {
        dataset: read_json(s3, settings.AWS_BUCKET_NAME, key) for dataset, key in datasets.items()
    }
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
    streets_geojson = read_json(
        s3,
        settings.AWS_BUCKET_NAME,
        streets_key,
    )
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
    homicides_totals = read_json(
        s3,
        settings.AWS_BUCKET_NAME,
        homicides_key,
    )
    app.state.homicides_totals = homicides_totals
    app.state.dataset_etags["homicides"] = _get_s3_etag(s3, homicides_key)


def refresh_if_stale(app: FastAPI, names: list[str]) -> None:
    """Refresh cached datasets if their TTL has expired and ETags changed."""
    s3 = app.state.s3
    # TTL controls how often we check S3 for updates per dataset.
    ttl = settings.API_REFRESH_TTL_SECONDS
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
