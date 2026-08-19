from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from dashboard_utils.constants import DATE_FORMAT
from dashboard_utils.models.geojson import GeoJSONFeature, GeoJSONFeatureCollection

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

    model_config = ConfigDict(extra="forbid", strict=True)

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
        description=f"The datetime of the incident in the format '{DATE_FORMAT}'.",
    )
    age_group: AgeGroupOptions = Field(
        title="Age group",
        description="The victim's age group (or unknown).",
    )
    has_court_case: StrictBool | None = Field(
        title="Public court search result",
        description=(
            "Whether an automated incident-number search of Pennsylvania's public court "
            "portal returned a result. True means the search returned a result; false "
            "means a completed search returned an explicit no-results response; null "
            "means the search was unavailable, incomplete, or inconclusive. This field "
            "does not establish a relationship between a court record and a shooting "
            "victim or report a case outcome."
        ),
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

    @field_validator("dc_key", mode="before")
    @classmethod
    def verify_dc_key(cls, value: object) -> str:
        """Require the source incident identifier to be a normalized string."""
        if not isinstance(value, str):
            raise ValueError("dc_key must be a string")
        normalized = value.strip()
        if not normalized:
            raise ValueError("dc_key must not be blank")
        if normalized.endswith(".0"):
            raise ValueError("dc_key must not use floating-point formatting")
        return normalized


class ShootingFeature(GeoJSONFeature[ShootingVictimsSchema]):
    """GeoJSON Feature wrapper for a shooting victim record."""


class ShootingsFeatureCollection(GeoJSONFeatureCollection[ShootingFeature]):
    """GeoJSON FeatureCollection for shootings."""
