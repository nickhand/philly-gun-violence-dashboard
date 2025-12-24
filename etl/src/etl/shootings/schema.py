from typing import Literal

import numpy as np
from pydantic import BaseModel, Field, field_validator

# Options for categorical fields
RaceOptions = Literal["B", "H", "W", "A", "Other/Unknown"]
SexOptions = Literal["M", "F"]
AgeGroupOptions = Literal[
    "Younger than 18",
    "18 to 30",
    "31 to 45",
    "Older than 45",
    "Unknown",
]


class ShootingVictimsSchema(BaseModel):
    """Schema for the shooting victims dataset."""

    dc_key: str = Field(
        title="Incident number",
        description="The unique incident number assigned by the Police Department.",
    )
    race: RaceOptions = Field(
        title="Race/Ethnicity",
        description=(
            "The race/ethnicity of the shooting victim. "
            "Allowed values include: 'B' = Black, Non-Hispanic, 'H' = Hispanic, "
            "'W' = White, Non-Hispanic, 'A' = Asian, and 'Other/Unknown'"
        ),
    )
    sex: SexOptions = Field(
        title="Sex",
        description="The sex of the shooting victim.",
    )
    fatal: bool = Field(
        title="Fatal?",
        description="Whether the incident was fatal.",
    )
    date: str = Field(
        title="Date",
        description="The datetime of the incident in the format 'Y/m/d H:M:S'",
    )
    age_group: AgeGroupOptions = Field(
        title="Age group",
        description="The victim's age group (or unknown).",
    )
    has_court_case: bool = Field(
        title="Associated Court Case?",
        description="Does the incident number have an associated court case?",
    )
    age: float | None = Field(
        title="Age",
        description="The victim's age; missing in some cases.",
    )
    street_name: str | None = Field(
        title="Street name",
        description="The name of the street the incident occurred on, if available.",
    )
    block_number: int | None = Field(
        title="Block number",
        description="The block number where the incident occurred, if available.",
    )
    zip_code: str | None = Field(
        title="ZIP Code",
        description="The ZIP code where the incident occurred, if available.",
    )
    council_district: str | None = Field(
        title="Council district",
        description="The council district where the incident occurred, if available.",
    )
    police_district: str | None = Field(
        title="Police district",
        description="The police district where the incident occurred, if available.",
    )
    neighborhood: str | None = Field(
        title="Neighborhood name",
        description="The name of the neighborhood where the incident occurred, if available.",
    )
    school_name: str | None = Field(
        title="School catchment",
        description="The elementary school catchment where the incident occurred, if available.",
    )
    house_district: str | None = Field(
        title="PA House district",
        description="The PA House district where the incident occurred, if available.",
    )
    senate_district: str | None = Field(
        title="PA Senate district",
        description="The PA Senate district where the incident occurred, if available.",
    )
    segment_id: str | None = Field(
        title="Block Segment ID",
        description="The ID of the street segment where the incident occurred, if available.",
    )

    @field_validator("dc_key")
    @classmethod
    def verify_dc_key(cls, v: str) -> str:
        if not isinstance(v, str):
            assert not np.isnan(v), "cannot be NaN"
        else:
            assert not v.endswith(".0"), "bad string formatting"
        return v
