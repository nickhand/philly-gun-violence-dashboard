"""
Extraction helpers for PPD homicide statistics.

Uses Playwright (sync) to render the page and JustHTML to parse selectors.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Tuple

import pandas as pd
from justhtml import JustHTML
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

__all__ = [
    "DEFAULT_URL",
    "fetch_homicide_dom",
    "parse_homicide_dom",
    "extract_homicide_stats",
]

CRIME_TABLE_SELECTOR = ".container-crime"
PLAYWRIGHT_TIMEOUT_MS = 20_000  # milliseconds
DEFAULT_URL = "https://www.phillypolice.com/crime-data/crime-statistics/"

# Run sync Playwright in a worker thread when called from a running event loop
_THREAD_EXECUTOR: ThreadPoolExecutor | None = None


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


def _fetch_homicide_dom_sync(url: str = DEFAULT_URL, debug: bool = False) -> JustHTML:
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
            browser = p.chromium.launch(headless=not debug)
            page = browser.new_page()
            try:
                page.goto(url, wait_until="networkidle", timeout=PLAYWRIGHT_TIMEOUT_MS)
                page.wait_for_selector(
                    CRIME_TABLE_SELECTOR, timeout=PLAYWRIGHT_TIMEOUT_MS
                )
                html = page.content()
            finally:
                browser.close()
    except PlaywrightTimeoutError as exc:
        raise ValueError("Page took too long to load") from exc

    dom = _parse_if_complete(html)
    if dom is None:
        raise ValueError("Crime stats content not found in rendered page")
    return dom


def _run_sync_threadsafe(fn, *args, **kwargs):
    """
    Run a sync function safely, even when already inside an event loop.

    Parameters
    ----------
    fn : callable
        Function to execute.
    *args
        Positional arguments passed to ``fn``.
    **kwargs
        Keyword arguments passed to ``fn``.

    Returns
    -------
    Any
        Result from the function call.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return fn(*args, **kwargs)

    global _THREAD_EXECUTOR
    if _THREAD_EXECUTOR is None:
        _THREAD_EXECUTOR = ThreadPoolExecutor(max_workers=1)
    future = loop.run_in_executor(_THREAD_EXECUTOR, lambda: fn(*args, **kwargs))
    return future.result()


def fetch_homicide_dom(url: str = DEFAULT_URL, debug: bool = False) -> JustHTML:
    """
    Fetch the homicide stats DOM using sync Playwright; safe in async contexts.

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
    """
    return _run_sync_threadsafe(_fetch_homicide_dom_sync, url, debug)


def _query_first(node, selector: str):
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


def parse_homicide_dom(
    dom: JustHTML,
) -> Tuple[pd.Timestamp, pd.DataFrame, pd.DataFrame]:
    """
    Extract as-of date, annual totals, and YTD totals from the DOM.

    Parameters
    ----------
    dom : JustHTML
        Parsed DOM of the PPD crime stats page.

    Returns
    -------
    tuple
        ``(as_of_date, annual_totals_df, ytd_totals_df)`` where ``as_of_date`` is a
        pandas Timestamp and the DataFrames have columns ``year`` plus ``annual`` or ``ytd``.
    """
    month_day_text = _query_first(
        _query_first(dom, ".crime-title"), "span.crime-text"
    ).to_text(strip=True)
    month_day = month_day_text.split("to")[-1].strip()

    ytd_container = _query_first(dom, ".container-crime.year-to-date")
    year_text = _query_first(ytd_container, ".data-heading").to_text(strip=True)
    year = int(year_text)
    as_of_date = pd.to_datetime(f"{month_day} {year} 11:59:00")

    full_year_container = _query_first(dom, ".container-crime.full-year")
    annual_totals = pd.DataFrame(
        {
            "year": [
                int(div.to_text(strip=True))
                for div in full_year_container.query(".data-heading")
            ],
            "annual": [
                int(div.to_text(strip=True))
                for div in full_year_container.query(".counted-data")
            ],
        }
    ).sort_values("year", ascending=False)

    ytd_totals = pd.DataFrame(
        {
            "year": [
                int(div.to_text(strip=True))
                for div in ytd_container.query(".data-heading")
            ],
            "ytd": [
                int(div.to_text(strip=True))
                for div in ytd_container.query(".counted-data")
            ],
        }
    ).sort_values("year", ascending=False)

    return as_of_date, annual_totals, ytd_totals


def extract_homicide_stats(
    debug: bool = False,
) -> Tuple[pd.Timestamp, pd.DataFrame, pd.DataFrame]:
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
