"""Pydantic schemas for UJS portal scraping results."""

from typing import Any

from pydantic import BaseModel, field_validator

__all__ = ["PortalResult"]


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
