"""Shared pagination models."""

from pydantic import BaseModel, Field


class Page(BaseModel):
    """Common pagination metadata for paged responses."""

    limit: int = Field(
        title="Limit",
        description="Maximum number of features returned.",
    )
    offset: int = Field(
        title="Offset",
        description="Zero-based index of the first returned feature.",
    )
    count: int = Field(
        title="Count",
        description="Number of features returned in this page.",
    )
    total: int = Field(
        title="Total",
        description="Total number of available features for the query.",
    )
    next_offset: int | None = Field(
        title="Next offset",
        description="Offset to request the next page, if available.",
    )
