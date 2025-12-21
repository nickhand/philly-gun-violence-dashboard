"""Pydantic schemas for UJS portal scraping results."""

from typing import List

import pandas as pd
from pydantic import BaseModel, field_validator

__all__ = ["PortalResult", "PortalResults"]


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
    def _strip_strings(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    def __repr__(self) -> str:
        fields = ["docket_number", "filing_date", "party"]
        summary = ", ".join(f"{f}='{getattr(self, f)}'" for f in fields)
        return f"{self.__class__.__name__}({summary})"


class PortalResults(BaseModel):
    """List of results from portal scraping."""

    data: List[PortalResult]

    def __len__(self) -> int:
        return len(self.data)

    def __getitem__(self, index: int) -> PortalResult:
        return self.data.__getitem__(index)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(num_results={len(self)})"

    def to_pandas(self) -> pd.DataFrame:
        return pd.DataFrame([r.model_dump() for r in self.data])
