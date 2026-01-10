"""Data freshness metadata endpoints."""

from typing import Any

from fastapi import APIRouter, Request

from dashboard_utils.processed import read_processed_json

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("")
def get_all_meta(request: Request) -> dict[str, Any]:
    """Return metadata for all datasets.

    Returns
    -------
    dict[str, Any]
        Metadata including last_updated and data_through for each dataset.
    """
    s3 = request.app.state.s3
    return {
        "shootings": read_processed_json("shootings_meta", s3=s3),
        "homicides": read_processed_json("homicides_meta", s3=s3),
        "courts": read_processed_json("courts_meta", s3=s3),
    }


@router.get("/shootings")
def get_shootings_meta(request: Request) -> dict[str, Any]:
    """Return metadata for shootings dataset.

    Returns
    -------
    dict[str, Any]
        Metadata including last_updated and data_through.
    """
    s3 = request.app.state.s3
    return read_processed_json("shootings_meta", s3=s3)


@router.get("/homicides")
def get_homicides_meta(request: Request) -> dict[str, Any]:
    """Return metadata for homicides dataset.

    Returns
    -------
    dict[str, Any]
        Metadata including last_updated and data_through.
    """
    s3 = request.app.state.s3
    return read_processed_json("homicides_meta", s3=s3)


@router.get("/courts")
def get_courts_meta(request: Request) -> dict[str, Any]:
    """Return metadata for courts dataset.

    Returns
    -------
    dict[str, Any]
        Metadata including last_updated and data_through.
    """
    s3 = request.app.state.s3
    return read_processed_json("courts_meta", s3=s3)
