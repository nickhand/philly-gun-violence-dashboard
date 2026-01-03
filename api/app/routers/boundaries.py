"""Boundary GeoJSON endpoints."""

from typing import cast

from fastapi import APIRouter, HTTPException, Request

from app.data_loader import refresh_if_stale
from dashboard_utils.models.boundaries import BoundaryFeatureCollection

router = APIRouter()


@router.get("/boundaries")
def list_boundaries(request: Request) -> dict[str, list[str]]:
    """List available boundary datasets.

    Parameters
    ----------
    request : fastapi.Request
        The current request with access to application state.

    Returns
    -------
    dict[str, list[str]]
        The list of dataset names under the "datasets" key.
    """
    refresh_if_stale(request.app, ["boundaries_manifest"])
    return {"datasets": sorted(request.app.state.boundaries)}


@router.get("/boundaries/{dataset}")
def get_boundary(
    dataset: str,
    request: Request,
) -> BoundaryFeatureCollection:
    """Return a boundary dataset by name.

    Parameters
    ----------
    dataset : str
        The dataset name.
    request : fastapi.Request
        The current request with access to application state.

    Returns
    -------
    BoundaryFeatureCollection
        The GeoJSON FeatureCollection for the boundary dataset.
    """
    refresh_if_stale(request.app, ["boundaries_manifest"])
    boundaries = request.app.state.boundaries
    if dataset not in boundaries:
        raise HTTPException(status_code=404, detail="Boundary dataset not found.")
    return cast(BoundaryFeatureCollection, boundaries[dataset])
