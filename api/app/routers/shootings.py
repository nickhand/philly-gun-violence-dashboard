"""Shootings endpoints."""

from typing import Literal, cast

from fastapi import APIRouter, Depends, Query, Request

from app.data_loader import make_refresh_dependency
from app.models.page import Page
from app.utils.pagination import build_page, paginate_features
from dashboard_utils.models.shootings import ShootingFeature

router = APIRouter(dependencies=[Depends(make_refresh_dependency(["shootings"]))])


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
    limit = max(limit, 0)
    if year is None:
        page_features, count, next_offset, total = paginate_features(
            request.app.state.shootings_features,
            limit=limit,
            offset=offset,
        )
    else:
        indices = request.app.state.shootings_year_index.get(year, [])
        page_indices, count, next_offset, total = paginate_features(
            indices,
            limit=limit,
            offset=offset,
        )
        page_features = [request.app.state.shootings_features[idx] for idx in page_indices]
    return cast(
        ShootingsPage,
        build_page(
            features=page_features,
            limit=limit,
            offset=offset,
            count=count,
            total=total,
            next_offset=next_offset,
        ),
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
    return {"years": request.app.state.shootings_years}
