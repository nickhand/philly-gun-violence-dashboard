"""Street blocks endpoints."""

from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Query, Request

from app.data_loader import make_refresh_dependency
from app.models.page import Page
from app.utils.pagination import build_page, paginate_features
from dashboard_utils.models.streets import StreetBlockFeature

router = APIRouter(dependencies=[Depends(make_refresh_dependency(["streets"]))])


class StreetsPage(Page):
    """Paginated street blocks GeoJSON response."""

    type: Literal["FeatureCollection"]
    features: list[StreetBlockFeature]


@router.get("/streets")
def get_streets(
    request: Request,
    segment_id: Annotated[list[str] | None, Query()] = None,
    limit: Annotated[int, Query(ge=0)] = 2000,
    offset: Annotated[int, Query(ge=0)] = 0,
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
    limit = max(limit, 0)
    if not segment_id:
        page_features, count, next_offset, total = paginate_features(
            request.app.state.streets_geojson["features"],
            limit=limit,
            offset=offset,
        )
    else:
        features_source = [
            request.app.state.streets_by_segment_id[sid]
            for sid in segment_id
            if sid in request.app.state.streets_by_segment_id
        ]
        page_features, count, next_offset, total = paginate_features(
            features_source,
            limit=limit,
            offset=offset,
        )
    return cast(
        StreetsPage,
        build_page(
            features=page_features,
            limit=limit,
            offset=offset,
            count=count,
            total=total,
            next_offset=next_offset,
        ),
    )
