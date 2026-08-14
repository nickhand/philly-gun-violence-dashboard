"""Crawler-visible HTML and XML endpoints backed by loaded dashboard data."""

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import HTMLResponse

from app.data_loader import make_refresh_dependency
from app.stats_page import get_stats_page_cache

router = APIRouter(
    tags=["statistics"],
    dependencies=[Depends(make_refresh_dependency(["shootings", "homicides"]))],
)

CACHE_CONTROL = "public, max-age=0, must-revalidate"


def _not_modified(if_none_match: str | None, etag: str) -> bool:
    if not if_none_match:
        return False
    candidates = {value.strip().removeprefix("W/").strip('"') for value in if_none_match.split(",")}
    return etag in candidates or "*" in candidates


def _headers(etag: str) -> dict[str, str]:
    return {
        "Cache-Control": CACHE_CONTROL,
        "ETag": f'"{etag}"',
        "X-Robots-Tag": "index, follow",
    }


@router.get("/stats", response_class=HTMLResponse, response_model=None)
def get_stats_page(
    request: Request,
    if_none_match: str | None = Header(None),
) -> Response:
    """Return the current, server-rendered statistics and FAQ page."""
    cached = get_stats_page_cache(request.app)
    headers = _headers(cached.etag)
    if _not_modified(if_none_match, cached.etag):
        return Response(status_code=304, headers=headers)
    return HTMLResponse(cached.html, headers=headers)


@router.get("/sitemap.xml", response_model=None)
def get_sitemap(
    request: Request,
    if_none_match: str | None = Header(None),
) -> Response:
    """Return a sitemap whose modification dates track the loaded data."""
    cached = get_stats_page_cache(request.app)
    etag = f"{cached.etag}-sitemap"
    headers = _headers(etag)
    if _not_modified(if_none_match, etag):
        return Response(status_code=304, headers=headers)
    return Response(cached.sitemap, media_type="application/xml", headers=headers)
