"""Process liveness and loaded-dataset readiness endpoints."""

from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.data_loader import (
    get_data_snapshot,
    refresh_if_stale,
    require_boundaries,
    require_homicides,
    require_shootings,
    require_streets,
)

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Return process liveness without making an upstream S3 request.

    Returns
    -------
    dict[str, str]
        The status payload.
    """
    return {"status": "ok"}


def _data_date(metadata: dict[str, Any], dataset: str) -> date:
    value = metadata.get("data_through")
    if not isinstance(value, str):
        raise ValueError(f"{dataset} metadata has no data_through date")
    return date.fromisoformat(value)


@router.get(
    "/ready",
    responses={503: {"description": "Datasets are unavailable or older than the threshold."}},
)
def readiness(request: Request) -> JSONResponse:
    """Refresh core pointers and report snapshot freshness and upstream health."""
    today = datetime.now(UTC).date()
    try:
        refresh_if_stale(
            request.app,
            ["shootings", "homicides", "boundaries_manifest", "streets"],
        )
        snapshot = get_data_snapshot(request.app)
        shootings = require_shootings(snapshot)
        homicides = require_homicides(snapshot)
        boundaries = require_boundaries(snapshot)
        streets = require_streets(snapshot)
        dataset_values = {
            "shootings": (shootings.freshness, shootings.source_kind),
            "homicides": (homicides.freshness, homicides.source_kind),
        }
        datasets = {}
        stale = False
        for name, (metadata, source_kind) in dataset_values.items():
            data_through = _data_date(metadata, name)
            age_days = (today - data_through).days
            current = 0 <= age_days <= settings.api_readiness_max_data_age_days
            stale = stale or not current
            datasets[name] = {
                "data_through": data_through.isoformat(),
                "age_days": age_days,
                "source": source_kind,
                "current": current,
            }
        datasets["boundaries"] = {
            "source": boundaries.source_kind,
            "current": True,
        }
        datasets["streets"] = {
            "source": streets.source_token[0],
            "current": True,
        }
    except (RuntimeError, TypeError, ValueError) as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "detail": str(exc)},
        )

    status = "stale" if stale else "ready"
    refresh_failure_names = {
        "boundaries_manifest": "boundaries",
    }
    refresh_failures = sorted(
        refresh_failure_names.get(name, name) for name in request.app.state.dataset_last_failed
    )
    if refresh_failures:
        status = "degraded"
    return JSONResponse(
        status_code=503 if stale or refresh_failures else 200,
        content={
            "status": status,
            "max_data_age_days": settings.api_readiness_max_data_age_days,
            "datasets": datasets,
            "refresh_failures": refresh_failures,
        },
    )
