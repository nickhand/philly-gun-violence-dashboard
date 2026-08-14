"""Build and cache crawler-visible statistics pages from loaded API data."""

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from html import escape
from pathlib import Path
from typing import Any

from fastapi import FastAPI

CANONICAL_BASE = "https://www.nickhand.dev/philly-gun-violence-map"
API_BASE = "https://philly-gun-violence-dashboard-api.fly.dev"
_TEMPLATE = Path(__file__).with_name("templates").joinpath("stats.html").read_text()


@dataclass(frozen=True)
class YearStats:
    """Shooting-victim and homicide totals for one calendar year."""

    year: int
    victims: int
    homicides: int | float | None


@dataclass(frozen=True)
class StatsSnapshot:
    """All values used by the human-readable statistics page."""

    shootings_data_through: str
    homicides_data_through: str
    current_year: int
    previous_year: int
    minimum_year: int
    total_victims_all_years: int
    current_total: int
    current_fatal: int
    current_nonfatal: int
    homicides_ytd: int | float | None
    homicides_previous_ytd: int | float | None
    homicide_percent_change: int | None
    peak: YearStats
    years: tuple[YearStats, ...]


@dataclass(frozen=True)
class StatsPageCache:
    """Rendered SEO responses cached against the loaded dataset versions."""

    source_key: tuple[str, ...]
    html: str
    sitemap: str
    etag: str


def _as_number(value: object) -> int | float | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    return None


def _is_fatal(value: object) -> bool:
    """Interpret the normalized flag while tolerating historical string values."""
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "t", "yes", "y"}
    return bool(value)


def _derive_data_through(rows_by_year: dict[int, list[dict[str, Any]]]) -> str:
    dates = [
        str(row["date"])[:10] for rows in rows_by_year.values() for row in rows if row.get("date")
    ]
    return max(dates, default=date.today().isoformat())


def _freshness_date(metadata: object, fallback: str) -> str:
    if isinstance(metadata, dict):
        value = metadata.get("data_through")
        if isinstance(value, str) and value:
            candidate = value[:10]
            try:
                date.fromisoformat(candidate)
            except ValueError:
                pass
            else:
                return candidate
    return fallback


def _yearly_homicide_value(
    totals: dict[str, Any],
    year: int,
    *,
    current_year: int,
) -> int | float | None:
    record = totals.get(str(year))
    if not isinstance(record, dict):
        return None
    field = "ytd" if year == current_year else "annual"
    return _as_number(record.get(field))


def build_stats_snapshot(app: FastAPI) -> StatsSnapshot:
    """Aggregate an immutable page snapshot from already-loaded application state."""
    rows_by_year = app.state.shootings_rows_by_year
    years = sorted(rows_by_year)
    if not years:
        raise ValueError("Cannot render the statistics page without shooting records.")

    current_year = years[-1]
    previous_year = current_year - 1
    current_rows = rows_by_year[current_year]
    current_fatal = sum(_is_fatal(row.get("fatal")) for row in current_rows)
    dated_victims = sum(len(rows_by_year[year]) for year in years)
    shootings_meta = getattr(app.state, "shootings_meta", {})
    total_victims = (
        shootings_meta.get("rows", dated_victims)
        if isinstance(shootings_meta, dict)
        else dated_victims
    )
    homicides_totals = app.state.homicides_totals

    yearly = tuple(
        YearStats(
            year=year,
            victims=len(rows_by_year[year]),
            homicides=_yearly_homicide_value(
                homicides_totals,
                year,
                current_year=current_year,
            ),
        )
        for year in years
    )
    completed_years = tuple(item for item in yearly if item.year != current_year)
    peak = max(completed_years or yearly, key=lambda item: item.victims)

    current_homicides = _yearly_homicide_value(
        homicides_totals,
        current_year,
        current_year=current_year,
    )
    previous_record = homicides_totals.get(str(previous_year), {})
    previous_homicides = (
        _as_number(previous_record.get("ytd")) if isinstance(previous_record, dict) else None
    )
    percent_change = None
    if current_homicides is not None and previous_homicides is not None and previous_homicides != 0:
        percent_change = round(
            ((current_homicides - previous_homicides) / previous_homicides) * 100
        )

    fallback_date = _derive_data_through(rows_by_year)
    shootings_date = _freshness_date(
        getattr(app.state, "shootings_freshness", None),
        fallback_date,
    )
    homicides_date = _freshness_date(
        getattr(app.state, "homicides_freshness", None),
        shootings_date,
    )

    return StatsSnapshot(
        shootings_data_through=shootings_date,
        homicides_data_through=homicides_date,
        current_year=current_year,
        previous_year=previous_year,
        minimum_year=years[0],
        total_victims_all_years=total_victims,
        current_total=len(current_rows),
        current_fatal=current_fatal,
        current_nonfatal=len(current_rows) - current_fatal,
        homicides_ytd=current_homicides,
        homicides_previous_ytd=previous_homicides,
        homicide_percent_change=percent_change,
        peak=peak,
        years=yearly,
    )


def _format_number(value: int | float | None) -> str:
    if value is None:
        return "—"
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.1f}"


def _format_date(value: str) -> str:
    parsed = date.fromisoformat(value[:10])
    return f"{parsed.strftime('%B')} {parsed.day}, {parsed.year}"


def _homicide_sentence(snapshot: StatsSnapshot) -> str:
    if snapshot.homicides_ytd is None:
        return ""
    as_of = _format_date(snapshot.homicides_data_through)
    sentence = (
        f"As of {as_of}, Philadelphia has recorded "
        f"{_format_number(snapshot.homicides_ytd)} homicides in {snapshot.current_year}"
    )
    change = snapshot.homicide_percent_change
    if change is None:
        return f"{sentence}."
    if change == 0:
        return f"{sentence}, unchanged from the same point in {snapshot.previous_year}."
    direction = "up" if change > 0 else "down"
    return (
        f"{sentence}, {direction} {abs(change)}% from "
        f"{_format_number(snapshot.homicides_previous_ytd)} homicides at the same point "
        f"in {snapshot.previous_year}."
    )


def _shooting_sentence(snapshot: StatsSnapshot) -> str:
    as_of = _format_date(snapshot.shootings_data_through)
    return (
        f"As of {as_of}, there have been {_format_number(snapshot.current_total)} "
        f"shooting victims in Philadelphia in {snapshot.current_year}: "
        f"{_format_number(snapshot.current_fatal)} fatal and "
        f"{_format_number(snapshot.current_nonfatal)} nonfatal."
    )


def _peak_sentence(snapshot: StatsSnapshot) -> str:
    homicide_suffix = (
        f" and {_format_number(snapshot.peak.homicides)} total homicides"
        if snapshot.peak.homicides is not None
        else ""
    )
    return (
        f"The highest victim count in this dataset is {snapshot.peak.year}, with "
        f"{_format_number(snapshot.peak.victims)} shooting victims{homicide_suffix}."
    )


def _faq(snapshot: StatsSnapshot) -> list[dict[str, str]]:
    shootings = _shooting_sentence(snapshot)
    homicides = _homicide_sentence(snapshot)
    peak = _peak_sentence(snapshot)
    change = snapshot.homicide_percent_change
    if change is None:
        trend_answer = f"{shootings} {peak}"
    else:
        direction = "up" if change > 0 else "down" if change < 0 else "unchanged"
        comparison = (
            f"Year-to-date homicides in {snapshot.current_year} are {direction}"
            f"{f' {abs(change)}%' if change else ''} compared with the same point in "
            f"{snapshot.previous_year}."
        )
        trend_answer = f"{comparison} {peak}"

    return [
        {
            "q": f"How many shootings have there been in Philadelphia in {snapshot.current_year}?",
            "a": shootings,
        },
        {
            "q": f"How many homicides has Philadelphia had in {snapshot.current_year}?",
            "a": (
                f"{homicides} The homicide count includes all homicides, not only firearm deaths."
                if homicides
                else "Current homicide totals are temporarily unavailable."
            ),
        },
        {
            "q": "Is gun violence in Philadelphia increasing or decreasing?",
            "a": trend_answer,
        },
        {
            "q": "Where does this data come from?",
            "a": (
                "Shooting victim data comes from the Philadelphia Police Department through "
                "OpenDataPhilly and is updated daily. Homicide totals come from the PPD "
                "Statistics Unit. Court records come from Pennsylvania's Unified Judicial "
                "System portal. All data is preliminary and may differ from other official sources."
            ),
        },
        {
            "q": "How can I download Philadelphia shooting data?",
            "a": (
                f"Download CSV or GeoJSON from the interactive dashboard at {CANONICAL_BASE}/, "
                f"use the public JSON API at {API_BASE}/docs, or get the source data from "
                "OpenDataPhilly."
            ),
            "a_html": (
                f'Download CSV or GeoJSON from the <a href="{CANONICAL_BASE}/">interactive '
                f'dashboard</a>, use the <a href="{API_BASE}/docs">public JSON API</a>, or get '
                'the source data from <a href="https://opendataphilly.org/datasets/'
                'shooting-victims/" rel="noopener">OpenDataPhilly</a>.'
            ),
        },
    ]


def _json_for_html(value: object) -> str:
    return (
        json.dumps(value, indent=2, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def render_stats_page(snapshot: StatsSnapshot) -> str:
    """Render the complete no-JavaScript statistics document."""
    shooting_sentence = _shooting_sentence(snapshot)
    homicide_sentence = _homicide_sentence(snapshot)
    peak_sentence = _peak_sentence(snapshot)
    total_sentence = (
        f"Since {snapshot.minimum_year}, Philadelphia has recorded "
        f"{_format_number(snapshot.total_victims_all_years)} shooting victims."
    )
    faq = _faq(snapshot)
    faq_json_ld = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": item["q"],
                "acceptedAnswer": {"@type": "Answer", "text": item["a"]},
            }
            for item in faq
        ],
    }
    dataset_json_ld = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebPage",
                "name": "Philadelphia Gun Violence Statistics",
                "url": f"{CANONICAL_BASE}/stats",
                "dateModified": max(
                    snapshot.shootings_data_through,
                    snapshot.homicides_data_through,
                ),
            },
            {
                "@type": "Dataset",
                "name": "Philadelphia Shooting Victims Data",
                "url": f"{CANONICAL_BASE}/stats",
                "dateModified": snapshot.shootings_data_through,
                "temporalCoverage": f"{snapshot.minimum_year}/{snapshot.current_year}",
                "isAccessibleForFree": True,
                "distribution": {
                    "@type": "DataDownload",
                    "encodingFormat": "application/json",
                    "contentUrl": f"{API_BASE}/shootings/meta",
                },
            },
        ],
    }

    max_victims = max(item.victims for item in snapshot.years)
    table_rows = []
    for item in snapshot.years:
        current = item.year == snapshot.current_year
        year_label = f'{item.year} <span class="ytd">YTD</span>' if current else str(item.year)
        year_class = "yr yr-current" if current else "yr"
        percentage = round((item.victims / max_victims) * 100) if max_victims else 0
        table_rows.append(
            f'<tr><td class="{year_class}">{year_label}</td>'
            f'<td class="num">{_format_number(item.victims)}</td>'
            f'<td class="bar-cell"><div class="bar-track"><div class="bar-fill" '
            f'style="width:{percentage}%"></div></div></td>'
            f'<td class="num">{_format_number(item.homicides)}</td></tr>'
        )

    summary_parts = []
    if homicide_sentence:
        summary_parts.append(f"<p>{escape(homicide_sentence)}</p>")
    summary_parts.append(
        f"<p>{escape(shooting_sentence)} {escape(total_sentence)} {escape(peak_sentence)}</p>"
    )
    faq_html = "\n        ".join(
        f'<div class="faq-row"><h3>{escape(item["q"])}</h3>'
        f"<p>{item.get('a_html', escape(item['a']))}</p></div>"
        for item in faq
    )

    change = snapshot.homicide_percent_change
    if change is None:
        trend_detail = ""
    elif change == 0:
        trend_detail = (
            f'<div class="figure-detail"><span class="c-date">unchanged vs. '
            f"{snapshot.previous_year}</span></div>"
        )
    else:
        direction = "up" if change > 0 else "down"
        trend_detail = (
            f'<div class="figure-detail"><span class="c-date">{direction} {abs(change)}% '
            f"vs. {snapshot.previous_year}</span></div>"
        )

    shootings_as_of = _format_date(snapshot.shootings_data_through)
    homicides_as_of = _format_date(snapshot.homicides_data_through)
    title = f"Philadelphia Gun Violence Statistics {snapshot.current_year} | Shootings & Homicides"
    description = f"{shooting_sentence} {homicide_sentence} Updated daily from public data."
    replacements = {
        "{{TITLE}}": escape(title, quote=True),
        "{{DESCRIPTION}}": escape(description, quote=True),
        "{{CANONICAL_URL}}": f"{CANONICAL_BASE}/stats",
        "{{CANONICAL_BASE}}": CANONICAL_BASE,
        "{{API_BASE}}": API_BASE,
        "{{FAQ_JSON_LD}}": _json_for_html(faq_json_ld),
        "{{DATASET_JSON_LD}}": _json_for_html(dataset_json_ld),
        "{{FRESHNESS_LABEL}}": (
            f"Data through {shootings_as_of}"
            if shootings_as_of == homicides_as_of
            else f"Shootings through {shootings_as_of} · Homicides through {homicides_as_of}"
        ),
        "{{CURRENT_TOTAL}}": _format_number(snapshot.current_total),
        "{{CURRENT_YEAR}}": str(snapshot.current_year),
        "{{CURRENT_FATAL}}": _format_number(snapshot.current_fatal),
        "{{CURRENT_NONFATAL}}": _format_number(snapshot.current_nonfatal),
        "{{HOMICIDES_YTD}}": _format_number(snapshot.homicides_ytd),
        "{{TREND_DETAIL}}": trend_detail,
        "{{TOTAL_ALL_YEARS}}": _format_number(snapshot.total_victims_all_years),
        "{{MIN_YEAR}}": str(snapshot.minimum_year),
        "{{PEAK_YEAR}}": str(snapshot.peak.year),
        "{{PEAK_VICTIMS}}": _format_number(snapshot.peak.victims),
        "{{SUMMARY_PARAGRAPHS}}": "\n        ".join(summary_parts),
        "{{TABLE_ROWS}}": "\n            ".join(table_rows),
        "{{FAQ_HTML}}": faq_html,
    }
    html = _TEMPLATE
    for marker, value in replacements.items():
        html = html.replace(marker, value)
    return html


def render_sitemap(snapshot: StatsSnapshot) -> str:
    """Render a data-aware sitemap for the canonical dashboard URLs."""
    latest = max(snapshot.shootings_data_through, snapshot.homicides_data_through)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{CANONICAL_BASE}/</loc>
    <lastmod>{latest}</lastmod>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>{CANONICAL_BASE}/stats</loc>
    <lastmod>{latest}</lastmod>
    <changefreq>daily</changefreq>
    <priority>0.9</priority>
  </url>
  <url>
    <loc>{CANONICAL_BASE}/about</loc>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
  </url>
</urlset>
"""


def stats_source_key(app: FastAPI) -> tuple[str, ...]:
    """Return the state signature that controls rendered-page invalidation."""
    etags = app.state.dataset_etags
    shootings_freshness = getattr(app.state, "shootings_freshness", {})
    homicides_freshness = getattr(app.state, "homicides_freshness", {})
    if not isinstance(shootings_freshness, dict):
        shootings_freshness = {}
    if not isinstance(homicides_freshness, dict):
        homicides_freshness = {}
    return (
        str(app.state.shootings_version),
        str(etags.get("shootings", "")),
        str(etags.get("homicides", "")),
        str(shootings_freshness.get("data_through", "")),
        str(homicides_freshness.get("data_through", "")),
    )


def render_and_cache_stats_page(app: FastAPI) -> StatsPageCache:
    """Render both SEO responses and place them in application state."""
    source_key = stats_source_key(app)
    snapshot = build_stats_snapshot(app)
    html = render_stats_page(snapshot)
    sitemap = render_sitemap(snapshot)
    etag = hashlib.sha256(f"{html}\n{sitemap}".encode()).hexdigest()[:16]
    cached = StatsPageCache(source_key=source_key, html=html, sitemap=sitemap, etag=etag)
    app.state.stats_page_cache = cached
    return cached


def get_stats_page_cache(app: FastAPI) -> StatsPageCache:
    """Reuse the cached documents unless either loaded dataset has changed."""
    cached = getattr(app.state, "stats_page_cache", None)
    if isinstance(cached, StatsPageCache) and cached.source_key == stats_source_key(app):
        return cached
    return render_and_cache_stats_page(app)
