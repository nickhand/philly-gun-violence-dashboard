"""Scrape data from the PA Unified Judicial System portal using Playwright."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, Self

import tenacity
from justhtml import JustHTML
from loguru import logger
from playwright.sync_api import Browser, Page, Playwright, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from etl.courts.scraper.schema import OutcomeStatus, PortalResult, ScrapeError, ScrapeOutcome

if TYPE_CHECKING:
    from etl.courts.verification.audit import AttemptTracker, AuditWriter
    from etl.courts.verification.classifier import ClassificationResult
    from etl.courts.verification.net_observer import NetworkObserver
    from etl.courts.verification.shard import AuditContext

__all__ = ["UJSPortalScraper", "RetryableScrapeError"]

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


class RetryableScrapeError(Exception):
    """Exception raised for retryable scrape outcomes when verification is enabled.

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

    Uses classification-based verification to detect rate limiting, captchas,
    and other transient errors. Results are returned as ScrapeOutcome objects
    with status, classification, and parsed results.

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
    audit_output_dir : str | None
        Directory for audit output files.
    audit_context : AuditContext | None
        Shard context for distributed scraping.
    enable_screenshots : bool
        If ``True``, capture screenshots for non-HAS_RESULTS outcomes.
    compress_audit : bool
        If ``True``, compress audit files with gzip.
    """

    search_by: Literal["Incident Number", "Docket Number"] = "Incident Number"
    debug: bool = False
    log_freq: int = 50
    sleep: float = 7.0
    timeout_ms: int = 12_000
    max_attempts: int = 5
    wait_min: float = 5.0
    wait_max: float = 30.0
    errors: Literal["raise", "ignore"] = "raise"

    # Audit options
    audit_output_dir: str | None = None
    audit_context: AuditContext | None = None
    enable_screenshots: bool = True
    compress_audit: bool = True

    # Rate limiting options
    stagger_start: bool = True  # Stagger task starts based on shard_id
    adaptive_rate_limit: bool = True  # Slow down after consecutive SOFT_BLOCKED
    soft_blocked_backoff_min: float = 60.0  # Min backoff for SOFT_BLOCKED (seconds)
    soft_blocked_backoff_max: float = 600.0  # Max backoff for SOFT_BLOCKED (10 min)

    _playwright: Playwright | None = field(init=False, default=None)
    _browser: Browser | None = field(init=False, default=None)
    _page: Page | None = field(init=False, default=None)

    # Verification mode internal state
    _net_observer: NetworkObserver | None = field(init=False, default=None)
    _audit_writer: AuditWriter | None = field(init=False, default=None)
    _current_tracker: AttemptTracker | None = field(init=False, default=None)
    _current_attempt_start: str | None = field(init=False, default=None)
    _classifications: dict[str, ClassificationResult] = field(init=False, default_factory=dict)

    # Adaptive rate limiting state
    _consecutive_soft_blocked: int = field(init=False, default=0)
    _current_sleep: float = field(init=False, default=0.0)  # Initialized in __post_init__
    _stagger_applied: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        """Validate configuration and build the retry strategy."""
        if self.search_by not in SEARCH_BY_OPTIONS:
            raise ValueError(f"search_by must be one of {SEARCH_BY_OPTIONS}")

        # Initialize adaptive rate limiting
        self._current_sleep = self.sleep
        self._consecutive_soft_blocked = 0

        # Initialize verification/audit components
        self._init_verification()

        # Build the retryer - only retry RetryableScrapeError
        self._retryer = Retrying(
            stop=stop_after_attempt(self.max_attempts),
            wait=wait_random_exponential(multiplier=self.wait_min, max=self.wait_max),
            retry=retry_if_exception_type(RetryableScrapeError),
            reraise=True,
            before=self._before_attempt,
            before_sleep=self._before_retry,
        )

    def _init_verification(self) -> None:
        """Initialize verification mode components."""
        from etl.courts.verification.audit import create_audit_writer
        from etl.courts.verification.net_observer import NetworkObserver
        from etl.courts.verification.shard import get_audit_context

        # Create network observer
        self._net_observer = NetworkObserver()

        # Get or create shard context
        if self.audit_context is None:
            self.audit_context = get_audit_context()

        # Create audit writer if output dir specified
        if self.audit_output_dir:
            self._audit_writer = create_audit_writer(
                audit_context=self.audit_context,
                base_path=self.audit_output_dir,
                compress=self.compress_audit,
            )

    def _before_attempt(self, retry_state: tenacity.RetryCallState) -> None:
        """Reset network observer before each attempt."""
        if self._net_observer:
            self._net_observer.reset()
        self._current_attempt_start = datetime.now(UTC).isoformat()

    def _before_retry(self, retry_state: tenacity.RetryCallState) -> None:
        """Log and reset before retry.

        Uses exponential backoff with jitter for SOFT_BLOCKED errors,
        scaling from soft_blocked_backoff_min to soft_blocked_backoff_max.
        Also updates adaptive rate limiting state.
        """
        import random

        from etl.courts.verification.classifier import Classification

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

        # Reset the page before retrying
        self._reset_page()

        # Apply backoff based on classification
        if is_soft_blocked:
            # Track consecutive SOFT_BLOCKED for adaptive rate limiting
            self._consecutive_soft_blocked += 1

            # Exponential backoff with jitter: base * 2^(attempt-1) capped at max
            # Example with min=60, max=600:
            #   attempt 1: 60-120s, attempt 2: 120-240s, attempt 3: 240-480s, etc.
            base_backoff = self.soft_blocked_backoff_min * (2 ** (attempt - 1))
            capped_backoff = min(base_backoff, self.soft_blocked_backoff_max)
            # Add jitter: 0.5x to 1.5x of the calculated backoff
            jitter = random.uniform(0.5, 1.5)
            backoff = capped_backoff * jitter

            logger.warning(
                f"SOFT_BLOCKED #{self._consecutive_soft_blocked}, "
                f"backing off {backoff:.0f}s (attempt {attempt})"
            )
            time.sleep(backoff)

            # Adaptive rate limiting: increase sleep between requests
            if self.adaptive_rate_limit:
                self._increase_request_delay()
        else:
            # Non-SOFT_BLOCKED retry: use normal sleep
            time.sleep(self._current_sleep)

    def _increase_request_delay(self) -> None:
        """Increase the delay between requests (adaptive rate limiting).

        Doubles the current sleep time up to 4x the original value.
        Called when consecutive SOFT_BLOCKED errors are detected.
        """
        max_sleep = self.sleep * 4  # Cap at 4x original (e.g., 7s -> 28s)
        old_sleep = self._current_sleep
        self._current_sleep = min(self._current_sleep * 2, max_sleep)
        if self._current_sleep != old_sleep:
            logger.info(
                f"Adaptive rate limit: increased request delay from {old_sleep:.1f}s "
                f"to {self._current_sleep:.1f}s"
            )

    def _reset_rate_limit_state(self) -> None:
        """Reset adaptive rate limiting state after a successful request.

        Called when a request succeeds to gradually recover request rate.
        """
        if self._consecutive_soft_blocked > 0:
            self._consecutive_soft_blocked = 0
            # Gradually decrease sleep (halve it, but not below original)
            if self._current_sleep > self.sleep:
                old_sleep = self._current_sleep
                self._current_sleep = max(self._current_sleep / 2, self.sleep)
                logger.info(
                    f"Adaptive rate limit: decreased request delay from {old_sleep:.1f}s "
                    f"to {self._current_sleep:.1f}s after success"
                )

    def _apply_staggered_start(self) -> None:
        """Apply initial delay based on shard_id to stagger task starts.

        Called once at the start of scrape_portal_data to prevent all tasks
        from hitting the portal simultaneously.
        """
        if self._stagger_applied or not self.stagger_start:
            return

        self._stagger_applied = True

        if self.audit_context is None:
            return

        import random

        shard_id = self.audit_context.shard_id
        shard_count = self.audit_context.shard_count

        # Stagger delay: each shard waits (shard_id / shard_count) * base_delay
        # Plus random jitter to avoid synchronized waves
        # Base delay: spread tasks over ~60 seconds
        base_delay = 60.0
        stagger_delay = (shard_id / shard_count) * base_delay
        jitter = random.uniform(0, 5)  # 0-5 seconds additional jitter
        total_delay = stagger_delay + jitter

        if total_delay > 0:
            logger.info(
                f"Staggered start: shard {shard_id}/{shard_count} "
                f"waiting {total_delay:.1f}s before starting"
            )
            time.sleep(total_delay)

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

        # Attach network observer
        if self._net_observer:
            self._net_observer.attach(self._page)

        self._page.goto(PORTAL_URL, wait_until="networkidle", timeout=self.timeout_ms)

        # Set search type
        self._page.select_option(SEARCH_BY_DROPDOWN, label=self.search_by)

        # Return the initialized page
        return self._page

    def _reset_page(self) -> None:
        """Close Playwright objects and reset handles."""
        # Detach network observer
        if self._net_observer and self._page:
            self._net_observer.detach(self._page)

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
        """Close Playwright resources and audit writer."""
        self._reset_page()
        if self._audit_writer:
            self._audit_writer.close()

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

    def _capture_screenshot(self, incident_number: str, attempt_index: int) -> str | None:
        """Capture a screenshot if enabled (verification mode).

        Parameters
        ----------
        incident_number : str
            Normalized incident number.
        attempt_index : int
            Attempt number.

        Returns
        -------
        str | None
            S3 path to screenshot or None if not captured.
        """
        if not self.enable_screenshots or self._page is None:
            return None

        if self._audit_writer is None:
            return None

        try:
            screenshot_path = self._audit_writer.get_screenshot_path(incident_number, attempt_index)
            self._page.screenshot(path=screenshot_path, full_page=True)
            # Return S3 path (will be local path if not S3 destination)
            return self._audit_writer.local_to_s3_path(screenshot_path)
        except Exception as e:
            logger.debug(f"Failed to capture screenshot: {e}")
            return None

    def _capture_error_screenshot(self, input_value: str) -> str | None:
        """Capture a screenshot for an error (verification mode).

        Parameters
        ----------
        input_value : str
            Input value that caused the error.

        Returns
        -------
        str | None
            S3 path to screenshot or None if not captured.
        """
        if not self.enable_screenshots or self._page is None:
            return None

        if self._audit_writer is None:
            return None

        try:
            screenshot_path = self._audit_writer.get_error_screenshot_path(input_value)
            self._page.screenshot(path=screenshot_path, full_page=True)
            # Return S3 path (will be local path if not S3 destination)
            return self._audit_writer.local_to_s3_path(screenshot_path)
        except Exception as e:
            logger.debug(f"Failed to capture error screenshot: {e}")
            return None

    def _scrape_once(
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
        from etl.courts.verification.classifier import (
            Classification,
            ClassificationResult,
            classify_case_search,
            classify_from_exception,
        )

        normalized = self._normalize_input(input_value)
        if normalized is None:
            # Invalid input - return UI_DRIFT classification
            from etl.courts.verification.classifier import ClassificationResult

            invalid_result = ClassificationResult(
                classification=Classification.UI_DRIFT_OR_UNKNOWN,
                subreason="Invalid incident number format",
                final_url="",
            )
            return invalid_result, None

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
                self._net_observer,  # type: ignore[arg-type]
                results_wait_timeout_ms=self.timeout_ms,
            )

            # If HAS_RESULTS, parse the actual results
            if result.classification == Classification.HAS_RESULTS:
                try:
                    html = page.content()
                    portal_results = _parse_results(html)

                    # Reclassify to ZERO_RESULTS if classifier detected rows but
                    # parser found no valid data (e.g., "No results found" row)
                    if portal_results is None:
                        result = ClassificationResult(
                            classification=Classification.ZERO_RESULTS,
                            subreason="Results container visible but no parseable data rows",
                            row_count=0,
                            final_url=result.final_url,
                            marker_hits=result.marker_hits,
                            status_histogram=result.status_histogram,
                            requestfailed_count=result.requestfailed_count,
                            elapsed_ms=result.elapsed_ms,
                            page_title=result.page_title,
                        )
                except Exception as e:
                    logger.debug(f"Failed to parse results: {e}")

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
                page.url if self._page else "",
                self._net_observer,
                elapsed_ms,
            )

        timestamp_end = datetime.now(UTC).isoformat()

        # Determine if we will retry
        will_retry = result.is_retryable and attempt_index < self.max_attempts

        # Capture screenshot for non-success outcomes
        screenshot_path: str | None = None
        if result.classification != Classification.HAS_RESULTS:
            screenshot_path = self._capture_screenshot(normalized, attempt_index)

        # Calculate sleep time for audit log
        sleep_s: float | None = None
        if will_retry:
            sleep_s = min(self.wait_min * (2 ** (attempt_index - 1)), self.wait_max)

        # Record attempt
        if self._current_tracker is not None and self._audit_writer is not None:
            attempt_row = self._current_tracker.add_attempt(
                result=result,
                attempt_index=attempt_index,
                timestamp_start=timestamp_start,
                timestamp_end=timestamp_end,
                will_retry=will_retry,
                sleep_s=sleep_s,
                screenshot_path=screenshot_path,
            )
            self._audit_writer.write_attempt(attempt_row)

        # Raise RetryableScrapeError for retryable classifications
        if result.is_retryable:
            raise RetryableScrapeError(result)

        return result, portal_results

    def __call__(self, input_value: str) -> ScrapeOutcome:
        """Scrape portal results for a single input with retries.

        Parameters
        ----------
        input_value : str
            Incident or docket number.

        Returns
        -------
        ScrapeOutcome
            Outcome with status, classification, and results (if any).
        """
        from etl.courts.verification.audit import AttemptTracker
        from etl.courts.verification.classifier import Classification, ClassificationResult

        normalized = self._normalize_input(input_value)
        if normalized is None:
            # Invalid input format
            return ScrapeOutcome(
                status=OutcomeStatus.INVALID_INPUT,
                classification="INVALID_INPUT",
                subreason=f"Invalid incident number format: {input_value}",
                attempt_count=0,
            )

        # Initialize tracker for this incident number
        self._current_tracker = AttemptTracker(
            audit_context=self.audit_context,
            incident_number_raw=input_value,
            incident_number_normalized=normalized,
        )

        final_result: ClassificationResult | None = None
        portal_results: list[PortalResult] | None = None
        attempt_count = 0
        exhausted_retries = False

        # Run with retries - catch exhausted retries to allow audit finalization
        try:
            for attempt_index, attempt in enumerate(self._retryer, start=1):
                attempt_count = attempt_index
                with attempt:
                    final_result, portal_results = self._scrape_once(input_value, attempt_index)
        except RetryableScrapeError:
            # Retries exhausted with a retryable error - extract final result
            exhausted_retries = True
            if self._current_tracker and self._current_tracker.attempts:
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
            # Re-raise if errors='raise' mode
            if self.errors == "raise":
                raise

        # Build and write final audit row
        if self._current_tracker and self._audit_writer:
            try:
                final_row = self._current_tracker.build_final_row()
                self._audit_writer.write_final(final_row)
            except Exception as e:
                logger.warning(f"Failed to write final audit row: {e}")

        # Ensure we have a result
        if final_result is None:
            final_result = ClassificationResult(
                classification=Classification.UI_DRIFT_OR_UNKNOWN,
                subreason="No result after all attempts",
                final_url="",
            )

        # Store classification
        self._classifications[normalized] = final_result

        # Map classification to outcome status
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

    @property
    def classifications(self) -> dict[str, ClassificationResult]:
        """Return collected classifications (verification mode only).

        Returns
        -------
        dict[str, ClassificationResult]
            Dictionary mapping normalized incident numbers to classification results.
        """
        return self._classifications

    def scrape_portal_data(
        self,
        input_values: list[str],
    ) -> tuple[dict[str, ScrapeOutcome], list[ScrapeError]]:
        """
        Scrape portal data for a list of input values.

        Parameters
        ----------
        input_values : list[str]
            Values to query (incident or docket numbers).

        Returns
        -------
        tuple[dict[str, ScrapeOutcome], list[ScrapeError]]
            Tuple of (results dict, error list).

            - Results dict maps input values to ScrapeOutcome objects
            - ScrapeOutcome.status distinguishes SUCCESS, NO_RESULTS, FAILED, INVALID_INPUT
            - ScrapeOutcome.results contains the parsed data (if SUCCESS)

        Notes
        -----
        Classifications for each input are stored in ``self.classifications``
        and audit logs are written to the output directory.
        """
        results: dict[str, ScrapeOutcome] = {}
        N = len(input_values)
        logger.info(f"Scraping info for {N} values")

        # Clear classifications for fresh run
        self._classifications.clear()

        # Apply staggered start to avoid thundering herd
        self._apply_staggered_start()

        # Errors with rich context
        errors: list[ScrapeError] = []

        # Wrap in try/finally to ensure audit files are saved even on crash
        try:
            # Loop over input values and scrape
            for i, val in enumerate(input_values):
                # Log progress
                if i % self.log_freq == 0:
                    logger.debug(f"Scraping index {i}")

                # Try to scrape the value, with retry/error handling
                try:
                    outcome = self(val)
                    results[val] = outcome
                    # Only reset rate limit state on SUCCESS or NO_RESULTS
                    if outcome.status in (OutcomeStatus.SUCCESS, OutcomeStatus.NO_RESULTS):
                        self._reset_rate_limit_state()
                except Exception as exc:
                    # Capture error screenshot
                    screenshot_path = self._capture_error_screenshot(val)

                    # Capture rich error info
                    error_record = ScrapeError(
                        input_value=val,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                        timestamp=datetime.now(UTC),
                        attempt_count=self.max_attempts,  # Failed after all retries
                        screenshot_path=screenshot_path,
                    )
                    errors.append(error_record)

                    # If ignoring errors, log a warning and continue
                    if self.errors == "ignore":
                        logger.warning(f"Ignoring exception for value {val}: {exc}")
                        # Create a failed outcome for tracking
                        results[val] = ScrapeOutcome(
                            status=OutcomeStatus.FAILED,
                            classification="EXCEPTION",
                            subreason=str(exc),
                            attempt_count=self.max_attempts,
                        )
                    # Otherwise, re-raise the exception
                    else:
                        logger.exception(f"Exception raised for value {val}: {exc}")
                        raise

                # Sleep between requests (uses adaptive rate if enabled)
                time.sleep(self._current_sleep)

            # Log classification summary
            if self._classifications:
                self._log_classification_summary()

            # We are all done
            logger.debug(f"Done scraping: {N} values processed")
        finally:
            # Always close to ensure audit files are uploaded (even on crash)
            self.close()

        return results, errors

    def _log_classification_summary(self) -> None:
        """Log a summary of classifications (verification mode)."""
        from collections import Counter

        counts = Counter(r.classification.value for r in self._classifications.values())
        total = sum(counts.values())
        logger.info(f"Classification summary ({total} total):")
        for classification, count in sorted(counts.items()):
            pct = (count / total) * 100 if total > 0 else 0
            logger.info(f"  {classification}: {count} ({pct:.1f}%)")
