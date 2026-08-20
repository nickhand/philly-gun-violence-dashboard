#!/usr/bin/env python3
"""Audit the deployed, read-only crawler-discovery contracts."""

from __future__ import annotations

import argparse
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime
from html.parser import HTMLParser
from typing import NamedTuple
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

AI_SEARCH_CRAWLERS = (
    ("OAI-SearchBot", "OAI-SearchBot/1.0; +https://openai.com/searchbot"),
    ("Claude-SearchBot", "Claude-SearchBot/1.0"),
    ("PerplexityBot", "PerplexityBot/1.0; +https://perplexity.ai/perplexitybot"),
)
CANONICAL_PATHS = ("", "/stats", "/data", "/methodology", "/about")
MONITOR_USER_AGENT = (
    "philly-dashboard-crawler-discovery-smoke/1.0 "
    "(+https://github.com/nickhand/philly-gun-violence-dashboard)"
)
REQUEST_ATTEMPTS = 3
REQUEST_TIMEOUT_SECONDS = 15
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
RETRYABLE_HTTP_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class CrawlDiscoveryError(RuntimeError):
    """A deployed crawler-discovery contract is unavailable or invalid."""


class HttpResponse(NamedTuple):
    """The bounded portion of an HTTP response required by this audit."""

    final_url: str
    headers: tuple[tuple[str, str], ...]
    body: bytes


def _require(condition: object, message: str) -> None:
    if not condition:
        raise CrawlDiscoveryError(message)


def _absolute_https_url(value: str, *, label: str, origin_only: bool = False) -> str:
    normalized = value.rstrip("/")
    parsed = urlsplit(normalized)
    _require(parsed.scheme == "https", f"{label} must use HTTPS")
    _require(bool(parsed.hostname), f"{label} must include a hostname")
    _require(
        parsed.username is None and parsed.password is None,
        f"{label} cannot include userinfo",
    )
    _require(not parsed.query and not parsed.fragment, f"{label} cannot include query or fragment")
    if origin_only:
        _require(parsed.path in {"", "/"}, f"{label} must be an origin without a path")
    return normalized


def _header_values(headers: tuple[tuple[str, str], ...], name: str) -> tuple[str, ...]:
    target = name.casefold()
    return tuple(value for key, value in headers if key.casefold() == target)


def _content_type(headers: tuple[tuple[str, str], ...]) -> str:
    values = _header_values(headers, "content-type")
    _require(len(values) == 1, "response must include exactly one Content-Type header")
    return values[0].partition(";")[0].strip().casefold()


def _require_no_noindex(headers: tuple[tuple[str, str], ...], *, label: str) -> None:
    for value in _header_values(headers, "x-robots-tag"):
        _require(
            re.search(r"(?:^|[^a-z])noindex(?:[^a-z]|$)", value, flags=re.IGNORECASE) is None,
            f"{label} response has an X-Robots-Tag noindex directive",
        )


def _decode(response: HttpResponse, *, label: str) -> str:
    try:
        return response.body.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CrawlDiscoveryError(f"{label} response is not valid UTF-8") from exc


def _fetch(url: str, *, user_agent: str) -> HttpResponse:
    """Issue a bounded GET, retrying only transient transport and HTTP failures."""
    request = Request(
        url,
        headers={
            "Accept": "*/*",
            "User-Agent": user_agent,
        },
        method="GET",
    )
    last_error: BaseException | None = None
    for attempt in range(REQUEST_ATTEMPTS):
        try:
            with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310
                _require(response.status == 200, f"GET {url} returned HTTP {response.status}")
                final_url = response.geturl()
                _require(final_url == url, f"GET {url} redirected to {final_url}")
                body = response.read(MAX_RESPONSE_BYTES + 1)
                _require(
                    len(body) <= MAX_RESPONSE_BYTES,
                    f"GET {url} exceeded the {MAX_RESPONSE_BYTES}-byte response limit",
                )
                headers = tuple((key, value) for key, value in response.headers.items())
                return HttpResponse(final_url=final_url, headers=headers, body=body)
        except HTTPError as exc:
            if exc.code not in RETRYABLE_HTTP_STATUS:
                raise CrawlDiscoveryError(f"GET {url} returned HTTP {exc.code}") from exc
            last_error = exc
        except OSError as exc:
            last_error = exc
        if attempt + 1 < REQUEST_ATTEMPTS:
            time.sleep(2**attempt)
    error_name = type(last_error).__name__ if last_error is not None else "unknown error"
    raise CrawlDiscoveryError(
        f"GET {url} failed after {REQUEST_ATTEMPTS} attempts ({error_name})"
    ) from last_error


def _validate_robots(text: str, *, sitemap_url: str, probe_path: str) -> None:
    """Require the authoritative policy to advertise and allow the app."""
    lines = text.splitlines()
    directives = []
    for raw_line in lines:
        line = raw_line.split("#", maxsplit=1)[0].strip()
        key, separator, value = line.partition(":")
        if separator:
            directives.append((key.strip().casefold(), value.strip()))

    _require(
        any(key == "user-agent" for key, _value in directives),
        "robots.txt has no User-agent directive",
    )
    advertised_sitemaps = tuple(value for key, value in directives if key == "sitemap")
    _require(
        sitemap_url in advertised_sitemaps,
        "host-root robots.txt does not advertise the canonical app sitemap",
    )

    parser = RobotFileParser()
    parser.parse(lines)
    for crawler_name, user_agent in AI_SEARCH_CRAWLERS:
        _require(
            parser.can_fetch(user_agent, probe_path),
            f"host-root robots.txt disallows {crawler_name} from {probe_path}",
        )


def _parse_lastmod(value: str) -> None:
    try:
        if len(value) == 10:
            date.fromisoformat(value)
        else:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CrawlDiscoveryError(f"sitemap has an invalid lastmod value: {value}") from exc


def _local_name(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1]


def _validate_sitemap(text: str, *, app_base_url: str) -> None:
    """Require the canonical content set and reject off-site or malformed URLs."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise CrawlDiscoveryError("sitemap.xml is not well-formed XML") from exc
    _require(_local_name(root.tag) == "urlset", "sitemap root must be urlset")

    locations: list[str] = []
    for entry in root:
        _require(_local_name(entry.tag) == "url", "sitemap urlset contains a non-url entry")
        loc_values = [
            (child.text or "").strip() for child in entry if _local_name(child.tag) == "loc"
        ]
        _require(len(loc_values) == 1 and bool(loc_values[0]), "sitemap entry needs one loc")
        location = loc_values[0]
        parsed = urlsplit(location)
        _require(parsed.scheme == "https", f"sitemap URL is not HTTPS: {location}")
        _require(
            not parsed.query and not parsed.fragment,
            f"sitemap URL is not canonical: {location}",
        )
        _require(
            location == app_base_url or location.startswith(f"{app_base_url}/"),
            f"sitemap URL is outside the canonical app base: {location}",
        )
        locations.append(location)
        for child in entry:
            if _local_name(child.tag) == "lastmod":
                value = (child.text or "").strip()
                _require(bool(value), f"sitemap lastmod is empty for {location}")
                _parse_lastmod(value)

    _require(len(locations) == len(set(locations)), "sitemap contains duplicate URLs")
    required = {f"{app_base_url}{path}" for path in CANONICAL_PATHS}
    missing = sorted(required - set(locations))
    _require(not missing, f"sitemap is missing canonical pages: {', '.join(missing)}")
    unexpected = sorted(set(locations) - required)
    _require(
        not unexpected,
        f"sitemap contains unexpected pages: {', '.join(unexpected)}",
    )


def _validate_llms(text: str, *, app_base_url: str) -> None:
    """Require a readable guide that links every canonical content page."""
    _require(text.startswith("# "), "llms.txt must start with a Markdown H1")
    _require("<html" not in text.casefold(), "llms.txt unexpectedly contains HTML")
    links = {match.group(1) for match in re.finditer(r"\[[^\]\n]+\]\((https://[^)\s]+)\)", text)}
    required = {f"{app_base_url}{path}" for path in CANONICAL_PATHS}
    missing = sorted(required - links)
    _require(not missing, f"llms.txt is missing canonical page links: {', '.join(missing)}")


class _DiscoveryHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.has_html = False
        self.has_main = False
        self.canonicals: list[str] = []
        self.describedby: list[str] = []
        self.noindex_meta: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.casefold(): value or "" for key, value in attrs}
        if tag == "html":
            self.has_html = True
        elif tag == "main":
            self.has_main = True
        elif tag == "link":
            rel = {item.casefold() for item in attributes.get("rel", "").split()}
            if "canonical" in rel:
                self.canonicals.append(attributes.get("href", ""))
            if "describedby" in rel:
                self.describedby.append(attributes.get("href", ""))
        elif tag == "meta":
            name = attributes.get("name", "").casefold()
            content = attributes.get("content", "")
            if name and re.search(r"(?:^|[^a-z])noindex(?:[^a-z]|$)", content, flags=re.IGNORECASE):
                self.noindex_meta.append(name)


def _validate_html(
    text: str,
    *,
    headers: tuple[tuple[str, str], ...],
    page_url: str,
    llms_url: str,
) -> None:
    """Require ordinary canonical SSR HTML with no indexing exclusion."""
    _require(_content_type(headers) == "text/html", f"{page_url} is not served as HTML")
    _require_no_noindex(headers, label=page_url)
    parser = _DiscoveryHTMLParser()
    parser.feed(text)
    _require(parser.has_html and parser.has_main, f"{page_url} lacks an HTML main document")
    _require(parser.canonicals == [page_url], f"{page_url} has an incorrect canonical link")
    _require(llms_url in parser.describedby, f"{page_url} does not describe itself with llms.txt")
    _require(not parser.noindex_meta, f"{page_url} has a noindex meta directive")


def audit(site_origin: str, app_base_url: str) -> dict[str, object]:
    """Fetch and validate all crawler-discovery resources with read-only GETs."""
    origin = _absolute_https_url(site_origin, label="site origin", origin_only=True)
    app_base = _absolute_https_url(app_base_url, label="app base URL")
    _require(
        urlsplit(origin).netloc == urlsplit(app_base).netloc,
        "site origin and app base URL must use the same authority",
    )

    robots_url = f"{origin}/robots.txt"
    sitemap_url = f"{app_base}/sitemap.xml"
    llms_url = f"{app_base}/llms.txt"
    page_url = f"{app_base}/stats"
    probe_path = urlsplit(page_url).path

    robots = _fetch(robots_url, user_agent=MONITOR_USER_AGENT)
    _require(_content_type(robots.headers) == "text/plain", "robots.txt is not text/plain")
    _validate_robots(
        _decode(robots, label="robots.txt"),
        sitemap_url=sitemap_url,
        probe_path=probe_path,
    )

    sitemap = _fetch(sitemap_url, user_agent=MONITOR_USER_AGENT)
    _require(
        _content_type(sitemap.headers) in {"application/xml", "text/xml"},
        "sitemap.xml is not served with an XML Content-Type",
    )
    _require_no_noindex(sitemap.headers, label="sitemap.xml")
    _validate_sitemap(_decode(sitemap, label="sitemap.xml"), app_base_url=app_base)

    llms = _fetch(llms_url, user_agent=MONITOR_USER_AGENT)
    _require(_content_type(llms.headers) == "text/plain", "llms.txt is not text/plain")
    _require_no_noindex(llms.headers, label="llms.txt")
    _validate_llms(_decode(llms, label="llms.txt"), app_base_url=app_base)

    checked_crawlers = []
    for crawler_name, user_agent in AI_SEARCH_CRAWLERS:
        page = _fetch(page_url, user_agent=user_agent)
        _validate_html(
            _decode(page, label=f"{crawler_name} HTML"),
            headers=page.headers,
            page_url=page_url,
            llms_url=llms_url,
        )
        checked_crawlers.append(crawler_name)

    return {
        "canonical_pages_in_sitemap": len(CANONICAL_PATHS),
        "crawler_user_agents_checked": checked_crawlers,
        "llms_url": llms_url,
        "robots_url": robots_url,
        "sitemap_url": sitemap_url,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-origin", required=True)
    parser.add_argument("--app-base-url", required=True)
    args = parser.parse_args()
    try:
        result = audit(args.site_origin, args.app_base_url)
    except CrawlDiscoveryError as exc:
        parser.exit(1, f"crawler-discovery check failed: {exc}\n")
    for key, value in result.items():
        print(f"{key}: {value}")
    print(
        "User-Agent probes verify deployed HTTP behavior only; actual vendor-IP access "
        "and indexing require provider logs or independent visibility monitoring."
    )


if __name__ == "__main__":
    main()
