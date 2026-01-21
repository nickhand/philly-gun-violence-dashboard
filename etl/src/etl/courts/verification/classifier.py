"""Response classification for UJS CaseSearch scraper.

Classifies each scrape attempt into one of six buckets:
- HAS_RESULTS: Results UI rendered with >= 1 row
- ZERO_RESULTS: Results UI rendered with explicit "no results" indicator
- SOFT_BLOCKED: Denied/interstitial/captcha/403/429 patterns
- REDIRECTED_OR_SESSION_LOST: Bounced to search start or session expired
- NETWORK_OR_SERVER_ERROR: Timeouts, DNS errors, 5xx responses
- UI_DRIFT_OR_UNKNOWN: Page loaded but expected anchors not found
"""

import contextlib
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from loguru import logger
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from etl.courts.verification.config import (
    BLOCKED_MARKERS,
    NO_RESULTS_TEXT_MARKERS,
    PORTAL_URL,
    REDIRECT_URL_PATTERNS,
    RESULTS_CONTAINER_SELECTOR,
    RESULTS_ROW_SELECTOR,
    SERVER_ERROR_STATUS_CODES,
    SESSION_LOST_MARKERS,
    SOFT_BLOCKED_STATUS_CODES,
)
from etl.courts.verification.net_observer import NetworkObserver

if TYPE_CHECKING:
    pass


class Classification(str, Enum):
    """Classification buckets for scrape attempts."""

    HAS_RESULTS = "HAS_RESULTS"
    ZERO_RESULTS = "ZERO_RESULTS"
    SOFT_BLOCKED = "SOFT_BLOCKED"
    REDIRECTED_OR_SESSION_LOST = "REDIRECTED_OR_SESSION_LOST"
    NETWORK_OR_SERVER_ERROR = "NETWORK_OR_SERVER_ERROR"
    UI_DRIFT_OR_UNKNOWN = "UI_DRIFT_OR_UNKNOWN"


# Classifications that should NOT trigger retries
NON_RETRYABLE_CLASSIFICATIONS = {
    Classification.HAS_RESULTS,
    Classification.ZERO_RESULTS,
}

# Classifications that ARE retryable
RETRYABLE_CLASSIFICATIONS = {
    Classification.SOFT_BLOCKED,
    Classification.REDIRECTED_OR_SESSION_LOST,
    Classification.NETWORK_OR_SERVER_ERROR,
    Classification.UI_DRIFT_OR_UNKNOWN,  # One retry allowed
}


@dataclass
class ClassificationResult:
    """Result of classifying a scrape attempt.

    Attributes
    ----------
    classification : Classification
        The classification bucket.
    subreason : str | None
        Additional detail about the classification.
    row_count : int | None
        Number of result rows found (for HAS_RESULTS).
    final_url : str
        The final URL after navigation.
    marker_hits : dict[str, bool]
        Which detection markers were triggered.
    status_histogram : dict[int, int]
        HTTP status code counts from network observer.
    requestfailed_count : int
        Number of failed requests.
    elapsed_ms : int
        Time taken for the classification (milliseconds).
    page_title : str | None
        Page title at time of classification.
    error_message : str | None
        Error message if an exception occurred.
    """

    classification: Classification
    subreason: str | None = None
    row_count: int | None = None
    final_url: str = ""
    marker_hits: dict[str, bool] | None = None
    status_histogram: dict[int, int] | None = None
    requestfailed_count: int = 0
    elapsed_ms: int = 0
    page_title: str | None = None
    error_message: str | None = None

    @property
    def is_retryable(self) -> bool:
        """Check if this classification should trigger a retry."""
        return self.classification in RETRYABLE_CLASSIFICATIONS

    @property
    def is_success(self) -> bool:
        """Check if this classification is a terminal success."""
        return self.classification in {Classification.HAS_RESULTS, Classification.ZERO_RESULTS}

    def to_dict(self) -> dict:
        """Convert to a JSON-serializable dictionary."""
        return {
            "classification": self.classification.value,
            "subreason": self.subreason,
            "row_count": self.row_count,
            "final_url": self.final_url,
            "marker_hits": self.marker_hits,
            "status_histogram": self.status_histogram,
            "requestfailed_count": self.requestfailed_count,
            "elapsed_ms": self.elapsed_ms,
            "page_title": self.page_title,
            "error_message": self.error_message,
        }


def _check_text_markers(content: str, markers: list[str]) -> tuple[bool, str | None]:
    """Check if any text markers are present in content.

    Parameters
    ----------
    content : str
        Page content or text to search.
    markers : list[str]
        List of marker strings to look for.

    Returns
    -------
    tuple[bool, str | None]
        (found, matched_marker) tuple.
    """
    content_lower = content.lower()
    for marker in markers:
        if marker.lower() in content_lower:
            return True, marker
    return False, None


def _check_url_patterns(url: str, patterns: list[str]) -> tuple[bool, str | None]:
    """Check if URL matches any redirect patterns.

    Parameters
    ----------
    url : str
        URL to check.
    patterns : list[str]
        List of URL path patterns.

    Returns
    -------
    tuple[bool, str | None]
        (matched, pattern) tuple.
    """
    for pattern in patterns:
        if pattern.lower() in url.lower():
            return True, pattern
    return False, None


def _count_result_rows(page: Page, selector: str = RESULTS_ROW_SELECTOR) -> int:
    """Count visible result rows in the results table.

    Parameters
    ----------
    page : Page
        Playwright page object.
    selector : str
        CSS selector for result rows.

    Returns
    -------
    int
        Number of visible result rows.
    """
    try:
        rows = page.query_selector_all(selector)
        # Filter out rows that might be hidden or empty
        visible_count = 0
        for row in rows:
            # Check if row has content (not just whitespace)
            text = row.inner_text()
            if text and text.strip():
                visible_count += 1
        return visible_count
    except Exception:
        return 0


def classify_case_search(
    page: Page,
    net_observer: NetworkObserver,
    *,
    results_wait_timeout_ms: int = 15_000,
) -> ClassificationResult:
    """Classify the result of a case search operation.

    This function should be called AFTER submitting a search query.
    It waits for results and classifies the outcome.

    Parameters
    ----------
    page : Page
        Playwright page with search already submitted.
    net_observer : NetworkObserver
        Network observer that has been tracking the page.
    results_wait_timeout_ms : int
        Timeout for waiting for results container.

    Returns
    -------
    ClassificationResult
        Classification of the scrape attempt.
    """
    import time

    start_time = time.perf_counter()
    marker_hits: dict[str, bool] = {
        "results_container": False,
        "has_rows": False,
        "no_results_text": False,
        "blocked_marker": False,
        "session_lost_marker": False,
        "redirect_url": False,
        "soft_block_status": False,
        "server_error_status": False,
    }

    final_url = page.url
    page_title: str | None = None
    error_message: str | None = None
    row_count: int | None = None
    subreason: str | None = None

    with contextlib.suppress(Exception):
        page_title = page.title()

    # Check network observer for status codes
    marker_hits["soft_block_status"] = net_observer.has_soft_block_status(SOFT_BLOCKED_STATUS_CODES)
    marker_hits["server_error_status"] = net_observer.has_server_error_status(
        SERVER_ERROR_STATUS_CODES
    )

    # Get page content for text marker checks
    try:
        page_content = page.content()
    except Exception as e:
        # Can't get content - likely a network/server error
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        return ClassificationResult(
            classification=Classification.NETWORK_OR_SERVER_ERROR,
            subreason=f"Failed to get page content: {e}",
            final_url=final_url,
            marker_hits=marker_hits,
            status_histogram=dict(net_observer.status_histogram),
            requestfailed_count=net_observer.requestfailed_count,
            elapsed_ms=elapsed_ms,
            page_title=page_title,
            error_message=str(e),
        )

    # Check for blocked markers in content
    blocked_found, blocked_marker = _check_text_markers(page_content, BLOCKED_MARKERS)
    marker_hits["blocked_marker"] = blocked_found
    if blocked_found:
        subreason = f"Blocked marker: {blocked_marker}"

    # Check for session lost markers
    session_lost_found, session_marker = _check_text_markers(page_content, SESSION_LOST_MARKERS)
    marker_hits["session_lost_marker"] = session_lost_found

    # Check URL for redirect patterns
    redirect_found, redirect_pattern = _check_url_patterns(final_url, REDIRECT_URL_PATTERNS)
    marker_hits["redirect_url"] = redirect_found

    # Check if we're back at the landing page (indicates session lost/redirect)
    is_landing_page = final_url.rstrip("/") == PORTAL_URL.rstrip("/")

    # Try to wait for results container
    results_container_visible = False
    try:
        page.wait_for_selector(
            RESULTS_CONTAINER_SELECTOR,
            timeout=results_wait_timeout_ms,
            state="visible",
        )
        results_container_visible = True
        marker_hits["results_container"] = True
    except PlaywrightTimeoutError:
        # Results container didn't appear
        pass
    except Exception as e:
        error_message = str(e)
        logger.debug(f"Error waiting for results container: {e}")

    # Now classify based on collected evidence
    elapsed_ms = int((time.perf_counter() - start_time) * 1000)
    net_snapshot = net_observer.get_snapshot()

    # Priority 1: Check for soft-blocked status codes or blocked markers
    if marker_hits["soft_block_status"] or marker_hits["blocked_marker"]:
        if not subreason:
            if marker_hits["soft_block_status"]:
                subreason = "HTTP 403/429 detected"
            else:
                subreason = "Blocked content marker detected"
        return ClassificationResult(
            classification=Classification.SOFT_BLOCKED,
            subreason=subreason,
            final_url=final_url,
            marker_hits=marker_hits,
            status_histogram=net_snapshot["status_histogram"],
            requestfailed_count=net_snapshot["requestfailed_count"],
            elapsed_ms=elapsed_ms,
            page_title=page_title,
            error_message=error_message,
        )

    # Priority 2: Check for redirect/session lost
    # NOTE: Only flag as landing page redirect if results container is NOT visible.
    # The portal uses client-side rendering, so the URL often stays at /CaseSearch
    # even when results are successfully displayed.
    is_redirected = marker_hits["session_lost_marker"] or marker_hits["redirect_url"]
    is_landing_without_results = is_landing_page and not results_container_visible

    if is_redirected or is_landing_without_results:
        subreason_parts = []
        if marker_hits["session_lost_marker"]:
            subreason_parts.append(f"Session marker: {session_marker}")
        if marker_hits["redirect_url"]:
            subreason_parts.append(f"Redirect URL pattern: {redirect_pattern}")
        if is_landing_without_results:
            subreason_parts.append("Returned to landing page without results")
        return ClassificationResult(
            classification=Classification.REDIRECTED_OR_SESSION_LOST,
            subreason="; ".join(subreason_parts) if subreason_parts else None,
            final_url=final_url,
            marker_hits=marker_hits,
            status_histogram=net_snapshot["status_histogram"],
            requestfailed_count=net_snapshot["requestfailed_count"],
            elapsed_ms=elapsed_ms,
            page_title=page_title,
            error_message=error_message,
        )

    # Priority 3: Check for server errors or request failures
    if marker_hits["server_error_status"] or net_snapshot["requestfailed_count"] > 0:
        return ClassificationResult(
            classification=Classification.NETWORK_OR_SERVER_ERROR,
            subreason=(
                "Server error status detected"
                if marker_hits["server_error_status"]
                else f"{net_snapshot['requestfailed_count']} request(s) failed"
            ),
            final_url=final_url,
            marker_hits=marker_hits,
            status_histogram=net_snapshot["status_histogram"],
            requestfailed_count=net_snapshot["requestfailed_count"],
            elapsed_ms=elapsed_ms,
            page_title=page_title,
            error_message=error_message,
        )

    # Priority 4: If results container is visible, check for rows
    if results_container_visible:
        row_count = _count_result_rows(page)
        marker_hits["has_rows"] = row_count > 0

        # Check for "no results" text markers
        no_results_found, _ = _check_text_markers(page_content, NO_RESULTS_TEXT_MARKERS)
        marker_hits["no_results_text"] = no_results_found

        if row_count > 0:
            return ClassificationResult(
                classification=Classification.HAS_RESULTS,
                subreason=f"Found {row_count} result row(s)",
                row_count=row_count,
                final_url=final_url,
                marker_hits=marker_hits,
                status_histogram=net_snapshot["status_histogram"],
                requestfailed_count=net_snapshot["requestfailed_count"],
                elapsed_ms=elapsed_ms,
                page_title=page_title,
            )
        elif no_results_found or row_count == 0:
            return ClassificationResult(
                classification=Classification.ZERO_RESULTS,
                subreason=(
                    "No results text marker found" if no_results_found else "Results table empty"
                ),
                row_count=0,
                final_url=final_url,
                marker_hits=marker_hits,
                status_histogram=net_snapshot["status_histogram"],
                requestfailed_count=net_snapshot["requestfailed_count"],
                elapsed_ms=elapsed_ms,
                page_title=page_title,
            )

    # Priority 5: Results container never appeared - UI drift or unknown
    return ClassificationResult(
        classification=Classification.UI_DRIFT_OR_UNKNOWN,
        subreason="Results container did not appear within timeout",
        final_url=final_url,
        marker_hits=marker_hits,
        status_histogram=net_snapshot["status_histogram"],
        requestfailed_count=net_snapshot["requestfailed_count"],
        elapsed_ms=elapsed_ms,
        page_title=page_title,
        error_message=error_message,
    )


def classify_from_exception(
    exception: Exception,
    final_url: str,
    net_observer: NetworkObserver,
    elapsed_ms: int,
) -> ClassificationResult:
    """Classify a scrape attempt that raised an exception.

    Parameters
    ----------
    exception : Exception
        The exception that was raised.
    final_url : str
        URL at time of exception.
    net_observer : NetworkObserver
        Network observer instance.
    elapsed_ms : int
        Time elapsed before exception.

    Returns
    -------
    ClassificationResult
        Classification based on exception type.
    """
    net_snapshot = net_observer.get_snapshot()

    # Check if it's a timeout
    if isinstance(exception, PlaywrightTimeoutError):
        return ClassificationResult(
            classification=Classification.NETWORK_OR_SERVER_ERROR,
            subreason=f"Playwright timeout: {exception}",
            final_url=final_url,
            status_histogram=net_snapshot["status_histogram"],
            requestfailed_count=net_snapshot["requestfailed_count"],
            elapsed_ms=elapsed_ms,
            error_message=str(exception),
        )

    # Check for network-related exceptions
    error_str = str(exception).lower()
    network_keywords = ["network", "dns", "connection", "timeout", "refused", "reset"]
    if any(kw in error_str for kw in network_keywords):
        return ClassificationResult(
            classification=Classification.NETWORK_OR_SERVER_ERROR,
            subreason=f"Network error: {type(exception).__name__}",
            final_url=final_url,
            status_histogram=net_snapshot["status_histogram"],
            requestfailed_count=net_snapshot["requestfailed_count"],
            elapsed_ms=elapsed_ms,
            error_message=str(exception),
        )

    # Default to UI drift/unknown for other exceptions
    return ClassificationResult(
        classification=Classification.UI_DRIFT_OR_UNKNOWN,
        subreason=f"Unexpected exception: {type(exception).__name__}",
        final_url=final_url,
        status_histogram=net_snapshot["status_histogram"],
        requestfailed_count=net_snapshot["requestfailed_count"],
        elapsed_ms=elapsed_ms,
        error_message=str(exception),
    )
