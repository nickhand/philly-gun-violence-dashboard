"""Scrape data from the PA Unified Judicial System portal using Playwright."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Self

import tenacity
from justhtml import JustHTML
from loguru import logger
from playwright.sync_api import Browser, Page, Playwright, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from etl.courts.scraper.classifier import (
    Classification,
    ClassificationResult,
    classify_case_search,
    classify_from_exception,
)
from etl.courts.scraper.schema import OutcomeStatus, PortalResult, ScrapeOutcome, SoftBlocked

if TYPE_CHECKING:
    from etl.courts.scraper.net_observer import NetworkObserver

__all__ = ["UJSPortalScraper", "RetryableScrapeError"]

PORTAL_BASE_URL = "https://ujsportal.pacourts.us"
PORTAL_URL = f"{PORTAL_BASE_URL}/CaseSearch"
SEARCH_BY_OPTIONS = {"Incident Number", "Docket Number"}

# Longer timeout for cold browser launch + initial page load vs. live scraping ops.
# After _reset_page(), Chromium restarts and the portal's React app renders from scratch —
# that legitimately takes longer than a form fill or results wait.
_NAV_TIMEOUT_MS = 30_000

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


class RetryableScrapeError(Exception):
    """Carries ClassificationResult so tenacity hooks can access classification details."""

    def __init__(self, result: ClassificationResult) -> None:
        self.result = result
        super().__init__(f"Retryable scrape error: {result.classification.value}")


def _has_class(node: Any, class_name: str) -> bool:
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
    """Parse the portal search results table into structured records."""
    doc = JustHTML(html)
    tables = doc.query(RESULTS_CONTAINER)
    if not tables:
        return None

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
    timeout_ms : int
        Timeout for page loads and waits, in milliseconds.
    max_attempts : int
        Maximum number of retry attempts for each input.
        SOFT_BLOCKED is capped at 1 retry regardless of this value.
    wait_min : float
        Minimum wait time between retries, in seconds.
    wait_max : float
        Maximum wait time between retries, in seconds.
    errors : str
        Error handling strategy; either "raise" or "ignore".
    """

    search_by: Literal["Incident Number", "Docket Number"] = "Incident Number"
    debug: bool = False
    timeout_ms: int = 20_000
    max_attempts: int = 5
    wait_min: float = 5.0
    wait_max: float = 30.0
    errors: Literal["raise", "ignore"] = "raise"

    _playwright: Playwright | None = field(init=False, default=None)
    _browser: Browser | None = field(init=False, default=None)
    _page: Page | None = field(init=False, default=None)
    _net_observer: NetworkObserver | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        if self.search_by not in SEARCH_BY_OPTIONS:
            raise ValueError(f"search_by must be one of {SEARCH_BY_OPTIONS}")

        from etl.courts.scraper.net_observer import NetworkObserver

        self._net_observer = NetworkObserver()

        self._retryer = Retrying(
            stop=stop_after_attempt(self.max_attempts),
            wait=wait_random_exponential(multiplier=self.wait_min, max=self.wait_max),
            retry=retry_if_exception_type(RetryableScrapeError),
            reraise=True,
            before=self._before_attempt,
            before_sleep=self._before_retry,
        )

    def _before_attempt(self, retry_state: tenacity.RetryCallState) -> None:
        """Reset network observer before each attempt."""
        if self._net_observer:
            self._net_observer.reset()

    def _before_retry(self, retry_state: tenacity.RetryCallState) -> None:
        """Reset page before retry. Raises SoftBlocked after 1 retry on SOFT_BLOCKED."""
        attempt = retry_state.attempt_number
        outcome = retry_state.outcome
        is_soft_blocked = False

        if outcome is not None and outcome.exception() is not None:
            exc = outcome.exception()
            if isinstance(exc, RetryableScrapeError):
                logger.warning(
                    f"Retrying after {exc.result.classification.value} "
                    f"(attempt {attempt}/{self.max_attempts})"
                )
                is_soft_blocked = exc.result.classification == Classification.SOFT_BLOCKED

        self._reset_page()

        # After 1 retry on SOFT_BLOCKED, give up in-task and let SQS redistribute
        if is_soft_blocked and attempt >= 2:
            raise SoftBlocked(f"SOFT_BLOCKED after {attempt} attempts — deferring to SQS")

    def __enter__(self) -> Self:
        self._ensure_page()
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _ensure_page(self) -> Page:
        """Lazily start Playwright and navigate to the portal."""
        if self._page is not None:
            return self._page

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=not self.debug)
        self._page = self._browser.new_page()

        if self._net_observer:
            self._net_observer.attach(self._page)

        self._page.goto(PORTAL_URL, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS)
        self._page.wait_for_selector(SEARCH_BY_DROPDOWN, state="visible", timeout=_NAV_TIMEOUT_MS)
        self._page.select_option(SEARCH_BY_DROPDOWN, label=self.search_by)

        return self._page

    def _reset_page(self) -> None:
        """Close Playwright objects and reset handles."""
        if self._net_observer and self._page:
            self._net_observer.detach(self._page)

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

    def reset(self) -> None:
        """Reset browser state before a later retry or redelivery."""
        self._reset_page()

    @property
    def page(self) -> Page | None:
        """Current Playwright page, exposed for failure screenshots."""
        return self._page

    def _normalize_input(self, input_value: str) -> str | None:
        value = str(input_value)
        if self.search_by == "Incident Number":
            if len(value) == 12:
                value = value[2:]
            if len(value) != 10:
                return None
        return value

    def _scrape_once(
        self,
        input_value: str,
        attempt_index: int,
    ) -> tuple[ClassificationResult, list[PortalResult] | None]:
        """Perform a single scrape attempt with classification.

        Raises
        ------
        RetryableScrapeError
            If the classification is retryable.
        """
        normalized = self._normalize_input(input_value)
        if normalized is None:
            invalid_result = ClassificationResult(
                classification=Classification.UI_DRIFT_OR_UNKNOWN,
                subreason="Invalid incident number format",
                final_url="",
            )
            return invalid_result, None

        start_time = time.perf_counter()

        portal_results: list[PortalResult] | None = None
        result: ClassificationResult
        page: Page | None = None

        try:
            page = self._ensure_page()
            search_by_tag = self.search_by.replace(" ", "")
            input_selector = f"#{search_by_tag}-Control input"

            page.fill(input_selector, "")
            page.fill(input_selector, normalized)
            page.click(SEARCH_BUTTON)

            result = classify_case_search(
                page,
                self._net_observer,  # type: ignore[arg-type]
                results_wait_timeout_ms=self.timeout_ms,
            )

            if result.classification == Classification.HAS_RESULTS:
                try:
                    html = page.content()
                    portal_results = _parse_results(html)

                    if portal_results is None:
                        result = ClassificationResult(
                            classification=Classification.UI_DRIFT_OR_UNKNOWN,
                            subreason="Results rows were visible but could not be parsed",
                            row_count=result.row_count,
                            final_url=result.final_url,
                            marker_hits=result.marker_hits,
                            status_histogram=result.status_histogram,
                            requestfailed_count=result.requestfailed_count,
                            elapsed_ms=result.elapsed_ms,
                            page_title=result.page_title,
                        )
                except Exception as e:
                    logger.debug(f"Failed to parse results: {e}")
                    result = ClassificationResult(
                        classification=Classification.UI_DRIFT_OR_UNKNOWN,
                        subreason=f"Failed to parse results: {type(e).__name__}",
                        row_count=result.row_count,
                        final_url=result.final_url,
                        marker_hits=result.marker_hits,
                        status_histogram=result.status_histogram,
                        requestfailed_count=result.requestfailed_count,
                        elapsed_ms=result.elapsed_ms,
                        page_title=result.page_title,
                        error_message=str(e),
                    )

        except PlaywrightTimeoutError as e:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            result = classify_from_exception(
                e,
                page.url if page else "",
                self._net_observer,
                elapsed_ms,
            )
        except Exception as e:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            result = classify_from_exception(
                e,
                page.url if page else "",
                self._net_observer,
                elapsed_ms,
            )

        if result.is_retryable:
            raise RetryableScrapeError(result)

        return result, portal_results

    def __call__(self, input_value: str) -> ScrapeOutcome:
        """Scrape portal results for a single input with retries.

        Raises
        ------
        SoftBlocked
            If SOFT_BLOCKED persists after the allowed retry budget (1 retry).
        """
        normalized = self._normalize_input(input_value)
        if normalized is None:
            return ScrapeOutcome(
                status=OutcomeStatus.INVALID_INPUT,
                classification="INVALID_INPUT",
                subreason=f"Invalid incident number format: {input_value}",
                attempt_count=0,
            )

        final_result: ClassificationResult | None = None
        portal_results: list[PortalResult] | None = None
        attempt_count = 0
        exhausted_retries = False

        try:
            for attempt_index, attempt in enumerate(self._retryer, start=1):
                attempt_count = attempt_index
                with attempt:
                    final_result, portal_results = self._scrape_once(input_value, attempt_index)
        except RetryableScrapeError as exc:
            exhausted_retries = True
            final_result = exc.result
            if self.errors == "raise":
                raise

        if final_result is None:
            final_result = ClassificationResult(
                classification=Classification.UI_DRIFT_OR_UNKNOWN,
                subreason="No result after all attempts",
                final_url="",
            )

        if exhausted_retries:
            status = OutcomeStatus.FAILED
        elif final_result.classification == Classification.HAS_RESULTS:
            status = OutcomeStatus.SUCCESS
        elif final_result.classification == Classification.ZERO_RESULTS:
            status = OutcomeStatus.NO_RESULTS
        else:
            status = OutcomeStatus.FAILED

        return ScrapeOutcome(
            status=status,
            results=portal_results,
            classification=final_result.classification.value,
            subreason=final_result.subreason,
            attempt_count=attempt_count,
        )
