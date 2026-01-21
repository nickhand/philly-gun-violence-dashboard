"""Tenacity-integrated scraper with verification-grade audit logging.

This module provides a verification-aware scraper that:
- Classifies every attempt into defined buckets
- Logs audit records for each attempt and final outcome
- Only retries retryable classifications (never ZERO_RESULTS)
- Captures screenshots for non-HAS_RESULTS outcomes
"""

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Self

from justhtml import JustHTML
from loguru import logger
from playwright.sync_api import Browser, Page, Playwright, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from etl.courts.scraper.schema import PortalResult
from etl.courts.verification.audit import AttemptTracker, AuditWriter, create_audit_writer
from etl.courts.verification.classifier import (
    Classification,
    ClassificationResult,
    classify_case_search,
    classify_from_exception,
)
from etl.courts.verification.config import (
    PORTAL_BASE_URL,
    PORTAL_URL,
    RESULTS_CONTAINER_SELECTOR,
    ScraperConfig,
    get_scraper_config,
)
from etl.courts.verification.net_observer import NetworkObserver
from etl.courts.verification.shard import AuditContext, get_audit_context, normalize_incident_number

__all__ = ["VerifiedUJSPortalScraper", "RetryableScrapeError"]

# Selectors used in the portal UI
SEARCH_BY_DROPDOWN = "#SearchBy-Control select"
SEARCH_BUTTON = "#btnSearch"

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
    """Exception raised for retryable scrape outcomes.

    This exception carries the ClassificationResult so tenacity hooks
    can access classification details.

    Attributes
    ----------
    result : ClassificationResult
        The classification result that triggered the retry.
    """

    def __init__(self, result: ClassificationResult) -> None:
        self.result = result
        super().__init__(f"Retryable scrape error: {result.classification.value}")


def _has_class(node: Any, class_name: str) -> bool:
    """Check whether a JustHTML node has a given CSS class."""
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
    """Parse the portal search results table into structured records.

    Parameters
    ----------
    html : str
        HTML content of the results page.

    Returns
    -------
    list[PortalResult] or None
        Parsed results, or None if no data rows were found.
    """
    doc = JustHTML(html)
    tables = doc.query(RESULTS_CONTAINER_SELECTOR)
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
class VerifiedUJSPortalScraper:
    """Scrape the UJS courts portal with verification-grade audit logging.

    This scraper integrates:
    - Response classification for every attempt
    - Network observation for HTTP status tracking
    - Audit logging (attempts + final)
    - Tenacity-based retry with observability hooks
    - Optional screenshot capture

    Attributes
    ----------
    search_by : str
        Search type ("Incident Number" or "Docket Number").
    config : ScraperConfig
        Scraper configuration.
    audit_context : AuditContext
        Shard context for parallel runs.
    audit_writer : AuditWriter | None
        Audit log writer (auto-created if None).
    """

    search_by: Literal["Incident Number", "Docket Number"] = "Incident Number"
    config: ScraperConfig = field(default_factory=get_scraper_config)
    audit_context: AuditContext = field(default_factory=get_audit_context)
    audit_writer: AuditWriter | None = None

    _playwright: Playwright | None = field(init=False, default=None)
    _browser: Browser | None = field(init=False, default=None)
    _page: Page | None = field(init=False, default=None)
    _net_observer: NetworkObserver = field(init=False, default_factory=NetworkObserver)

    # Tracking for current incident number
    _current_tracker: AttemptTracker | None = field(init=False, default=None)
    _current_attempt_start: str | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        """Initialize audit writer and retry strategy."""
        if self.search_by not in {"Incident Number", "Docket Number"}:
            raise ValueError("search_by must be 'Incident Number' or 'Docket Number'")

        # Create audit writer if not provided
        if self.audit_writer is None:
            self.audit_writer = create_audit_writer(
                self.audit_context,
                compress=self.config.compress_audit_logs,
            )

        # Build tenacity retryer
        self._retryer = Retrying(
            stop=stop_after_attempt(self.config.max_attempts),
            wait=wait_random_exponential(
                multiplier=self.config.backoff_base_s,
                max=self.config.backoff_max_s,
            ),
            retry=retry_if_exception_type(RetryableScrapeError),
            reraise=False,
            before=self._before_attempt,
            after=self._after_attempt,
            before_sleep=self._before_sleep,
            retry_error_callback=self._on_retry_exhausted,
        )

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
        self._browser = self._playwright.chromium.launch(headless=not self.config.debug)
        self._page = self._browser.new_page()

        # Attach network observer
        self._net_observer.attach(self._page)

        # Navigate to portal
        self._page.goto(
            PORTAL_URL,
            wait_until="networkidle",
            timeout=self.config.navigation_timeout_ms,
        )

        # Set search type
        self._page.select_option(SEARCH_BY_DROPDOWN, label=self.search_by)

        return self._page

    def _reset_page(self) -> None:
        """Close Playwright objects and reset handles."""
        try:
            if self._page:
                self._net_observer.detach(self._page)
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
        """Close all resources."""
        self._reset_page()
        if self.audit_writer:
            self.audit_writer.close()

    def _before_attempt(self, retry_state: RetryCallState) -> None:
        """Reset network observer before each attempt."""
        self._net_observer.reset()
        self._current_attempt_start = datetime.now(UTC).isoformat()

    def _after_attempt(self, retry_state: RetryCallState) -> None:
        """Log the attempt audit record after each attempt."""
        # This is handled in _scrape_once_with_classification to capture
        # the classification result properly
        pass

    def _before_sleep(self, retry_state: RetryCallState) -> None:
        """Sleep between retries with exponential backoff."""
        attempt = retry_state.attempt_number
        sleep_time = retry_state.next_action.sleep if retry_state.next_action else 0

        outcome = retry_state.outcome
        if outcome is not None and outcome.exception() is not None:
            exc = outcome.exception()
            if isinstance(exc, RetryableScrapeError):
                logger.warning(
                    f"Retrying after {exc.result.classification.value} "
                    f"(attempt {attempt}/{self.config.max_attempts}), "
                    f"sleeping {sleep_time:.1f}s"
                )

        # Reset the page before retry
        self._reset_page()
        time.sleep(self.config.sleep_between_requests_s)

    def _on_retry_exhausted(self, retry_state: RetryCallState) -> ClassificationResult | None:
        """Return the last classification result when all retries are exhausted."""
        outcome = retry_state.outcome
        if outcome is not None and outcome.exception() is not None:
            exc = outcome.exception()
            if isinstance(exc, RetryableScrapeError):
                return exc.result
        return None

    def _capture_screenshot(self, incident_number: str, attempt_index: int) -> str | None:
        """Capture a screenshot if enabled.

        Parameters
        ----------
        incident_number : str
            Normalized incident number.
        attempt_index : int
            Attempt number.

        Returns
        -------
        str | None
            Path to screenshot or None if not captured.
        """
        if not self.config.enable_screenshots or self._page is None:
            return None

        if self.audit_writer is None:
            return None

        try:
            screenshot_path = self.audit_writer.get_screenshot_path(incident_number, attempt_index)
            self._page.screenshot(path=screenshot_path, full_page=True)
            return str(screenshot_path)
        except Exception as e:
            logger.debug(f"Failed to capture screenshot: {e}")
            return None

    def _scrape_once_with_classification(
        self,
        input_value: str,
        attempt_index: int,
    ) -> tuple[ClassificationResult, list[PortalResult] | None]:
        """Perform a single scrape attempt with classification.

        Parameters
        ----------
        input_value : str
            Raw incident/docket number.
        attempt_index : int
            Attempt number (1-based).

        Returns
        -------
        tuple[ClassificationResult, list[PortalResult] | None]
            Classification result and parsed portal results (if HAS_RESULTS).

        Raises
        ------
        RetryableScrapeError
            If the classification is retryable.
        """
        normalized = normalize_incident_number(input_value)
        timestamp_start = self._current_attempt_start or datetime.now(UTC).isoformat()

        page = self._ensure_page()
        start_time = time.perf_counter()

        portal_results: list[PortalResult] | None = None
        result: ClassificationResult

        try:
            # Fill in the form and submit
            search_by_tag = self.search_by.replace(" ", "")
            input_selector = f"#{search_by_tag}-Control input"

            page.fill(input_selector, "")
            page.fill(input_selector, normalized)
            page.click(SEARCH_BUTTON)

            # Wait briefly for initial response
            time.sleep(0.5)

            # Classify the result
            result = classify_case_search(
                page,
                self._net_observer,
                results_wait_timeout_ms=self.config.results_wait_timeout_ms,
            )

            # If HAS_RESULTS, parse the actual results
            if result.classification == Classification.HAS_RESULTS:
                try:
                    html = page.content()
                    portal_results = _parse_results(html)
                except Exception as e:
                    logger.debug(f"Failed to parse results: {e}")

        except PlaywrightTimeoutError as e:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            result = classify_from_exception(
                e, page.url if page else "", self._net_observer, elapsed_ms
            )
        except Exception as e:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            result = classify_from_exception(
                e, page.url if self._page else "", self._net_observer, elapsed_ms
            )

        timestamp_end = datetime.now(UTC).isoformat()

        # Determine if we will retry
        will_retry = result.is_retryable and attempt_index < self.config.max_attempts

        # Capture screenshot for non-success outcomes
        screenshot_path: str | None = None
        if result.classification != Classification.HAS_RESULTS:
            screenshot_path = self._capture_screenshot(normalized, attempt_index)

        # Calculate sleep time for audit log
        sleep_s: float | None = None
        if will_retry:
            # Estimate next sleep time (tenacity calculates actual value)
            sleep_s = min(
                self.config.backoff_base_s * (2 ** (attempt_index - 1)),
                self.config.backoff_max_s,
            )

        # Record attempt
        if self._current_tracker is not None and self.audit_writer is not None:
            attempt_row = self._current_tracker.add_attempt(
                result=result,
                attempt_index=attempt_index,
                timestamp_start=timestamp_start,
                timestamp_end=timestamp_end,
                will_retry=will_retry,
                sleep_s=sleep_s,
                screenshot_path=screenshot_path,
            )
            self.audit_writer.write_attempt(attempt_row)

        # Raise RetryableScrapeError for retryable classifications
        if result.is_retryable:
            raise RetryableScrapeError(result)

        return result, portal_results

    def __call__(
        self,
        input_value: str,
    ) -> tuple[ClassificationResult, list[PortalResult] | None]:
        """Scrape portal results for a single input with retries and audit logging.

        Parameters
        ----------
        input_value : str
            Incident or docket number.

        Returns
        -------
        tuple[ClassificationResult, list[PortalResult] | None]
            Final classification and parsed results (if HAS_RESULTS).
        """
        normalized = normalize_incident_number(input_value)

        # Initialize tracker for this incident number
        self._current_tracker = AttemptTracker(
            audit_context=self.audit_context,
            incident_number_raw=input_value,
            incident_number_normalized=normalized,
        )

        final_result: ClassificationResult | None = None
        portal_results: list[PortalResult] | None = None

        # Run with retries
        for attempt_index, attempt in enumerate(self._retryer, start=1):
            with attempt:
                final_result, portal_results = self._scrape_once_with_classification(
                    input_value, attempt_index
                )

        # Check if retries exhausted (retry_error_callback was called)
        if (
            final_result is None
            and self._retryer.statistics.get("attempt_number")
            and self._current_tracker
            and self._current_tracker.attempts
        ):
            last_attempt = self._current_tracker.attempts[-1]
            final_result = ClassificationResult(
                classification=Classification(last_attempt.classification),
                subreason=last_attempt.subreason,
                row_count=last_attempt.row_count,
                final_url=last_attempt.final_url,
                marker_hits=last_attempt.marker_hits,
                status_histogram=last_attempt.status_histogram,
                requestfailed_count=last_attempt.requestfailed_count,
                elapsed_ms=last_attempt.elapsed_ms,
                error_message=last_attempt.error_message,
            )

        # Build and write final audit row
        if self._current_tracker and self.audit_writer:
            try:
                final_row = self._current_tracker.build_final_row()
                self.audit_writer.write_final(final_row)
            except Exception as e:
                logger.warning(f"Failed to write final audit row: {e}")

        # Ensure we have a result
        if final_result is None:
            final_result = ClassificationResult(
                classification=Classification.UI_DRIFT_OR_UNKNOWN,
                subreason="No result after all attempts",
                final_url="",
            )

        return final_result, portal_results

    def scrape_portal_data(
        self,
        input_values: list[str],
    ) -> tuple[dict[str, list[PortalResult] | None], dict[str, ClassificationResult]]:
        """Scrape portal data for a list of input values.

        Parameters
        ----------
        input_values : list[str]
            Values to query (incident or docket numbers).

        Returns
        -------
        tuple[dict[str, list[PortalResult] | None], dict[str, ClassificationResult]]
            (results_dict, classifications_dict)
        """
        results: dict[str, list[PortalResult] | None] = {}
        classifications: dict[str, ClassificationResult] = {}
        N = len(input_values)

        logger.info(f"Scraping info for {N} values (shard {self.audit_context.shard_id})")

        for i, val in enumerate(input_values):
            # Log progress
            if i % self.config.log_freq == 0:
                logger.debug(f"Scraping index {i}/{N}")

            try:
                classification, portal_results = self(val)
                results[val] = portal_results
                classifications[val] = classification
            except Exception as exc:
                logger.exception(f"Unexpected exception for value {val}: {exc}")
                results[val] = None
                classifications[val] = ClassificationResult(
                    classification=Classification.NETWORK_OR_SERVER_ERROR,
                    subreason=f"Unexpected exception: {type(exc).__name__}",
                    error_message=str(exc),
                )

            # Sleep between requests
            time.sleep(self.config.sleep_between_requests_s)

        logger.info(f"Done scraping: {N} values processed")
        return results, classifications
