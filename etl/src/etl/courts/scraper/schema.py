"""Pydantic schemas for UJS portal scraping results."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, field_validator

__all__ = ["PortalResult", "ScrapeError", "ScrapeOutcome", "OutcomeStatus"]


class OutcomeStatus(str, Enum):
    """Status of a scrape outcome.

    Attributes
    ----------
    SUCCESS : str
        Found results in the portal (HAS_RESULTS classification).
    NO_RESULTS : str
        Portal search completed but found no matching records.
    FAILED : str
        Scrape failed after exhausting retries (e.g., SOFT_BLOCKED, UI_DRIFT).
    INVALID_INPUT : str
        Input value was invalid (e.g., wrong format).
    """

    SUCCESS = "success"
    NO_RESULTS = "no_results"
    FAILED = "failed"
    INVALID_INPUT = "invalid_input"


class ScrapeOutcome(BaseModel):
    """Outcome of a scrape attempt for a single input value.

    This provides richer information than just the results list,
    allowing callers to distinguish between "no results found" and
    "scrape failed after retries".

    Attributes
    ----------
    status : OutcomeStatus
        High-level status of the scrape.
    results : list[PortalResult] | None
        Parsed results if status is SUCCESS, None otherwise.
    classification : str | None
        Raw classification from the verifier (e.g., "HAS_RESULTS", "SOFT_BLOCKED").
    subreason : str | None
        Additional context about the classification.
    attempt_count : int
        Number of attempts made.
    """

    status: OutcomeStatus
    results: list["PortalResult"] | None = None
    classification: str | None = None
    subreason: str | None = None
    attempt_count: int = 1


class PortalResult(BaseModel):
    """Scraped result from the UJS portal page."""

    docket_number: str
    court_type: str
    short_caption: str
    case_status: str
    filing_date: str
    party: str
    date_of_birth: str
    county: str
    court_office: str
    otn: str
    lotn: str
    dc_number: str
    docket_sheet_url: str
    court_summary_url: str

    @field_validator("*", mode="before")
    @classmethod
    def _strip_strings(cls, v: Any) -> Any:
        """Strip leading/trailing whitespace from all string fields."""
        if isinstance(v, str):
            return v.strip()
        return v


class ScrapeError(BaseModel):
    """Error record for a failed scrape attempt."""

    input_value: str
    error_type: str
    error_message: str
    timestamp: datetime
    attempt_count: int
    screenshot_path: str | None = None
