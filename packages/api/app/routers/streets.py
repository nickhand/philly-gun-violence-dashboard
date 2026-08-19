"""Street blocks endpoints."""

from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.data_loader import get_data_snapshot, make_refresh_dependency, require_streets
from app.models.page import Page
from app.utils.pagination import build_page, paginate_features
from dashboard_utils.models.streets import StreetBlockFeature

router = APIRouter(dependencies=[Depends(make_refresh_dependency(["streets"]))])
MAX_STREET_PAGE_SIZE = 5000
MAX_SEGMENT_IDS = 500
MAX_SEGMENT_IDS_QUERY_LENGTH = 10_000


class StreetsPage(Page):
    """Paginated street blocks GeoJSON response."""

    type: Literal["FeatureCollection"]
    features: list[StreetBlockFeature]


@router.get("/streets")
def get_streets(
    request: Request,
    segment_ids: Annotated[str | None, Query(max_length=MAX_SEGMENT_IDS_QUERY_LENGTH)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_STREET_PAGE_SIZE)] = 2000,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> StreetsPage:
    """Return street block GeoJSON filtered by segment IDs.

    Parameters
    ----------
    request : fastapi.Request
        The current request with access to application state.
    segment_ids : str | None, optional
        Comma-separated segment IDs to filter by; if omitted, return all features.
    limit : int, optional
        Maximum number of features to return.
    offset : int, optional
        Zero-based index of the first feature to return.

    Returns
    -------
    StreetsPage
        Paginated GeoJSON FeatureCollection with pagination metadata.
    """
    # Parse comma-separated segment IDs
    segment_id_list = (
        list(dict.fromkeys(sid.strip() for sid in segment_ids.split(",") if sid.strip()))
        if segment_ids
        else None
    )
    if segment_id_list and len(segment_id_list) > MAX_SEGMENT_IDS:
        raise HTTPException(
            status_code=422,
            detail=f"At most {MAX_SEGMENT_IDS} unique segment IDs may be requested",
        )
    streets = require_streets(get_data_snapshot(request.app))
    if not segment_id_list:
        page_features, count, next_offset, total = paginate_features(
            streets.collection["features"],
            limit=limit,
            offset=offset,
        )
    else:
        features_source = [
            streets.by_segment_id[sid] for sid in segment_id_list if sid in streets.by_segment_id
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
