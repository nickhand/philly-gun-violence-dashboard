"""Data freshness metadata endpoints."""

from typing import Any, cast

from fastapi import APIRouter, Depends, Request

from app.data_loader import (
    get_data_snapshot,
    make_refresh_dependency,
    require_homicides,
    require_shootings,
)
from dashboard_utils.processed import read_processed_json

router = APIRouter(
    prefix="/meta",
    tags=["meta"],
    dependencies=[Depends(make_refresh_dependency(["shootings", "homicides"]))],
)


@router.get("")
def get_all_meta(request: Request) -> dict[str, Any]:
    """Return metadata for all datasets.

    Returns
    -------
    dict[str, Any]
        Metadata including last_updated and data_through for each dataset.
    """
    snapshot = get_data_snapshot(request.app)
    return {
        "shootings": require_shootings(snapshot).freshness,
        "homicides": require_homicides(snapshot).freshness,
        "courts": read_processed_json("courts_meta", s3=request.app.state.s3),
    }


@router.get("/shootings")
def get_shootings_meta(request: Request) -> dict[str, Any]:
    """Return metadata for shootings dataset.

    Returns
    -------
    dict[str, Any]
        Metadata including last_updated and data_through.
    """
    return require_shootings(get_data_snapshot(request.app)).freshness


@router.get("/homicides")
def get_homicides_meta(request: Request) -> dict[str, Any]:
    """Return metadata for homicides dataset.

    Returns
    -------
    dict[str, Any]
        Metadata including last_updated and data_through.
    """
    return require_homicides(get_data_snapshot(request.app)).freshness


@router.get("/courts")
def get_courts_meta(request: Request) -> dict[str, Any]:
    """Return metadata for courts dataset.

    Returns
    -------
    dict[str, Any]
        Metadata including last_updated and data_through.
    """
    s3 = request.app.state.s3
    return cast(dict[str, Any], read_processed_json("courts_meta", s3=s3))
