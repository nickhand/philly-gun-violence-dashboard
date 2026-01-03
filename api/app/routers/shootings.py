"""Shootings endpoints."""

from typing import Literal, cast

from fastapi import APIRouter, Query, Request

from app.data_loader import refresh_if_stale
from app.models.page import Page
from dashboard_utils.models.shootings import ShootingFeature

router = APIRouter()


class ShootingsPage(Page):
    """Paginated shootings GeoJSON response."""

    type: Literal["FeatureCollection"]
    features: list[ShootingFeature]


@router.get("/shootings")
def get_shootings(
    request: Request,
    year: int | None = None,
    limit: int = Query(2000, ge=0),
    offset: int = Query(0, ge=0),
) -> ShootingsPage:
    """Return the shootings GeoJSON, optionally filtered by year.

    Parameters
    ----------
    request : fastapi.Request
        The current request with access to application state.
    year : int | None, optional
        If provided, only return features for the given year.
    limit : int, optional
        Maximum number of features to return.
    offset : int, optional
        Zero-based index of the first feature to return.

    Returns
    -------
    ShootingsPage
        Paginated GeoJSON FeatureCollection with pagination metadata.
    """
    refresh_if_stale(request.app, ["shootings"])
    limit = max(limit, 0)
    if year is None:
        features_source = request.app.state.shootings_features
        total = len(features_source)
        page_features = features_source[offset : offset + limit]
    else:
        indices = request.app.state.shootings_year_index.get(year, [])
        total = len(indices)
        page_features = [
            request.app.state.shootings_features[idx] for idx in indices[offset : offset + limit]
        ]
    count = len(page_features)
    next_offset = offset + count if offset + count < total else None
    return cast(
        ShootingsPage,
        {
            "type": "FeatureCollection",
            "features": page_features,
            "limit": limit,
            "offset": offset,
            "count": count,
            "total": total,
            "next_offset": next_offset,
        },
    )


@router.get("/shootings/years")
def get_shootings_years(request: Request) -> dict[str, list[int]]:
    """Return the set of years available in the shootings dataset.

    Parameters
    ----------
    request : fastapi.Request
        The current request with access to application state.

    Returns
    -------
    dict[str, list[int]]
        The list of available years under the "years" key.
    """
    refresh_if_stale(request.app, ["shootings"])
    return {"years": request.app.state.shootings_years}
