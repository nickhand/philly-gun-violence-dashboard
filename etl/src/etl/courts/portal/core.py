"""Scrape data from the PA Unified Judicial System portal using Playwright."""

import time
from dataclasses import dataclass, field
from typing import Any, Literal, Self

import tenacity
from justhtml import JustHTML
from loguru import logger
from playwright.sync_api import Browser, Page, Playwright, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from etl.courts.portal.schema import PortalResult

__all__ = ["UJSPortalScraper"]

PORTAL_BASE_URL = "https://ujsportal.pacourts.us"
PORTAL_URL = f"{PORTAL_BASE_URL}/CaseSearch"
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


def _has_class(node: Any, class_name: str) -> bool:
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


def _parse_results(html: str) -> list[PortalResult] | None:
    """
    Parse the portal search results table into structured records.

    Parameters
    ----------
    html : str
        HTML content of the results page.

    Returns
    -------
    list[PortalResult] or None
        Parsed results, or None if no data rows were found.
    """
    # Parse the HTML and find the results table
    doc = JustHTML(html)
    tables = doc.query(RESULTS_CONTAINER)
    if not tables:
        return None

    # Extract rows and parse data
    rows = tables[0].query("tbody > tr")
    data: list[dict[str, Any]] = []
    for row in rows:
        cells = [
            td.to_text(strip=True) for td in row.query("td") if not _has_class(td, "display-none")
        ]
        if not cells:
            continue
        if len(cells) < len(RESULT_FIELDS):
            continue

        record = dict(zip(RESULT_FIELDS, cells[: len(RESULT_FIELDS)], strict=True))
        links = [a.attrs.get("href") for a in row.query("a") if a.attrs and a.attrs.get("href")]
        if len(links) >= 2:
            record["court_summary_url"] = f"{PORTAL_BASE_URL}{links[-1]}"
            record["docket_sheet_url"] = f"{PORTAL_BASE_URL}{links[-2]}"
        data.append(record)

    if not data:
        return None

    return [PortalResult.model_validate(record) for record in data]


@dataclass
class UJSPortalScraper:
    """Scrape the UJS courts portal by incident number or docket number.

    Attributes
    ----------
    search_by : str
        The type of input to search by; either "Incident Number" or "Docket Number".
    debug : bool
        If ``True``, run Playwright in debug mode.
    log_freq : int
        Frequency of logging progress during batch scrapes.
    sleep : float
        Seconds to sleep between requests.
    timeout_ms : int
        Timeout for page loads and waits, in milliseconds.
    max_attempts : int
        Maximum number of retry attempts for each input.
    wait_min : float
        Minimum wait time between retries, in seconds.
    wait_max : float
        Maximum wait time between retries, in seconds.
    errors : str
        Error handling strategy; either "raise" or "ignore".
    """

    search_by: Literal["Incident Number", "Docket Number"] = "Incident Number"
    debug: bool = False
    log_freq: int = 50
    sleep: float = 7.0
    timeout_ms: int = 12_000
    max_attempts: int = 8
    wait_min: float = 5.0
    wait_max: float = 30.0
    errors: Literal["raise", "ignore"] = "raise"

    _playwright: Playwright | None = field(init=False, default=None)
    _browser: Browser | None = field(init=False, default=None)
    _page: Page | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        """Validate configuration and build the retry strategy."""
        if self.search_by not in SEARCH_BY_OPTIONS:
            raise ValueError(f"search_by must be one of {SEARCH_BY_OPTIONS}")

        # Build the retryer
        self._retryer = Retrying(
            stop=stop_after_attempt(self.max_attempts),
            wait=wait_random_exponential(multiplier=self.wait_min, max=self.wait_max),
            retry=retry_if_exception_type(Exception),
            reraise=True,
            before_sleep=self._before_retry,
        )

    def _before_retry(self, retry_state: "tenacity.RetryCallState") -> None:
        """
        Reset the page and back off before a retry.

        Parameters
        ----------
        retry_state : tenacity.RetryCallState
            State containing attempt info and exception.
        """
        input_value = retry_state.args[0] if retry_state.args else "unknown"
        attempt = retry_state.attempt_number
        outcome = retry_state.outcome

        # Build the message and log a warning
        msg = (
            f"Retrying portal scrape for {input_value} "
            f"(attempt {attempt}/{self.max_attempts}) due to: "
        )
        if outcome is not None and outcome.exception() is not None:
            msg += f"{outcome.exception()}"
        logger.warning(msg)

        # Reset the page and sleep before retrying
        self._reset_page()
        time.sleep(self.sleep)

    def __enter__(self) -> Self:
        self._ensure_page()
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _ensure_page(self) -> Page:
        """Lazily start Playwright and navigate to the portal."""
        # Return existing page if already initialized
        if self._page is not None:
            return self._page

        # Initialize Playwright
        self._playwright = sync_playwright().start()

        # Launch browser and navigate to portal
        self._browser = self._playwright.chromium.launch(headless=not self.debug)
        self._page = self._browser.new_page()
        self._page.goto(PORTAL_URL, wait_until="networkidle", timeout=self.timeout_ms)

        # Set search type
        self._page.select_option(SEARCH_BY_DROPDOWN, label=self.search_by)

        # Return the initialized page
        return self._page

    def _reset_page(self) -> None:
        """Close Playwright objects and reset handles."""
        # Close resources if they exist
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
        """Close Playwright resources."""
        self._reset_page()

    def _normalize_input(self, input_value: str) -> str | None:
        """
        Normalize an input value for the selected search type.

        Ensure the incident number is exactly 10 digits.

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

    def _scrape_once(self, input_value: str) -> list[PortalResult] | None:
        """
        Perform a single scrape attempt for one input value.

        Parameters
        ----------
        input_value : str
            Incident or docket number.

        Returns
        -------
        list[PortalResult] or None
            Parsed results or None when validation/parsing fails.
        """
        # Normalize the input value
        normalized = self._normalize_input(input_value)
        if normalized is None:
            return None

        # Ensure page is ready
        page = self._ensure_page()

        # Fill in the form and submit
        search_by_tag = self.search_by.replace(" ", "")
        input_selector = f"#{search_by_tag}-Control input"

        # Clear any existing input, fill in the new value, and submit
        page.fill(input_selector, "")
        page.fill(input_selector, normalized)
        page.click(SEARCH_BUTTON)

        # Wait for results to load
        try:
            page.wait_for_selector(RESULTS_CONTAINER, timeout=self.timeout_ms, state="visible")
        except PlaywrightTimeoutError as exc:
            raise ValueError("Portal results did not load in time") from exc

        # Get the page content and parse results
        html = page.content()
        return _parse_results(html)

    def __call__(self, input_value: str) -> list[PortalResult] | None:
        """
        Scrape portal results for a single input with retries.

        Parameters
        ----------
        input_value : str
            Incident or docket number.

        Returns
        -------
        list[PortalResult] or None
            Parsed results or None if validation/parsing fails.
        """
        # Scrape results, retrying on failure according to the retry strategy
        for attempt in self._retryer:
            with attempt:
                return self._scrape_once(input_value)

        return None

    def scrape_portal_data(self, input_values: list[str]) -> list[PortalResult]:
        """
        Scrape portal data for a list of input values.

        Parameters
        ----------
        input_values : list[str]
            Values to query (incident or docket numbers).

        Returns
        -------
        list[PortalResult]
            Flattened list of result dictionaries.
        """
        results: list[PortalResult] = []
        N = len(input_values)
        logger.info(f"Scraping info for {N} values")

        try:
            for i, val in enumerate(input_values):
                if i % self.log_freq == 0:
                    logger.debug(f"Scraping index {i}")
                portal_results = self(val)
                if portal_results is None:
                    continue
                results.extend(portal_results)
                time.sleep(self.sleep)
        except Exception as exc:
            if self.errors == "ignore":
                logger.warning(f"Ignoring exception for value {val}: {exc}")
            else:
                logger.exception(f"Exception raised for value {val}: {exc}")
                raise
        finally:
            logger.debug(f"Done scraping: {N} values processed")
            self.close()

        return results
