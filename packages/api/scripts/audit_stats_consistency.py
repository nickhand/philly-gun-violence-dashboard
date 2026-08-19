"""Audit crawler-visible statistics against the API's machine-readable data."""

import argparse
import json
import re
from datetime import date
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


class AuditError(RuntimeError):
    """A public statistics contract did not match its source data."""


def _require(condition: object, message: str) -> None:
    """Raise an optimization-safe audit failure when a contract is false."""
    if not condition:
        raise AuditError(message)


class StatsParser(HTMLParser):
    """Extract the visible figures, year table, metadata, and JSON-LD."""

    def __init__(self) -> None:
        super().__init__()
        self.canonical: str | None = None
        self.description: str | None = None
        self.figures: list[str] = []
        self.table_rows: list[list[str]] = []
        self.json_ld: list[dict[str, Any]] = []
        self.visible_text: list[str] = []
        self._capture_figure = False
        self._figure_parts: list[str] = []
        self._in_tbody = False
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._in_json_ld = False
        self._json_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "link" and attributes.get("rel") == "canonical":
            self.canonical = attributes.get("href")
        if tag == "meta" and attributes.get("name") == "description":
            self.description = attributes.get("content")
        if tag == "div" and "figure" in classes:
            self._capture_figure = True
            self._figure_parts = []
        if tag == "tbody":
            self._in_tbody = True
        elif tag == "tr" and self._in_tbody:
            self._row = []
        elif tag == "td" and self._row is not None:
            self._cell = []
        if tag == "script" and attributes.get("type") == "application/ld+json":
            self._in_json_ld = True
            self._json_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self._capture_figure:
            value = " ".join(self._figure_parts).strip()
            if value:
                self.figures.append(value)
            self._capture_figure = False
        if tag == "td" and self._cell is not None and self._row is not None:
            self._row.append(" ".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.table_rows.append(self._row)
            self._row = None
        elif tag == "tbody":
            self._in_tbody = False
        if tag == "script" and self._in_json_ld:
            self.json_ld.append(json.loads("".join(self._json_parts)))
            self._in_json_ld = False

    def handle_data(self, data: str) -> None:
        normalized = " ".join(data.split())
        if normalized and not self._in_json_ld:
            self.visible_text.append(normalized)
            if self._capture_figure:
                self._figure_parts.append(normalized)
            if self._cell is not None:
                self._cell.append(normalized)
        if self._in_json_ld:
            self._json_parts.append(data)


def _request(url: str, *, etag: str | None = None) -> tuple[int, dict[str, str], str]:
    headers = {"User-Agent": "Googlebot/2.1 (+https://www.google.com/bot.html)"}
    if etag:
        headers["If-None-Match"] = etag
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=30) as response:
            headers = {key.lower(): value for key, value in response.headers.items()}
            return response.status, headers, response.read().decode()
    except HTTPError as error:
        headers = {key.lower(): value for key, value in error.headers.items()}
        return error.code, headers, error.read().decode()


def _json(url: str) -> dict[str, Any]:
    status, _, body = _request(url)
    if status != 200:
        raise AssertionError(f"GET {url} returned {status}")
    value = json.loads(body)
    if not isinstance(value, dict):
        raise AssertionError(f"GET {url} did not return an object")
    return value


def _number(value: str) -> int | None:
    cleaned = value.replace(",", "").strip()
    return None if cleaned == "—" else int(cleaned)


def _pretty_date(value: str) -> str:
    parsed = date.fromisoformat(value[:10])
    return f"{parsed.strftime('%B')} {parsed.day}, {parsed.year}"


def _is_fatal(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "t", "yes", "y"}
    return bool(value)


def audit(
    base_url: str,
    *,
    stats_url: str | None = None,
    sitemap_url: str | None = None,
) -> dict[str, Any]:
    """Raise on any mismatch and return a concise success summary."""
    base = base_url.rstrip("/") + "/"
    meta = _json(urljoin(base, "meta"))
    shootings = _json(urljoin(base, "shootings/meta"))
    years = [int(year) for year in shootings["years"]]
    current_year = years[-1]
    current_meta = shootings["years_meta"][str(current_year)]
    current_rows_url = urljoin(base, str(current_meta["rows_url"]).lstrip("/"))
    status, _, ndjson = _request(current_rows_url)
    if status != 200:
        raise AssertionError(f"GET {current_rows_url} returned {status}")
    current_rows = [json.loads(line) for line in ndjson.splitlines() if line.strip()]
    fatal = sum(_is_fatal(row.get("fatal")) for row in current_rows)
    nonfatal = len(current_rows) - fatal

    public_stats_url = stats_url or urljoin(base, "stats")
    public_sitemap_url = sitemap_url or urljoin(base, "sitemap.xml")
    status, headers, html = _request(public_stats_url)
    if status != 200:
        raise AssertionError(f"GET {public_stats_url} returned {status}")
    parser = StatsParser()
    parser.feed(html)
    text = " ".join(parser.visible_text)

    expected_canonical = "https://www.nickhand.dev/philly-gun-violence-map/stats"
    _require(parser.canonical == expected_canonical, "Stats canonical URL is incorrect")
    cache_directives = {
        directive.strip().lower()
        for directive in headers.get("cache-control", "").split(",")
        if directive.strip()
    }
    _require(
        {"public", "max-age=0", "must-revalidate"} <= cache_directives,
        "Stats cache-control directives are incomplete",
    )
    _require("etag" in headers, "Stats response is missing an ETag")
    revalidation_status, _, _ = _request(public_stats_url, etag=headers["etag"])
    _require(revalidation_status == 304, "Stats ETag did not revalidate with HTTP 304")

    _require(
        int(shootings["rows"]) == int(meta["shootings"]["row_count"]),
        "Shootings row count disagrees with API metadata",
    )
    _require(
        sum(int(shootings["years_meta"][str(year)]["rows"]) for year in years)
        == int(shootings["rows"]),
        "Per-year shooting rows do not sum to the all-years count",
    )
    _require(len(current_rows) == int(current_meta["rows"]), "Current-year row count is wrong")
    _require(len(parser.figures) == 3, "Stats page must expose exactly three headline figures")
    _require(_number(parser.figures[0]) == len(current_rows), "Current-year figure is wrong")
    _require(_number(parser.figures[2]) == int(shootings["rows"]), "All-years figure is wrong")
    _require(f"{fatal:,} fatal" in text, "Fatal shooting count is missing")
    _require(f"{nonfatal:,} nonfatal" in text, "Nonfatal shooting count is missing")

    current_homicides = _json(urljoin(base, f"homicides/{current_year}"))
    _require(
        _number(parser.figures[1]) == int(current_homicides["ytd"]),
        "Current homicide figure is wrong",
    )
    previous_homicides = _json(urljoin(base, f"homicides/{current_year - 1}"))
    if previous_homicides["ytd"]:
        change = round(
            (
                (float(current_homicides["ytd"]) - float(previous_homicides["ytd"]))
                / float(previous_homicides["ytd"])
            )
            * 100
        )
        direction = "up" if change > 0 else "down"
        _require(
            f"{direction} {abs(change)}% from {int(previous_homicides['ytd']):,} homicides" in text,
            "Homicide year-over-year comparison is wrong",
        )

    table = {}
    for row in parser.table_rows:
        if len(row) != 4:
            raise AssertionError(f"Unexpected stats table row: {row}")
        year_match = re.match(r"(\d{4})", row[0])
        if not year_match:
            raise AssertionError(f"Missing year in stats table row: {row}")
        table[int(year_match.group(1))] = (_number(row[1]), _number(row[3]))

    _require(sorted(table) == years, "Stats year table does not match available years")
    for year in years:
        expected_victims = int(shootings["years_meta"][str(year)]["rows"])
        homicide_record = _json(urljoin(base, f"homicides/{year}"))
        expected_homicides = (
            homicide_record["ytd"] if year == current_year else homicide_record["annual"]
        )
        _require(table[year][0] == expected_victims, f"Shooting count is wrong for {year}")
        _require(table[year][1] == expected_homicides, f"Homicide count is wrong for {year}")

    peak_year = max(
        years[:-1] or years,
        key=lambda year: int(shootings["years_meta"][str(year)]["rows"]),
    )
    peak_victims = int(shootings["years_meta"][str(peak_year)]["rows"])
    _require(
        f"highest year {peak_year} · {peak_victims:,}" in text,
        "Peak shooting-victim annotation is wrong",
    )

    shooting_date = str(meta["shootings"]["data_through"])
    homicide_date = str(meta["homicides"]["data_through"])
    _require(
        f"As of {_pretty_date(shooting_date)}, there have been" in text,
        "Shootings freshness copy is wrong",
    )
    _require(
        f"As of {_pretty_date(homicide_date)}, Philadelphia has recorded" in text,
        "Homicide freshness copy is wrong",
    )
    _require(
        bool(parser.description)
        and f"{len(current_rows):,} shooting victims" in str(parser.description),
        "Meta description is missing the current shooting count",
    )
    _require(
        f"{int(current_homicides['ytd']):,} homicides" in str(parser.description),
        "Meta description is missing the current homicide count",
    )

    faq = next(item for item in parser.json_ld if item.get("@type") == "FAQPage")
    faq_text = json.dumps(faq)
    _require(f"{len(current_rows):,} shooting victims" in faq_text, "FAQ shooting count is wrong")
    _require(
        f"{int(current_homicides['ytd']):,} homicides" in faq_text,
        "FAQ homicide count is wrong",
    )
    _require(
        f"highest victim count in this dataset is {peak_year}" in faq_text,
        "FAQ peak-year statement is wrong",
    )

    sitemap_status, _, sitemap = _request(public_sitemap_url)
    _require(sitemap_status == 200, "Sitemap did not return HTTP 200")
    _require(expected_canonical in sitemap, "Sitemap is missing the stats canonical URL")
    _require(
        f"<lastmod>{max(shooting_date, homicide_date)}</lastmod>" in sitemap,
        "Sitemap last-modified date is stale",
    )

    return {
        "current_year": current_year,
        "shooting_victims": len(current_rows),
        "fatal": fatal,
        "nonfatal": nonfatal,
        "homicides_ytd": int(current_homicides["ytd"]),
        "all_years_victims": int(shootings["rows"]),
        "shootings_data_through": shooting_date,
        "homicides_data_through": homicide_date,
        "years_checked": len(years),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url", help="API origin containing /stats and data endpoints")
    parser.add_argument(
        "--stats-url",
        help="Public stats URL to audit when it is proxied from a separate origin",
    )
    parser.add_argument(
        "--sitemap-url",
        help="Public sitemap URL to audit when it is proxied from a separate origin",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            audit(
                args.base_url,
                stats_url=args.stats_url,
                sitemap_url=args.sitemap_url,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
