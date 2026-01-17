"""Shootings endpoints.

This module provides endpoints for accessing shootings data:
- `/shootings/meta` - Primary entry point with version, metadata, and URLs
- `/shootings/rows/{version}.ndjson` - Versioned NDJSON for Arquero (immutable, cacheable)
- `/shootings/geojson/{version}.geojson` - Versioned GeoJSON for maps (immutable, cacheable)
"""

import json
from collections.abc import Iterator
from typing import Any, cast

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import StreamingResponse

from app.data_loader import make_refresh_dependency

router = APIRouter(dependencies=[Depends(make_refresh_dependency(["shootings"]))])

# Cache headers for immutable versioned assets (1 year)
IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable"
# Cache headers for meta endpoint (must revalidate)
META_CACHE_CONTROL = "max-age=0, must-revalidate"


@router.get("/shootings/meta", response_model=None)
def get_shootings_meta(
    request: Request,
    response: Response,
    if_none_match: str | None = Header(None),
) -> Response | dict[str, Any]:
    """Return metadata about the shootings dataset including version and URLs.

    This is the primary entry point. The frontend should:
    1. Fetch this endpoint to get the current version and available years
    2. Use `rows_url` to fetch NDJSON data for Arquero
    3. Use `geojson_url` to fetch GeoJSON for map rendering

    Supports ETag-based caching: if `If-None-Match` header matches the
    current version, returns 304 Not Modified.

    Parameters
    ----------
    request : fastapi.Request
        The current request with access to application state.
    response : fastapi.Response
        The response object for setting headers.
    if_none_match : str | None
        Optional ETag from client for conditional request.

    Returns
    -------
    Response | dict[str, Any]
        304 Not Modified if ETag matches, otherwise the metadata dict.
    """
    meta = request.app.state.shootings_meta
    version = meta["version"]

    # Check for conditional request
    if if_none_match and if_none_match.strip('"') == version:
        return Response(status_code=304)

    # Set cache headers
    response.headers["ETag"] = f'"{version}"'
    response.headers["Cache-Control"] = META_CACHE_CONTROL

    return cast(dict[str, Any], meta)


@router.get("/shootings/rows/{version}.ndjson")
def get_shootings_rows(
    request: Request,
    version: str,
) -> StreamingResponse:
    """Return shootings data as NDJSON (newline-delimited JSON) for Arquero.

    Each line is a JSON object representing a flattened shooting record with:
    - `lon`, `lat`: Coordinates extracted from geometry
    - `date_ms`: Date as Unix timestamp in milliseconds
    - All properties from the original GeoJSON features

    This endpoint is versioned and immutable - the same version always returns
    the same data, enabling aggressive client-side caching.

    Parameters
    ----------
    request : fastapi.Request
        The current request with access to application state.
    version : str
        The version string (must match current dataset version).

    Returns
    -------
    StreamingResponse
        NDJSON stream with immutable cache headers.

    Raises
    ------
    HTTPException
        404 if version doesn't match current dataset version.
    """
    from fastapi import HTTPException

    current_version = request.app.state.shootings_version
    if version != current_version:
        raise HTTPException(
            status_code=404,
            detail=f"Version '{version}' not found. Current version is '{current_version}'.",
        )

    def generate_ndjson() -> Iterator[str]:
        """Stream NDJSON rows one line at a time."""
        rows = request.app.state.shootings_rows
        for row in rows:
            yield json.dumps(row, separators=(",", ":")) + "\n"

    return StreamingResponse(
        generate_ndjson(),
        media_type="application/x-ndjson; charset=utf-8",
        headers={"Cache-Control": IMMUTABLE_CACHE_CONTROL},
    )


@router.get("/shootings/geojson/{version}.geojson")
def get_shootings_geojson_versioned(
    request: Request,
    version: str,
) -> Response:
    """Return the full shootings GeoJSON FeatureCollection (versioned).

    This endpoint is versioned and immutable - the same version always returns
    the same data, enabling aggressive client-side caching. Use for map rendering.

    Parameters
    ----------
    request : fastapi.Request
        The current request with access to application state.
    version : str
        The version string (must match current dataset version).

    Returns
    -------
    Response
        GeoJSON response with immutable cache headers.

    Raises
    ------
    HTTPException
        404 if version doesn't match current dataset version.
    """
    from fastapi import HTTPException

    current_version = request.app.state.shootings_version
    if version != current_version:
        raise HTTPException(
            status_code=404,
            detail=f"Version '{version}' not found. Current version is '{current_version}'.",
        )

    geojson = request.app.state.shootings_geojson
    content = json.dumps(geojson, separators=(",", ":"))

    return Response(
        content=content,
        media_type="application/geo+json",
        headers={"Cache-Control": IMMUTABLE_CACHE_CONTROL},
    )
