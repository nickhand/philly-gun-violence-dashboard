"""Tests for fail-closed crawler-discovery parsing."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from types import ModuleType

MODULE_PATH = Path(__file__).with_name("check_crawler_discovery.py")


def _load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("crawler_discovery_checker", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load crawler-discovery checker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECKER = _load_checker()
APP_BASE_URL = "https://www.example.test/dashboard"
SITEMAP_URL = f"{APP_BASE_URL}/sitemap.xml"
LLMS_URL = f"{APP_BASE_URL}/llms.txt"
PAGE_URL = f"{APP_BASE_URL}/stats"


def _valid_robots() -> str:
    return f"User-agent: *\nAllow: /\n\nSitemap: {SITEMAP_URL}\n"


def _valid_sitemap() -> str:
    entries = "".join(
        f"<url><loc>{APP_BASE_URL}{path}</loc><lastmod>2026-08-20</lastmod></url>"
        for path in CHECKER.CANONICAL_PATHS
    )
    return f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</urlset>'


def _valid_llms() -> str:
    links = "\n".join(f"- [Page]({APP_BASE_URL}{path})" for path in CHECKER.CANONICAL_PATHS)
    return f"# Dashboard\n\n{links}\n"


def _valid_html() -> str:
    return (
        "<!doctype html><html><head>"
        f'<link rel="canonical" href="{PAGE_URL}">'
        f'<link rel="describedby" href="{LLMS_URL}">'
        '<meta name="robots" content="index, follow">'
        "</head><body><main>Statistics</main></body></html>"
    )


class CrawlerDiscoveryParsing(unittest.TestCase):
    def test_valid_discovery_documents_pass(self) -> None:
        CHECKER._validate_robots(
            _valid_robots(),
            sitemap_url=SITEMAP_URL,
            probe_path="/dashboard/stats",
        )
        CHECKER._validate_sitemap(_valid_sitemap(), app_base_url=APP_BASE_URL)
        CHECKER._validate_llms(_valid_llms(), app_base_url=APP_BASE_URL)
        CHECKER._validate_html(
            _valid_html(),
            headers=(("Content-Type", "text/html; charset=utf-8"),),
            page_url=PAGE_URL,
            llms_url=LLMS_URL,
        )

    def test_robots_must_advertise_the_sitemap_and_allow_each_crawler(self) -> None:
        without_sitemap = "User-agent: *\nAllow: /\n"
        with self.assertRaisesRegex(CHECKER.CrawlDiscoveryError, "does not advertise"):
            CHECKER._validate_robots(
                without_sitemap,
                sitemap_url=SITEMAP_URL,
                probe_path="/dashboard/stats",
            )

        blocked = _valid_robots() + "\nUser-agent: OAI-SearchBot\nDisallow: /dashboard/\n"
        with self.assertRaisesRegex(CHECKER.CrawlDiscoveryError, "disallows OAI-SearchBot"):
            CHECKER._validate_robots(
                blocked,
                sitemap_url=SITEMAP_URL,
                probe_path="/dashboard/stats",
            )

    def test_sitemap_requires_every_canonical_page_and_valid_lastmod(self) -> None:
        CHECKER._validate_sitemap(_valid_sitemap(), app_base_url=APP_BASE_URL)

        missing_about = _valid_sitemap().replace(
            f"<url><loc>{APP_BASE_URL}/about</loc><lastmod>2026-08-20</lastmod></url>",
            "",
        )
        with self.assertRaisesRegex(CHECKER.CrawlDiscoveryError, "missing canonical pages"):
            CHECKER._validate_sitemap(missing_about, app_base_url=APP_BASE_URL)

        invalid_date = _valid_sitemap().replace("2026-08-20", "not-a-date", 1)
        with self.assertRaisesRegex(CHECKER.CrawlDiscoveryError, "invalid lastmod"):
            CHECKER._validate_sitemap(invalid_date, app_base_url=APP_BASE_URL)

        sibling_prefix = _valid_sitemap().replace(
            f"<loc>{APP_BASE_URL}</loc>",
            f"<loc>{APP_BASE_URL}-other</loc>",
        )
        with self.assertRaisesRegex(CHECKER.CrawlDiscoveryError, "outside the canonical app base"):
            CHECKER._validate_sitemap(sibling_prefix, app_base_url=APP_BASE_URL)

        extra = _valid_sitemap().replace(
            "</urlset>",
            f"<url><loc>{APP_BASE_URL}/extra</loc></url></urlset>",
        )
        with self.assertRaisesRegex(CHECKER.CrawlDiscoveryError, "unexpected pages"):
            CHECKER._validate_sitemap(extra, app_base_url=APP_BASE_URL)

    def test_llms_requires_markdown_links_to_every_canonical_page(self) -> None:
        missing_stats = _valid_llms().replace(f"- [Page]({PAGE_URL})\n", "")
        with self.assertRaisesRegex(CHECKER.CrawlDiscoveryError, "missing canonical page links"):
            CHECKER._validate_llms(missing_stats, app_base_url=APP_BASE_URL)

        slash_only_root = _valid_llms().replace(
            f"- [Page]({APP_BASE_URL})\n",
            f"- [Page]({APP_BASE_URL}/)\n",
        )
        with self.assertRaisesRegex(CHECKER.CrawlDiscoveryError, "missing canonical page links"):
            CHECKER._validate_llms(slash_only_root, app_base_url=APP_BASE_URL)

    def test_html_rejects_header_and_meta_noindex(self) -> None:
        with self.assertRaisesRegex(CHECKER.CrawlDiscoveryError, "X-Robots-Tag noindex"):
            CHECKER._validate_html(
                _valid_html(),
                headers=(
                    ("Content-Type", "text/html"),
                    ("X-Robots-Tag", "OAI-SearchBot: noindex"),
                ),
                page_url=PAGE_URL,
                llms_url=LLMS_URL,
            )

        noindex_html = _valid_html().replace("index, follow", "noindex nofollow")
        with self.assertRaisesRegex(CHECKER.CrawlDiscoveryError, "noindex meta"):
            CHECKER._validate_html(
                noindex_html,
                headers=(("Content-Type", "text/html"),),
                page_url=PAGE_URL,
                llms_url=LLMS_URL,
            )

    def test_html_requires_the_canonical_and_llms_relationships(self) -> None:
        wrong_canonical = _valid_html().replace(PAGE_URL, f"{APP_BASE_URL}/", 1)
        with self.assertRaisesRegex(CHECKER.CrawlDiscoveryError, "incorrect canonical"):
            CHECKER._validate_html(
                wrong_canonical,
                headers=(("Content-Type", "text/html"),),
                page_url=PAGE_URL,
                llms_url=LLMS_URL,
            )

        without_llms = _valid_html().replace(
            f'<link rel="describedby" href="{LLMS_URL}">',
            "",
        )
        with self.assertRaisesRegex(CHECKER.CrawlDiscoveryError, "llms.txt"):
            CHECKER._validate_html(
                without_llms,
                headers=(("Content-Type", "text/html"),),
                page_url=PAGE_URL,
                llms_url=LLMS_URL,
            )


if __name__ == "__main__":
    unittest.main()
