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
    assert parser.canonical == expected_canonical
    cache_directives = {
        directive.strip().lower()
        for directive in headers.get("cache-control", "").split(",")
        if directive.strip()
    }
    assert {"public", "max-age=0", "must-revalidate"} <= cache_directives
    assert "etag" in headers
    revalidation_status, _, _ = _request(public_stats_url, etag=headers["etag"])
    assert revalidation_status == 304

    assert int(shootings["rows"]) == int(meta["shootings"]["row_count"])
    assert sum(int(shootings["years_meta"][str(year)]["rows"]) for year in years) == int(
        shootings["rows"]
    )
    assert len(current_rows) == int(current_meta["rows"])
    assert len(parser.figures) == 3
    assert _number(parser.figures[0]) == len(current_rows)
    assert _number(parser.figures[2]) == int(shootings["rows"])
    assert f"{fatal:,} fatal" in text
    assert f"{nonfatal:,} nonfatal" in text

    current_homicides = _json(urljoin(base, f"homicides/{current_year}"))
    assert _number(parser.figures[1]) == int(current_homicides["ytd"])
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
        assert (
            f"{direction} {abs(change)}% from {int(previous_homicides['ytd']):,} homicides" in text
        )

    table = {}
    for row in parser.table_rows:
        if len(row) != 4:
            raise AssertionError(f"Unexpected stats table row: {row}")
        year_match = re.match(r"(\d{4})", row[0])
        if not year_match:
            raise AssertionError(f"Missing year in stats table row: {row}")
        table[int(year_match.group(1))] = (_number(row[1]), _number(row[3]))

    assert sorted(table) == years
    for year in years:
        expected_victims = int(shootings["years_meta"][str(year)]["rows"])
        homicide_record = _json(urljoin(base, f"homicides/{year}"))
        expected_homicides = (
            homicide_record["ytd"] if year == current_year else homicide_record["annual"]
        )
        assert table[year][0] == expected_victims
        assert table[year][1] == expected_homicides

    peak_year = max(
        years[:-1] or years,
        key=lambda year: int(shootings["years_meta"][str(year)]["rows"]),
    )
    peak_victims = int(shootings["years_meta"][str(peak_year)]["rows"])
    assert f"highest year {peak_year} · {peak_victims:,}" in text

    shooting_date = str(meta["shootings"]["data_through"])
    homicide_date = str(meta["homicides"]["data_through"])
    assert f"As of {_pretty_date(shooting_date)}, there have been" in text
    assert f"As of {_pretty_date(homicide_date)}, Philadelphia has recorded" in text
    assert parser.description and f"{len(current_rows):,} shooting victims" in parser.description
    assert f"{int(current_homicides['ytd']):,} homicides" in parser.description

    faq = next(item for item in parser.json_ld if item.get("@type") == "FAQPage")
    faq_text = json.dumps(faq)
    assert f"{len(current_rows):,} shooting victims" in faq_text
    assert f"{int(current_homicides['ytd']):,} homicides" in faq_text
    assert f"highest victim count in this dataset is {peak_year}" in faq_text

    sitemap_status, _, sitemap = _request(public_sitemap_url)
    assert sitemap_status == 200
    assert expected_canonical in sitemap
    assert f"<lastmod>{max(shooting_date, homicide_date)}</lastmod>" in sitemap

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
