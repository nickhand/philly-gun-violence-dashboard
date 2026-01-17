"""Shootings endpoints.

This module provides endpoints for accessing shootings data:
- `/shootings/meta` - Primary entry point with version, metadata, and per-year URLs
- `/shootings/rows/{version}/{year}.ndjson` - Year-specific NDJSON for Arquero (immutable)
"""

import json
from collections.abc import Iterator
from typing import Any, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
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
    2. Use `years_meta[year].rows_url` to fetch NDJSON data for a specific year

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


@router.get("/shootings/rows/{version}/{year}.ndjson")
def get_shootings_rows_by_year(
    request: Request,
    version: str,
    year: int,
) -> StreamingResponse:
    """Return shootings data for a specific year as NDJSON.

    Each line is a JSON object representing a flattened shooting record with:
    - `lon`, `lat`: Coordinates extracted from geometry
    - `dateInMs`: Date as Unix timestamp in milliseconds
    - `timeInMs`: Milliseconds since midnight
    - `weekday`: Day of week (0=Sunday, 6=Saturday)
    - `year`: Year of incident
    - All properties from the original GeoJSON features

    This endpoint is versioned and immutable - the same version always returns
    the same data, enabling aggressive client-side caching.

    Parameters
    ----------
    request : fastapi.Request
        The current request with access to application state.
    version : str
        The version string (must match current dataset version).
    year : int
        The year to fetch data for.

    Returns
    -------
    StreamingResponse
        NDJSON stream with immutable cache headers.

    Raises
    ------
    HTTPException
        404 if version doesn't match or year not available.
    """
    current_version = request.app.state.shootings_version
    if version != current_version:
        raise HTTPException(
            status_code=404,
            detail=f"Version '{version}' not found. Current version is '{current_version}'.",
        )

    rows_by_year = request.app.state.shootings_rows_by_year
    if year not in rows_by_year:
        available_years = sorted(rows_by_year.keys())
        raise HTTPException(
            status_code=404,
            detail=f"Year {year} not found. Available years: {available_years}",
        )

    def generate_ndjson() -> Iterator[str]:
        """Stream NDJSON rows for the specified year."""
        for row in rows_by_year[year]:
            yield json.dumps(row, separators=(",", ":")) + "\n"

    return StreamingResponse(
        generate_ndjson(),
        media_type="application/x-ndjson; charset=utf-8",
        headers={"Cache-Control": IMMUTABLE_CACHE_CONTROL},
    )
