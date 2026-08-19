"""Homicide totals endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.data_loader import get_data_snapshot, make_refresh_dependency, require_homicides

router = APIRouter(dependencies=[Depends(make_refresh_dependency(["homicides"]))])


class HomicideTotalsResponse(BaseModel):
    """Annual and YTD homicide totals for a given year."""

    year: int = Field(
        title="Year",
        description="Calendar year of the totals.",
    )
    annual: float | None = Field(
        title="Annual total",
        description="Annual total homicide count for the year.",
    )
    ytd: int | float = Field(
        title="Year-to-date total",
        description="Year-to-date homicide count for the year.",
    )


@router.get("/homicides/{year}")
def get_homicide_totals(year: int, request: Request) -> HomicideTotalsResponse:
    """Return homicide totals for the requested year.

    Parameters
    ----------
    year : int
        Calendar year to fetch totals for.
    request : fastapi.Request
        The current request with access to application state.

    Returns
    -------
    HomicideTotalsResponse
        The annual and year-to-date totals for the requested year.
    """
    totals = require_homicides(get_data_snapshot(request.app)).totals
    record = totals.get(str(year))
    if record is None:
        raise HTTPException(status_code=404, detail=f"Homicide totals not found for year {year}.")
    return HomicideTotalsResponse(year=year, **record)
