"""Shootings endpoints.

This module provides endpoints for accessing shootings data:
- `/shootings/meta` - Primary entry point with version, metadata, and per-year URLs
- `/shootings/rows/{version}/{year}.ndjson` - Year-specific NDJSON for Arquero (immutable)
"""

import hashlib
import json
from collections.abc import Iterator
from typing import Any, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.data_loader import make_refresh_dependency

router = APIRouter(dependencies=[Depends(make_refresh_dependency(["shootings"]))])

# Cache headers for immutable versioned assets (1 year)
IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable"
# Cache headers for meta endpoint (must revalidate)
META_CACHE_CONTROL = "max-age=0, must-revalidate"


class ShootingYearManifest(BaseModel):
    """Row count and versioned download URL for one calendar year."""

    rows: int = Field(description="Number of shooting-victim rows for the year.")
    rows_url: str = Field(description="Versioned NDJSON path for the year.")


class ShootingsManifest(BaseModel):
    """Current shooting-data version and its year-specific downloads."""

    version: str = Field(description="Content-derived version of the current dataset.")
    generated_at: str = Field(description="UTC time when this API manifest was generated.")
    rows: int = Field(description="Total number of shooting-victim rows.")
    years: list[int] = Field(description="Calendar years available for download.")
    years_meta: dict[int, ShootingYearManifest] = Field(
        description="Row count and NDJSON path for each available year."
    )


NDJSON_RESPONSE: dict[int | str, dict[str, Any]] = {
    200: {
        "description": (
            "Newline-delimited JSON with one processed shooting-victim record per line."
        ),
        "content": {
            "application/x-ndjson": {
                "schema": {
                    "type": "string",
                    "description": (
                        "An NDJSON stream. Each line is one JSON object representing one "
                        "shooting victim, including normalized date fields, coordinates "
                        "when available, published or normalized demographic fields, and "
                        "geographic joins."
                    ),
                }
            }
        },
    }
}


@router.get(
    "/shootings/meta",
    response_model=ShootingsManifest,
    responses={304: {"description": "The current manifest version has not changed."}},
)
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
    etag = hashlib.sha256(
        json.dumps(meta, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    headers = {
        "ETag": f'"{etag}"',
        "Cache-Control": META_CACHE_CONTROL,
    }

    # Check for conditional request
    if if_none_match and if_none_match.strip('"') == etag:
        return Response(status_code=304, headers=headers)

    # Set cache headers
    response.headers.update(headers)

    return cast(dict[str, Any], meta)


@router.get(
    "/shootings/rows/{version}/{year}.ndjson",
    response_class=StreamingResponse,
    responses=NDJSON_RESPONSE,
)
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
        headers={
            "Cache-Control": IMMUTABLE_CACHE_CONTROL,
            "X-Robots-Tag": "noindex",
        },
    )
