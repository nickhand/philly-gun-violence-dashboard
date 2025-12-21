"""Scrape data from the PA Unified Judicial System portal using Playwright."""

import time
from dataclasses import dataclass, field
from typing import Any

from justhtml import JustHTML
from loguru import logger
from playwright.sync_api import (
    Browser,
    Page,
    Playwright,
    sync_playwright,
)
from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
)
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from .schema import PortalResults

PORTAL_URL = "https://ujsportal.pacourts.us/CaseSearch"
SEARCH_BY_OPTIONS = {"Incident Number", "Docket Number"}

# Selectors used in the portal UI
SEARCH_BY_DROPDOWN = "#SearchBy-Control select"
SEARCH_BUTTON = "#btnSearch"
RESULTS_CONTAINER = "#caseSearchResultGrid"

# Fields expected from the results table (order matters)
RESULT_FIELDS = [
    "docket_number",
    "court_type",
    "short_caption",
    "case_status",
    "filing_date",
    "party",
    "date_of_birth",
    "county",
    "court_office",
    "otn",
    "lotn",
    "dc_number",
]

__all__ = ["UJSPortalScraper"]


def _has_class(node, class_name: str) -> bool:
    """
    Check whether a JustHTML node has a given CSS class.

    Parameters
    ----------
    node : Any
        Node to inspect.
    class_name : str
        CSS class name to check for.

    Returns
    -------
    bool
        True if the class is present.
    """
    classes = node.attrs.get("class")
    if classes is None:
        return False
    if isinstance(classes, str):
        return class_name in classes.split()
    try:
        return class_name in classes
    except TypeError:
        return False


def _parse_results(html: str) -> PortalResults | None:
    """
    Parse the portal search results table into structured records.

    Parameters
    ----------
    html : str
        HTML content of the results page.

    Returns
    -------
    PortalResults or None
        Parsed results, or None if no data rows were found.
    """
    doc = JustHTML(html)
    tables = doc.query(RESULTS_CONTAINER)
    if not tables:
        return None

    rows = tables[0].query("tbody > tr")
    data: list[dict[str, Any]] = []
    for row in rows:
        cells = [
            td.to_text(strip=True)
            for td in row.query("td")
            if not _has_class(td, "display-none")
        ]
        if not cells:
            continue
        if len(cells) < len(RESULT_FIELDS):
            continue

        record = dict(zip(RESULT_FIELDS, cells[: len(RESULT_FIELDS)]))
        links = [
            a.attrs.get("href")
            for a in row.query("a")
            if a.attrs and a.attrs.get("href")
        ]
        if len(links) >= 2:
            record["court_summary_url"] = links[-1]
            record["docket_sheet_url"] = links[-2]
        data.append(record)

    if not data:
        return None
    return PortalResults.model_validate({"data": data})


@dataclass
class UJSPortalScraper:
    """
    Scrape the UJS courts portal by incident number or docket number.
    """

    search_by: str = "Incident Number"
    debug: bool = False
    log_freq: int = 50
    sleep: float = 7.0
    timeout_ms: int = 12_000
    max_attempts: int = 8
    wait_min: float = 5.0
    wait_max: float = 30.0
    errors: str = "raise"

    _playwright: Playwright | None = field(init=False, default=None)
    _browser: Browser | None = field(init=False, default=None)
    _page: Page | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        """
        Validate configuration and build the retry strategy.
        """
        if self.search_by not in SEARCH_BY_OPTIONS:
            raise ValueError(f"search_by must be one of {SEARCH_BY_OPTIONS}")
        self._retryer = Retrying(
            stop=stop_after_attempt(self.max_attempts),
            wait=wait_random_exponential(multiplier=self.wait_min, max=self.wait_max),
            retry=retry_if_exception_type(Exception),
            reraise=True,
            before_sleep=self._before_retry,
        )

    def _before_retry(self, retry_state) -> None:
        """
        Reset the page and back off before a retry.

        Parameters
        ----------
        retry_state : tenacity.RetryCallState
            State containing attempt info and exception.
        """
        input_value = retry_state.args[0] if retry_state.args else "unknown"
        attempt = retry_state.attempt_number
        logger.warning(
            "Retrying portal scrape for %s (attempt %s/%s) due to: %s",
            input_value,
            attempt,
            self.max_attempts,
            retry_state.outcome.exception(),
        )
        self._reset_page()
        time.sleep(self.sleep)

    def __enter__(self):
        self._ensure_page()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def _ensure_page(self) -> Page:
        """
        Lazily start Playwright and navigate to the portal.
        """
        if self._page is not None:
            return self._page
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=not self.debug)
        self._page = self._browser.new_page()
        self._page.goto(PORTAL_URL, wait_until="networkidle", timeout=self.timeout_ms)
        self._page.select_option(SEARCH_BY_DROPDOWN, label=self.search_by)
        return self._page

    def _reset_page(self) -> None:
        """
        Close Playwright objects and reset handles.
        """
        try:
            if self._page:
                self._page.close()
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
        finally:
            self._playwright = None
            self._browser = None
            self._page = None

    def close(self) -> None:
        """
        Close Playwright resources.
        """
        self._reset_page()

    def _normalize_input(self, input_value: str) -> str | None:
        """
        Normalize an input value for the selected search type.

        Parameters
        ----------
        input_value : str
            Raw input value.

        Returns
        -------
        str or None
            Normalized value or None if invalid.
        """
        value = str(input_value)
        if self.search_by == "Incident Number":
            if len(value) == 12:
                value = value[2:]
            if len(value) != 10:
                return None
        return value

    def _scrape_once(self, input_value: str) -> PortalResults | None:
        """
        Perform a single scrape attempt for one input value.

        Parameters
        ----------
        input_value : str
            Incident or docket number.

        Returns
        -------
        PortalResults or None
            Parsed results or None when validation/parsing fails.
        """
        self._ensure_page()
        normalized = self._normalize_input(input_value)
        if normalized is None:
            return None

        page = self._ensure_page()
        search_by_tag = self.search_by.replace(" ", "")
        input_selector = f"#{search_by_tag}-Control input"

        page.fill(input_selector, "")
        page.fill(input_selector, normalized)
        page.click(SEARCH_BUTTON)

        try:
            page.wait_for_selector(
                RESULTS_CONTAINER, timeout=self.timeout_ms, state="visible"
            )
        except PlaywrightTimeoutError as exc:
            raise ValueError("Portal results did not load in time") from exc

        html = page.content()
        return _parse_results(html)

    def __call__(self, input_value: str) -> PortalResults | None:
        """
        Scrape portal results for a single input with retries.

        Parameters
        ----------
        input_value : str
            Incident or docket number.

        Returns
        -------
        PortalResults or None
            Parsed results or None if validation/parsing fails.
        """
        for attempt in self._retryer:
            with attempt:
                return self._scrape_once(input_value)
        return None

    def scrape_portal_data(self, input_values: list[str]) -> list[dict[str, Any]]:
        """
        Scrape portal data for a list of input values.

        Parameters
        ----------
        input_values : list[str]
            Values to query (incident or docket numbers).

        Returns
        -------
        list[dict]
            Flattened list of result dictionaries.
        """
        results: list[dict[str, Any]] = []
        N = len(input_values)
        logger.info("Scraping info for %d values", N)

        try:
            for i, val in enumerate(input_values):
                if i % self.log_freq == 0:
                    logger.debug("Scraping index %d", i)
                portal_results = self(val)
                if portal_results is None:
                    continue
                results.extend(portal_results.model_dump()["data"])
                time.sleep(self.sleep)
        except Exception as exc:
            if self.errors == "ignore":
                logger.warning("Ignoring exception for value %s: %s", val, exc)
            else:
                logger.exception("Exception raised for value %s", val)
                raise
        finally:
            logger.debug("Done scraping: %d values processed", N)
            self.close()

        return results
