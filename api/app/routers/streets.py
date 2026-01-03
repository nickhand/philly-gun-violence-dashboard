"""Street blocks endpoints."""

from typing import Literal, cast

from fastapi import APIRouter, Query, Request

from app.data_loader import refresh_if_stale
from app.models.page import Page
from dashboard_utils.models.streets import StreetBlockFeature

router = APIRouter()


class StreetsPage(Page):
    """Paginated street blocks GeoJSON response."""

    type: Literal["FeatureCollection"]
    features: list[StreetBlockFeature]


@router.get("/streets")
def get_streets(
    request: Request,
    segment_id: list[str] | None = None,
    limit: int = Query(2000, ge=0),
    offset: int = Query(0, ge=0),
) -> StreetsPage:
    """Return street block GeoJSON filtered by segment IDs.

    Parameters
    ----------
    request : fastapi.Request
        The current request with access to application state.
    segment_id : list[str] | None, optional
        Segment IDs to filter by; if omitted, return all features.
    limit : int, optional
        Maximum number of features to return.
    offset : int, optional
        Zero-based index of the first feature to return.

    Returns
    -------
    StreetsPage
        Paginated GeoJSON FeatureCollection with pagination metadata.
    """
    refresh_if_stale(request.app, ["streets"])
    limit = max(limit, 0)
    if not segment_id:
        features_source = request.app.state.streets_geojson["features"]
        total = len(features_source)
        page_features = features_source[offset : offset + limit]
    else:
        features_source = [
            request.app.state.streets_by_segment_id[sid]
            for sid in segment_id
            if sid in request.app.state.streets_by_segment_id
        ]
        total = len(features_source)
        page_features = features_source[offset : offset + limit]
    count = len(page_features)
    next_offset = offset + count if offset + count < total else None
    return cast(
        StreetsPage,
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
