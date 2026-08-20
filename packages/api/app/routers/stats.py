"""Statistics JSON and legacy crawler-compatibility endpoints."""

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from app.data_loader import make_refresh_dependency
from app.stats_page import CANONICAL_BASE, StatsSnapshot, get_stats_page_cache

router = APIRouter(tags=["statistics"])
refresh_datasets = Depends(make_refresh_dependency(["shootings", "homicides"]))

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
        "X-Robots-Tag": "noindex, follow",
    }


@router.get(
    "/stats",
    response_class=HTMLResponse,
    response_model=None,
    dependencies=[refresh_datasets],
    include_in_schema=False,
)
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


@router.get(
    "/stats.json",
    response_model=StatsSnapshot,
    dependencies=[refresh_datasets],
)
def get_stats_json(
    request: Request,
    response: Response,
    if_none_match: str | None = Header(None),
) -> StatsSnapshot | Response:
    """Return the statistics snapshot used to render the HTML statistics page."""
    cached = get_stats_page_cache(request.app)
    etag = f"{cached.etag}-json"
    headers = _headers(etag)
    headers["X-Robots-Tag"] = "noindex"
    if _not_modified(if_none_match, etag):
        return Response(status_code=304, headers=headers)
    response.headers.update(headers)
    return cached.snapshot


@router.get("/sitemap.xml", response_model=None, include_in_schema=False)
def get_sitemap() -> RedirectResponse:
    """Redirect legacy crawlers to the canonical Nuxt sitemap."""
    return RedirectResponse(
        f"{CANONICAL_BASE}/sitemap.xml",
        status_code=308,
        headers={"Cache-Control": "public, max-age=3600"},
    )
