"""Configuration for UJS CaseSearch scraper verification.

This module provides configuration settings for the scraper, loaded from
environment variables with sensible defaults for local development.
"""

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class ScraperConfig:
    """Configuration for the UJS CaseSearch scraper with verification.

    Attributes
    ----------
    max_attempts : int
        Maximum number of retry attempts per incident number.
    backoff_base_s : float
        Base wait time for exponential backoff (seconds).
    backoff_max_s : float
        Maximum wait time between retries (seconds).
    jitter_s : float
        Maximum jitter added to backoff (seconds).
    navigation_timeout_ms : int
        Timeout for page navigation (milliseconds).
    results_wait_timeout_ms : int
        Timeout for waiting for results container (milliseconds).
    sleep_between_requests_s : float
        Sleep time between requests (seconds).
    enable_screenshots : bool
        Whether to capture screenshots for non-HAS_RESULTS outcomes.
    audit_output_dir : str
        Local directory for audit output files.
    audit_s3_prefix : str | None
        S3 prefix for audit output (e.g., 's3://bucket/courts-audit').
    compress_audit_logs : bool
        Whether to gzip audit log files.
    concurrency : int
        Maximum concurrent scrape operations (for local testing).
    debug : bool
        Enable debug mode (non-headless browser, verbose logging).
    log_freq : int
        Frequency of progress logging (every N incident numbers).
    """

    # Retry settings
    max_attempts: int = 8
    backoff_base_s: float = 5.0
    backoff_max_s: float = 30.0
    jitter_s: float = 2.0

    # Timeout settings
    navigation_timeout_ms: int = 12_000
    results_wait_timeout_ms: int = 15_000

    # Request pacing
    sleep_between_requests_s: float = 7.0

    # Screenshots
    enable_screenshots: bool = True

    # Audit output
    audit_output_dir: str = "artifacts"
    audit_s3_prefix: str | None = None
    compress_audit_logs: bool = True

    # Local concurrency (for testing harness)
    concurrency: int = 1

    # Debug settings
    debug: bool = False
    log_freq: int = 50


def _bool_env(key: str, default: bool) -> bool:
    """Parse a boolean environment variable."""
    val = os.getenv(key)
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes", "on")


def _int_env(key: str, default: int) -> int:
    """Parse an integer environment variable."""
    val = os.getenv(key)
    return int(val) if val else default


def _float_env(key: str, default: float) -> float:
    """Parse a float environment variable."""
    val = os.getenv(key)
    return float(val) if val else default


def _str_env(key: str, default: str) -> str:
    """Get a string environment variable with default."""
    return os.getenv(key, default)


def _optional_str_env(key: str) -> str | None:
    """Get an optional string environment variable."""
    return os.getenv(key)


@lru_cache(maxsize=1)
def get_scraper_config() -> ScraperConfig:
    """Load scraper configuration from environment variables.

    Environment Variables
    ---------------------
    MAX_ATTEMPTS : int
        Maximum retry attempts (default: 8)
    BACKOFF_BASE_S : float
        Base backoff time in seconds (default: 5.0)
    BACKOFF_MAX_S : float
        Maximum backoff time in seconds (default: 30.0)
    JITTER_S : float
        Maximum jitter in seconds (default: 2.0)
    NAVIGATION_TIMEOUT_MS : int
        Page navigation timeout in ms (default: 12000)
    RESULTS_WAIT_TIMEOUT_MS : int
        Results wait timeout in ms (default: 15000)
    SLEEP_BETWEEN_REQUESTS_S : float
        Sleep between requests in seconds (default: 7.0)
    ENABLE_SCREENSHOTS : bool
        Capture screenshots (default: True)
    AUDIT_OUTPUT_DIR : str
        Local audit output directory (default: 'artifacts')
    AUDIT_S3_PREFIX : str
        S3 prefix for audit output (optional)
    COMPRESS_AUDIT_LOGS : bool
        Gzip audit logs (default: True)
    CONCURRENCY : int
        Local concurrency (default: 1)
    DEBUG : bool
        Enable debug mode (default: False)
    LOG_FREQ : int
        Logging frequency (default: 50)

    Returns
    -------
    ScraperConfig
        Configuration instance populated from environment.
    """
    return ScraperConfig(
        max_attempts=_int_env("MAX_ATTEMPTS", 8),
        backoff_base_s=_float_env("BACKOFF_BASE_S", 5.0),
        backoff_max_s=_float_env("BACKOFF_MAX_S", 30.0),
        jitter_s=_float_env("JITTER_S", 2.0),
        navigation_timeout_ms=_int_env("NAVIGATION_TIMEOUT_MS", 12_000),
        results_wait_timeout_ms=_int_env("RESULTS_WAIT_TIMEOUT_MS", 15_000),
        sleep_between_requests_s=_float_env("SLEEP_BETWEEN_REQUESTS_S", 7.0),
        enable_screenshots=_bool_env("ENABLE_SCREENSHOTS", True),
        audit_output_dir=_str_env("AUDIT_OUTPUT_DIR", "artifacts"),
        audit_s3_prefix=_optional_str_env("AUDIT_S3_PREFIX"),
        compress_audit_logs=_bool_env("COMPRESS_AUDIT_LOGS", True),
        concurrency=_int_env("CONCURRENCY", 1),
        debug=_bool_env("DEBUG", False),
        log_freq=_int_env("LOG_FREQ", 50),
    )


# -----------------------------------------------------------------------------
# Classification constants (anchors/markers)
# -----------------------------------------------------------------------------

# Portal URL constants
PORTAL_BASE_URL = "https://ujsportal.pacourts.us"
PORTAL_URL = f"{PORTAL_BASE_URL}/CaseSearch"

# Selectors for results detection
RESULTS_CONTAINER_SELECTOR = "#caseSearchResultGrid"
RESULTS_ROW_SELECTOR = "#caseSearchResultGrid tbody tr"
NO_RESULTS_TEXT_MARKERS = [
    "No results found",
    "no results were found",
    "No records found",
    "0 results",
]

# Selectors/text for blocked/interstitial detection
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

# Selectors/text for session lost / redirect detection
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

# HTTP status codes considered as soft-blocked
SOFT_BLOCKED_STATUS_CODES = {403, 429}

# HTTP status codes indicating server errors (retryable)
SERVER_ERROR_STATUS_CODES = {500, 502, 503, 504}
