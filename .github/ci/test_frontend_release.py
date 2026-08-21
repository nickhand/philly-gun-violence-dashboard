"""Tests for the exact-build frontend production smoke."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch


def _load_checker() -> ModuleType:
    path = Path(__file__).with_name("check_frontend_release.py")
    spec = importlib.util.spec_from_file_location("frontend_release_checker", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load frontend release checker")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CHECKER = _load_checker()
BASE = "https://www.nickhand.dev/philly-gun-violence-map"
BUILD_ID = "build-123"
HEADERS = {
    "content-security-policy": "frame-ancestors 'none'",
    "strict-transport-security": "max-age=31536000",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
}
HTML = b"""<!doctype html><html><head><title>Dashboard</title>
<link rel="stylesheet" href="/philly-gun-violence-map/_nuxt/app.abc.css">
</head><body><main>Dashboard</main></body></html>"""


def _response(url: str, *, body: bytes = HTML, headers: dict[str, str] | None = None):
    return CHECKER.Fetched(url=url, headers=headers or HEADERS, body=body)


def _fetch(url: str):
    if "/_nuxt/builds/latest.json" in url:
        return _response(url, body=b'{"id":"build-123"}', headers={})
    if "/_nuxt/" in url:
        return _response(url, body=b"body{}", headers={"content-type": "text/css"})
    return _response(url.split("?", maxsplit=1)[0])


class FrontendReleaseCheckerTests(unittest.TestCase):
    def test_accepts_exact_build_pages_headers_and_asset(self) -> None:
        with patch.object(CHECKER, "_fetch", side_effect=_fetch):
            asset = CHECKER.check_frontend_release(
                app_base_url=BASE,
                expected_build_id=BUILD_ID,
                attempts=1,
                retry_delay=0,
            )

        self.assertEqual(
            asset,
            "https://www.nickhand.dev/philly-gun-violence-map/_nuxt/app.abc.css",
        )

    def test_rejects_a_stale_live_build(self) -> None:
        def stale(url: str):
            if "/_nuxt/builds/latest.json" in url:
                return _response(url, body=b'{"id":"older"}', headers={})
            return _fetch(url)

        with patch.object(CHECKER, "_fetch", side_effect=stale):
            with self.assertRaisesRegex(RuntimeError, "live build ID is 'older'"):
                CHECKER.check_frontend_release(
                    app_base_url=BASE,
                    expected_build_id=BUILD_ID,
                    attempts=1,
                    retry_delay=0,
                )

    def test_rejects_noindex_or_missing_security_headers(self) -> None:
        noindex = HTML.replace(b"</head>", b'<meta name="robots" content="noindex"></head>')

        def bad_page(url: str):
            if url == f"{BASE}/stats":
                return _response(url, body=noindex)
            return _fetch(url)

        with patch.object(CHECKER, "_fetch", side_effect=bad_page):
            with self.assertRaisesRegex(RuntimeError, "noindex metadata: /stats"):
                CHECKER.check_frontend_release(
                    app_base_url=BASE,
                    expected_build_id=BUILD_ID,
                    attempts=1,
                    retry_delay=0,
                )

        def missing_header(url: str):
            if url == f"{BASE}/about":
                headers = dict(HEADERS)
                headers.pop("x-frame-options")
                return _response(url, headers=headers)
            return _fetch(url)

        with patch.object(CHECKER, "_fetch", side_effect=missing_header):
            with self.assertRaisesRegex(RuntimeError, "invalid x-frame-options: /about"):
                CHECKER.check_frontend_release(
                    app_base_url=BASE,
                    expected_build_id=BUILD_ID,
                    attempts=1,
                    retry_delay=0,
                )

    def test_rejects_an_asset_outside_the_application_path(self) -> None:
        escaped = HTML.replace(
            b"/philly-gun-violence-map/_nuxt/app.abc.css",
            b"https://cdn.example.com/_nuxt/app.abc.css",
        )

        def escaped_page(url: str):
            if url == f"{BASE}/":
                return _response(url, body=escaped)
            return _fetch(url)

        with patch.object(CHECKER, "_fetch", side_effect=escaped_page):
            with self.assertRaisesRegex(RuntimeError, "escaped the canonical application path"):
                CHECKER.check_frontend_release(
                    app_base_url=BASE,
                    expected_build_id=BUILD_ID,
                    attempts=1,
                    retry_delay=0,
                )


if __name__ == "__main__":
    unittest.main()
