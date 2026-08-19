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
from typing import Any

from loguru import logger
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from etl.courts.scraper.net_observer import NetworkObserver

# Portal URL constants
PORTAL_URL = "https://ujsportal.pacourts.us/CaseSearch"

# Selectors for results detection
RESULTS_CONTAINER_SELECTOR = "#caseSearchResultGrid"
RESULTS_ROW_SELECTOR = "#caseSearchResultGrid tbody tr"
NO_RESULTS_ELEMENT_SELECTOR = (
    "#caseSearchResultGrid .no-records, #caseSearchResultGrid .no-results-message"
)
NO_RESULTS_TEXT_MARKERS = [
    "No results found",
    "no results were found",
    "No records found",
    "0 results",
]

# Text markers for blocked/interstitial detection
BLOCKED_MARKERS = [
    "Access Denied",
    "access denied",
    "unusual traffic",
    "too many requests",
    "Please enable cookies",
    "JavaScript required",
    "enable JavaScript",
    "CAPTCHA",
    "captcha",
    "verify you are human",
    "are you a robot",
    "rate limit",
    "temporarily blocked",
    "Service Unavailable",
]

# Text markers for session lost / redirect detection
SESSION_LOST_MARKERS = [
    "session has expired",
    "Session Expired",
    "please log in again",
    "login required",
    "sign in",
]

# URL patterns indicating redirect to landing/login
REDIRECT_URL_PATTERNS = [
    "/Login",
    "/login",
    "/SignIn",
    "/Error",
    "/Maintenance",
]

# HTTP status codes
SOFT_BLOCKED_STATUS_CODES = {403, 429}
SERVER_ERROR_STATUS_CODES = {500, 502, 503, 504}


class Classification(str, Enum):
    """Classification buckets for scrape attempts."""

    HAS_RESULTS = "HAS_RESULTS"
    ZERO_RESULTS = "ZERO_RESULTS"
    SOFT_BLOCKED = "SOFT_BLOCKED"
    REDIRECTED_OR_SESSION_LOST = "REDIRECTED_OR_SESSION_LOST"
    NETWORK_OR_SERVER_ERROR = "NETWORK_OR_SERVER_ERROR"
    UI_DRIFT_OR_UNKNOWN = "UI_DRIFT_OR_UNKNOWN"


NON_RETRYABLE_CLASSIFICATIONS = {
    Classification.HAS_RESULTS,
    Classification.ZERO_RESULTS,
}

RETRYABLE_CLASSIFICATIONS = {
    Classification.SOFT_BLOCKED,
    Classification.REDIRECTED_OR_SESSION_LOST,
    Classification.NETWORK_OR_SERVER_ERROR,
    Classification.UI_DRIFT_OR_UNKNOWN,
}


@dataclass
class ClassificationResult:
    """Result of classifying a scrape attempt."""

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
        return self.classification in RETRYABLE_CLASSIFICATIONS

    @property
    def is_success(self) -> bool:
        return self.classification in {Classification.HAS_RESULTS, Classification.ZERO_RESULTS}

    def to_dict(self) -> dict[str, Any]:
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
    content_lower = content.lower()
    for marker in markers:
        if marker.lower() in content_lower:
            return True, marker
    return False, None


def _check_url_patterns(url: str, patterns: list[str]) -> tuple[bool, str | None]:
    for pattern in patterns:
        if pattern.lower() in url.lower():
            return True, pattern
    return False, None


def _count_result_rows(page: Page, selector: str = RESULTS_ROW_SELECTOR) -> int:
    rows = page.query_selector_all(selector)
    visible_count = 0
    for row in rows:
        if not row.is_visible():
            continue
        text = row.inner_text()
        if not text or not text.strip():
            continue
        no_results_found, _ = _check_text_markers(text, NO_RESULTS_TEXT_MARKERS)
        if no_results_found:
            continue
        class_attr = row.get_attribute("class") or ""
        if "no-records" in class_attr.split():
            continue
        visible_count += 1
    return visible_count


def _visible_no_results_marker(page: Page) -> tuple[bool, str | None]:
    """Find an explicit, visible no-records element inside the result grid."""
    for element in page.query_selector_all(NO_RESULTS_ELEMENT_SELECTOR):
        if not element.is_visible():
            continue
        found, marker = _check_text_markers(element.inner_text(), NO_RESULTS_TEXT_MARKERS)
        if found:
            return True, marker
    return False, None


def classify_case_search(
    page: Page,
    net_observer: NetworkObserver,
    *,
    results_wait_timeout_ms: int = 15_000,
) -> ClassificationResult:
    """Classify the result of a case search operation.

    Should be called AFTER submitting a search query.
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

    marker_hits["soft_block_status"] = net_observer.has_soft_block_status(SOFT_BLOCKED_STATUS_CODES)
    marker_hits["server_error_status"] = net_observer.has_server_error_status(
        SERVER_ERROR_STATUS_CODES
    )

    try:
        page_content = page.content()
    except Exception as e:
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

    blocked_found, blocked_marker = _check_text_markers(page_content, BLOCKED_MARKERS)
    marker_hits["blocked_marker"] = blocked_found
    if blocked_found:
        subreason = f"Blocked marker: {blocked_marker}"

    session_lost_found, session_marker = _check_text_markers(page_content, SESSION_LOST_MARKERS)
    marker_hits["session_lost_marker"] = session_lost_found

    redirect_found, redirect_pattern = _check_url_patterns(final_url, REDIRECT_URL_PATTERNS)
    marker_hits["redirect_url"] = redirect_found

    is_landing_page = final_url.rstrip("/") == PORTAL_URL.rstrip("/")

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
        pass
    except Exception as e:
        error_message = str(e)
        logger.debug(f"Error waiting for results container: {e}")

    elapsed_ms = int((time.perf_counter() - start_time) * 1000)
    net_snapshot = net_observer.get_snapshot()

    def result(
        classification: Classification,
        *,
        subreason: str | None = None,
        row_count: int | None = None,
        error_message: str | None = error_message,
    ) -> ClassificationResult:
        return ClassificationResult(
            classification=classification,
            subreason=subreason,
            row_count=row_count,
            final_url=final_url,
            marker_hits=marker_hits,
            status_histogram=net_snapshot["status_histogram"],
            requestfailed_count=net_snapshot["requestfailed_count"],
            elapsed_ms=elapsed_ms,
            page_title=page_title,
            error_message=error_message,
        )

    # Priority 1: soft-blocked status codes or blocked markers
    if marker_hits["soft_block_status"] or marker_hits["blocked_marker"]:
        if not subreason:
            subreason = (
                "HTTP 403/429 detected"
                if marker_hits["soft_block_status"]
                else "Blocked content marker detected"
            )
        return result(Classification.SOFT_BLOCKED, subreason=subreason)

    # Priority 2: redirect/session lost
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
        return result(
            Classification.REDIRECTED_OR_SESSION_LOST,
            subreason="; ".join(subreason_parts) if subreason_parts else None,
        )

    # Priority 3: server errors. Generic request failures are considered only after
    # checking whether the results container rendered successfully.
    if marker_hits["server_error_status"]:
        return result(
            Classification.NETWORK_OR_SERVER_ERROR,
            subreason="Server error status detected",
        )

    # Priority 4: results container visible, check rows
    if results_container_visible:
        try:
            row_count = _count_result_rows(page)
        except Exception as exc:
            return result(
                Classification.UI_DRIFT_OR_UNKNOWN,
                subreason="Failed to inspect results table rows",
                error_message=str(exc),
            )
        marker_hits["has_rows"] = row_count > 0

        if row_count > 0:
            return result(
                Classification.HAS_RESULTS,
                subreason=f"Found {row_count} result row(s)",
                row_count=row_count,
                error_message=None,
            )
        try:
            no_results_found, _ = _visible_no_results_marker(page)
        except Exception as exc:
            return result(
                Classification.UI_DRIFT_OR_UNKNOWN,
                subreason="Failed to inspect explicit no-results indicator",
                row_count=0,
                error_message=str(exc),
            )
        marker_hits["no_results_text"] = no_results_found
        if no_results_found:
            return result(
                Classification.ZERO_RESULTS,
                subreason="No results text marker found",
                row_count=0,
                error_message=None,
            )
        return result(
            Classification.UI_DRIFT_OR_UNKNOWN,
            subreason="Results table was visible but empty without an explicit no-results marker",
            row_count=0,
            error_message=None,
        )

    if net_snapshot["requestfailed_count"] > 0:
        return result(
            Classification.NETWORK_OR_SERVER_ERROR,
            subreason=f"{net_snapshot['requestfailed_count']} request(s) failed",
        )

    # Priority 5: UI drift or unknown
    return result(
        Classification.UI_DRIFT_OR_UNKNOWN,
        subreason="Results container did not appear within timeout",
    )


def classify_from_exception(
    exception: Exception,
    final_url: str,
    net_observer: NetworkObserver | None,
    elapsed_ms: int,
) -> ClassificationResult:
    """Classify a scrape attempt that raised an exception."""
    net_snapshot = net_observer.get_snapshot() if net_observer else {}
    status_histogram = net_snapshot.get("status_histogram")
    requestfailed_count = net_snapshot.get("requestfailed_count", 0)

    if _has_status(status_histogram, SOFT_BLOCKED_STATUS_CODES):
        return ClassificationResult(
            classification=Classification.SOFT_BLOCKED,
            subreason="HTTP 403/429 detected during exception handling",
            final_url=final_url,
            status_histogram=status_histogram,
            requestfailed_count=requestfailed_count,
            elapsed_ms=elapsed_ms,
            error_message=str(exception),
        )

    if _has_status(status_histogram, SERVER_ERROR_STATUS_CODES):
        return ClassificationResult(
            classification=Classification.NETWORK_OR_SERVER_ERROR,
            subreason="Server error status detected during exception handling",
            final_url=final_url,
            status_histogram=status_histogram,
            requestfailed_count=requestfailed_count,
            elapsed_ms=elapsed_ms,
            error_message=str(exception),
        )

    if isinstance(exception, PlaywrightTimeoutError):
        return ClassificationResult(
            classification=Classification.NETWORK_OR_SERVER_ERROR,
            subreason=f"Playwright timeout: {exception}",
            final_url=final_url,
            status_histogram=status_histogram,
            requestfailed_count=requestfailed_count,
            elapsed_ms=elapsed_ms,
            error_message=str(exception),
        )

    error_str = str(exception).lower()
    network_keywords = ["network", "dns", "connection", "timeout", "refused", "reset"]
    if any(kw in error_str for kw in network_keywords):
        return ClassificationResult(
            classification=Classification.NETWORK_OR_SERVER_ERROR,
            subreason=f"Network error: {type(exception).__name__}",
            final_url=final_url,
            status_histogram=status_histogram,
            requestfailed_count=requestfailed_count,
            elapsed_ms=elapsed_ms,
            error_message=str(exception),
        )

    return ClassificationResult(
        classification=Classification.UI_DRIFT_OR_UNKNOWN,
        subreason=f"Unexpected exception: {type(exception).__name__}",
        final_url=final_url,
        status_histogram=status_histogram,
        requestfailed_count=requestfailed_count,
        elapsed_ms=elapsed_ms,
        error_message=str(exception),
    )


def _has_status(status_histogram: Any, statuses: set[int]) -> bool:
    """Return True when a network snapshot contains one of the target statuses."""
    if not isinstance(status_histogram, dict):
        return False
    for status in status_histogram:
        try:
            if int(status) in statuses:
                return True
        except (TypeError, ValueError):
            continue
    return False
