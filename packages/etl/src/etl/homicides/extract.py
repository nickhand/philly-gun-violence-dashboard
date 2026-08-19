"""
Extraction helpers for PPD homicide statistics.

Uses Playwright to render the page and JustHTML to parse selectors.
"""

import re
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from justhtml import JustHTML
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

__all__ = [
    "fetch_homicide_dom",
    "parse_homicide_dom",
    "extract_homicide_stats",
    "validate_homicide_snapshot",
]

CRIME_TABLE_SELECTOR = ".container-crime"
PLAYWRIGHT_TIMEOUT_MS = 20_000  # milliseconds
DEFAULT_URL = "https://www.phillypolice.com/crime-data/crime-statistics/"
HISTORICAL_BASELINE_YEAR = 2007
PHILADELPHIA_TIME_ZONE = ZoneInfo("America/New_York")


def _source_today() -> date:
    """Return today's date in the reporting source's local time zone."""
    return datetime.now(PHILADELPHIA_TIME_ZONE).date()


def _parse_if_complete(html: str) -> JustHTML | None:
    """
    Parse HTML and ensure the crime stats tables are present.

    Parameters
    ----------
    html : str
        Raw HTML for the PPD crime stats page.

    Returns
    -------
    JustHTML or None
        Parsed DOM if the expected selector is present; otherwise ``None``.
    """
    doc = JustHTML(html)
    if doc.query(CRIME_TABLE_SELECTOR):
        return doc
    return None


def fetch_homicide_dom(url: str = DEFAULT_URL, debug: bool = False) -> JustHTML:
    """
    Render the PPD crime stats page and return a parsed DOM (sync Playwright).

    Parameters
    ----------
    url : str, optional
        Page URL to fetch, by default the PPD crime statistics page.
    debug : bool, optional
        Whether to run Playwright with a visible (non-headless) browser.

    Returns
    -------
    JustHTML
        Parsed DOM containing the crime stats tables.

    Raises
    ------
    ValueError
        If the page times out or the expected content is missing.
    """
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=not debug,
                channel="chrome",
                chromium_sandbox=True,
            )
            page = browser.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=PLAYWRIGHT_TIMEOUT_MS)
                page.wait_for_selector(CRIME_TABLE_SELECTOR, timeout=PLAYWRIGHT_TIMEOUT_MS)
                html = page.content()
            finally:
                browser.close()
    except PlaywrightTimeoutError as exc:
        raise ValueError("Page took too long to load") from exc

    dom = _parse_if_complete(html)
    if dom is None:
        raise ValueError("Crime stats content not found in rendered page")
    return dom


def _query_first(node: JustHTML, selector: str) -> Any:
    """
    Return the first match for a selector or raise if none exists.

    Parameters
    ----------
    node : JustHTML
        DOM node to search from.
    selector : str
        CSS selector to match.

    Returns
    -------
    Any
        The first matching node.

    Raises
    ------
    ValueError
        If no matching nodes are found.
    """
    matches = node.query(selector)
    if not matches:
        raise ValueError(f"Selector not found: {selector}")
    return matches[0]


def _parse_year_counts(
    container: Any,
    *,
    value_selector: str,
    value_column: str,
    current_year: int,
) -> pd.DataFrame:
    """Parse one year/count table without silently truncating mismatched nodes."""
    year_nodes = container.query(".data-heading")
    value_nodes = container.query(value_selector)
    if not year_nodes or not value_nodes:
        raise ValueError(f"{value_column} table is empty")
    if len(year_nodes) != len(value_nodes):
        raise ValueError(
            f"{value_column} table has {len(year_nodes)} years but {len(value_nodes)} values"
        )

    try:
        years = [int(node.to_text(strip=True)) for node in year_nodes]
        values = [int(node.to_text(strip=True).replace(",", "")) for node in value_nodes]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{value_column} table contains a non-integer value") from exc
    if len(years) != len(set(years)):
        raise ValueError(f"{value_column} table contains duplicate years")
    if any(year < 1900 or year > current_year + 1 for year in years):
        raise ValueError(f"{value_column} table contains an implausible year")
    if any(value < 0 for value in values):
        raise ValueError(f"{value_column} table contains a negative count")

    return pd.DataFrame({"year": years, value_column: values}).sort_values("year", ascending=False)


def _require_historical_coverage(
    years: set[int],
    *,
    label: str,
    through_year: int,
) -> None:
    """Reject a truncated source table that would erase dashboard history."""
    expected = set(range(HISTORICAL_BASELINE_YEAR, through_year + 1))
    missing = sorted(expected - years)
    if missing:
        raise ValueError(
            f"{label} is missing historical years from the "
            f"{HISTORICAL_BASELINE_YEAR} baseline: {missing}"
        )


def validate_homicide_snapshot(
    as_of_date: pd.Timestamp,
    annual_totals: pd.DataFrame,
    ytd_totals: pd.DataFrame,
    *,
    today: date | None = None,
) -> int:
    """Validate reporting-period coherence and return the selected YTD year.

    PPD's heading describes a completed reporting day, so future-dated source
    labels receive no tolerance. Historical coverage is required from 2007,
    the first year currently published by the dashboard, to prevent a source
    redesign from silently deleting established comparisons.
    """
    source_today = today or _source_today()
    if not isinstance(as_of_date, pd.Timestamp) or pd.isna(as_of_date):
        raise ValueError("Homicide as-of date must be a valid timestamp")
    if as_of_date.date() > source_today:
        raise ValueError(
            f"Homicide as-of date {as_of_date.date()} is in the future relative to {source_today}"
        )
    if "year" not in annual_totals or "year" not in ytd_totals or ytd_totals.empty:
        raise ValueError("Homicide source tables must contain year values")

    annual_years = annual_totals["year"].tolist()
    ytd_years = ytd_totals["year"].tolist()
    if any(isinstance(year, bool) or not isinstance(year, int) for year in ytd_years):
        raise ValueError("YTD homicide years must be integers")
    if any(isinstance(year, bool) or not isinstance(year, int) for year in annual_years):
        raise ValueError("Annual homicide years must be integers")
    if len(ytd_years) != len(set(ytd_years)):
        raise ValueError("YTD homicide totals contain duplicate years")
    if len(annual_years) != len(set(annual_years)):
        raise ValueError("Annual homicide totals contain duplicate years")

    selected_year = max(ytd_years)
    if as_of_date.year != selected_year:
        raise ValueError(
            f"Homicide as-of year {as_of_date.year} does not match "
            f"the latest YTD row year {selected_year}"
        )
    if any(year >= selected_year for year in annual_years):
        raise ValueError("Annual homicide totals include a current or future reporting year")

    _require_historical_coverage(
        set(ytd_years),
        label="YTD homicide totals",
        through_year=selected_year,
    )
    _require_historical_coverage(
        set(annual_years),
        label="Annual homicide totals",
        through_year=selected_year - 1,
    )
    return selected_year


def parse_homicide_dom(
    dom: JustHTML,
    *,
    today: date | None = None,
) -> tuple[pd.Timestamp, pd.DataFrame, pd.DataFrame]:
    """
    Extract as-of date, annual totals, and YTD totals from the DOM.

    Parameters
    ----------
    dom : JustHTML
        Parsed DOM of the PPD crime stats page.
    today : date, optional
        Reporting-source date used for validation, by default the current date
        in Philadelphia. Tests may inject this value to keep boundary checks
        deterministic.

    Returns
    -------
    tuple
        ``(as_of_date, annual_totals_df, ytd_totals_df)`` where ``as_of_date`` is a
        pandas Timestamp and the DataFrames have columns ``year`` plus ``annual`` or ``ytd``.
    """
    source_today = today or _source_today()

    # Extract the month/day from the title
    month_day_text = _query_first(
        _query_first(dom, ".crime-title"),
        "span.crime-text",
    ).to_text(strip=True)
    as_of_match = re.search(r"\bto\s+(.+?)\s*$", month_day_text, flags=re.IGNORECASE)
    if as_of_match is None:
        raise ValueError("Crime statistics title does not contain an as-of date")
    month_day = as_of_match.group(1)

    # Extract the year-to-date container and year
    ytd_container = _query_first(dom, ".container-crime.year-to-date")
    year_text = _query_first(ytd_container, ".data-heading").to_text(strip=True)
    try:
        year = int(year_text)
    except ValueError as exc:
        raise ValueError("Year-to-date heading is not a valid year") from exc

    # Build the as-of date
    try:
        as_of_date = pd.to_datetime(f"{month_day} {year} 11:59:00", errors="raise")
    except (TypeError, ValueError) as exc:
        raise ValueError("Crime statistics title has an invalid as-of date") from exc
    if as_of_date.year != year:
        raise ValueError("Crime statistics as-of date does not match its heading year")

    # Extract full-year container and build the annual total DataFrame
    full_year_container = _query_first(dom, ".container-crime.full-year")
    annual_totals = _parse_year_counts(
        full_year_container,
        value_selector=".counted-data",
        value_column="annual",
        current_year=source_today.year,
    )

    # Build the year-to-date total DataFrame
    ytd_totals = _parse_year_counts(
        ytd_container,
        value_selector=".counted-data",
        value_column="ytd",
        current_year=source_today.year,
    )

    validate_homicide_snapshot(
        as_of_date,
        annual_totals,
        ytd_totals,
        today=source_today,
    )

    # Return the results
    return as_of_date, annual_totals, ytd_totals


def extract_homicide_stats(debug: bool = False) -> tuple[pd.Timestamp, pd.DataFrame, pd.DataFrame]:
    """
    Fetch and parse homicide stats in one call.

    Parameters
    ----------
    debug : bool, optional
        Whether to run Playwright with a visible (non-headless) browser.

    Returns
    -------
    tuple
        ``(as_of_date, annual_totals_df, ytd_totals_df)`` as produced by ``parse_homicide_dom``.
    """
    dom = fetch_homicide_dom(debug=debug)
    return parse_homicide_dom(dom)
