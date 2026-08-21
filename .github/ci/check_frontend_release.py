#!/usr/bin/env python3
"""Verify that one exact Nuxt build is live on the canonical Worker route."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import Request, urlopen

MAX_RESPONSE_BYTES = 5 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 10
PAGE_PATHS = ("/", "/stats", "/data", "/methodology", "/about")
REQUIRED_HEADERS = {
    "content-security-policy": re.compile(r"frame-ancestors\s+'none'", re.I),
    "strict-transport-security": re.compile(r"(?:^|\s)max-age=31536000(?:[;\s]|$)", re.I),
    "x-content-type-options": re.compile(r"^nosniff$", re.I),
    "x-frame-options": re.compile(r"^DENY$", re.I),
}
ASSET_PATTERN = re.compile(
    r"(?:src|href)=[\"']([^\"']*/_nuxt/[^\"']+\.(?:css|js))(?:\?[^\"']*)?[\"']",
    re.I,
)


@dataclass(frozen=True)
class Fetched:
    """Bounded HTTP response used by the release checker."""

    url: str
    headers: dict[str, str]
    body: bytes


def _fetch(url: str) -> Fetched:
    request = Request(  # noqa: S310 - exact operator-controlled HTTPS origin
        url,
        headers={
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
            "Cache-Control": "no-cache",
            "User-Agent": "philly-gun-violence-dashboard-release-check/1",
        },
    )
    with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310
        content_length = response.headers.get("Content-Length")
        if content_length is not None and int(content_length) > MAX_RESPONSE_BYTES:
            raise RuntimeError(f"response is too large: {url}")
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise RuntimeError(f"response is too large: {url}")
        return Fetched(
            url=response.geturl(),
            headers={key.lower(): value.strip() for key, value in response.headers.items()},
            body=body,
        )


def _require_page(response: Fetched, *, app_base_url: str, path: str) -> str:
    if not response.url.startswith(f"{app_base_url}/") and response.url != app_base_url:
        raise RuntimeError(f"page escaped the canonical application origin: {path}")
    html = response.body.decode("utf-8", errors="strict")
    if not re.search(r"<!doctype html|<html(?:\s|>)", html, re.I):
        raise RuntimeError(f"page is not HTML: {path}")
    if not re.search(r"<title>[^<]+", html, re.I):
        raise RuntimeError(f"page has no title: {path}")
    if not re.search(r"<main(?:\s|>)", html, re.I):
        raise RuntimeError(f"page has no main landmark: {path}")
    if re.search(r"<meta[^>]+name=[\"']robots[\"'][^>]+noindex", html, re.I):
        raise RuntimeError(f"production page contains noindex metadata: {path}")
    if "noindex" in response.headers.get("x-robots-tag", "").lower():
        raise RuntimeError(f"production response contains noindex: {path}")
    for name, pattern in REQUIRED_HEADERS.items():
        value = response.headers.get(name, "")
        if pattern.search(value) is None:
            raise RuntimeError(f"production response has invalid {name}: {path}")
    return html


def check_frontend_release(
    *,
    app_base_url: str,
    expected_build_id: str,
    attempts: int = 12,
    retry_delay: float = 3,
) -> str:
    """Require the exact build ID, canonical pages, headers, and one hashed asset."""
    base = app_base_url.rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "https" or not parsed.hostname or parsed.query or parsed.fragment:
        raise ValueError("app base URL must be an HTTPS origin and path")
    if not expected_build_id.strip():
        raise ValueError("expected build ID must not be blank")
    if attempts < 1 or retry_delay < 0:
        raise ValueError("retry settings are invalid")

    latest_url = (
        f"{base}/_nuxt/builds/latest.json?deployment-audit="
        f"{quote(expected_build_id, safe='')}"
    )
    last_error = "build ID did not match"
    for attempt in range(attempts):
        try:
            latest = json.loads(_fetch(latest_url).body)
            if isinstance(latest, dict) and latest.get("id") == expected_build_id:
                break
            last_error = f"live build ID is {latest.get('id')!r}"
        except (HTTPError, URLError, TimeoutError, UnicodeError, json.JSONDecodeError) as exc:
            last_error = f"build ID request failed: {exc}"
        if attempt + 1 < attempts:
            time.sleep(retry_delay)
    else:
        raise RuntimeError(
            f"expected build {expected_build_id!r} was not live after {attempts} attempts: "
            f"{last_error}"
        )

    homepage_html = ""
    for path in PAGE_PATHS:
        page = _fetch(f"{base}{path}")
        html = _require_page(page, app_base_url=base, path=path)
        if path == "/":
            homepage_html = html

    asset_match = ASSET_PATTERN.search(homepage_html)
    if asset_match is None:
        raise RuntimeError("homepage does not reference a hashed Nuxt asset")
    asset_url = urljoin(f"{base}/", asset_match.group(1))
    asset = urlsplit(asset_url)
    base_parts = urlsplit(base)
    expected_asset_prefix = f"{base_parts.path}/_nuxt/"
    if (
        asset.scheme != base_parts.scheme
        or asset.netloc != base_parts.netloc
        or not asset.path.startswith(expected_asset_prefix)
    ):
        raise RuntimeError("homepage Nuxt asset escaped the canonical application path")
    asset_response = _fetch(asset_url)
    if not asset_response.body:
        raise RuntimeError("homepage Nuxt asset is empty")

    return asset_url


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-base-url", required=True)
    parser.add_argument("--expected-build-id", required=True)
    parser.add_argument("--attempts", type=int, default=12)
    parser.add_argument("--retry-delay", type=float, default=3)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        asset_url = check_frontend_release(
            app_base_url=args.app_base_url,
            expected_build_id=args.expected_build_id,
            attempts=args.attempts,
            retry_delay=args.retry_delay,
        )
    except (HTTPError, URLError, TimeoutError, UnicodeError, ValueError, RuntimeError) as exc:
        print(f"Frontend release smoke failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"Frontend release smoke passed: build_id={args.expected_build_id} "
        f"pages={len(PAGE_PATHS)} asset={asset_url}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
