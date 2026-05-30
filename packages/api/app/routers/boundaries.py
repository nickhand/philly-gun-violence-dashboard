"""Boundary GeoJSON endpoints."""

from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Request

from app.data_loader import make_refresh_dependency
from dashboard_utils.models.boundaries import BoundaryFeatureCollection

router = APIRouter(dependencies=[Depends(make_refresh_dependency(["boundaries_manifest"]))])


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
    boundaries = request.app.state.boundaries
    if dataset not in boundaries:
        raise HTTPException(status_code=404, detail="Boundary dataset not found.")
    return cast(BoundaryFeatureCollection, boundaries[dataset])
