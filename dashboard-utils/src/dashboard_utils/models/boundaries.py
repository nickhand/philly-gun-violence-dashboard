from pydantic import BaseModel, Field

from dashboard_utils.models.geojson import GeoJSONFeature, GeoJSONFeatureCollection


class CityLimitsProperties(BaseModel):
    """Properties for the city limits boundary."""


class PaHouseDistrictProperties(BaseModel):
    """Properties for PA House districts."""

    house_district: str | None = Field(
        default=None,
        title="PA House district",
        description="Pennsylvania House district identifier.",
    )


class PaSenateDistrictProperties(BaseModel):
    """Properties for PA Senate districts."""

    senate_district: str | None = Field(
        default=None,
        title="PA Senate district",
        description="Pennsylvania Senate district identifier.",
    )


class SchoolCatchmentProperties(BaseModel):
    """Properties for school catchments."""

    school_name: str | None = Field(
        default=None,
        title="School catchment",
        description="Elementary school catchment name.",
    )


class PoliceDistrictProperties(BaseModel):
    """Properties for police districts."""

    police_district: str | None = Field(
        default=None,
        title="Police district",
        description="Police district identifier.",
    )


class ZipCodeProperties(BaseModel):
    """Properties for ZIP codes."""

    zip_code: str | None = Field(
        default=None,
        title="ZIP Code",
        description="ZIP code identifier.",
    )


class CouncilDistrictProperties(BaseModel):
    """Properties for council districts."""

    council_district: str | None = Field(
        default=None,
        title="Council district",
        description="City council district identifier.",
    )


class NeighborhoodProperties(BaseModel):
    """Properties for neighborhoods."""

    neighborhood: str | None = Field(
        default=None,
        title="Neighborhood name",
        description="Neighborhood name.",
    )


class CityLimitsFeature(GeoJSONFeature[CityLimitsProperties]):
    """GeoJSON Feature for city limits."""


class PaHouseDistrictFeature(GeoJSONFeature[PaHouseDistrictProperties]):
    """GeoJSON Feature for PA House districts."""


class PaSenateDistrictFeature(GeoJSONFeature[PaSenateDistrictProperties]):
    """GeoJSON Feature for PA Senate districts."""


class SchoolCatchmentFeature(GeoJSONFeature[SchoolCatchmentProperties]):
    """GeoJSON Feature for school catchments."""


class PoliceDistrictFeature(GeoJSONFeature[PoliceDistrictProperties]):
    """GeoJSON Feature for police districts."""


class ZipCodeFeature(GeoJSONFeature[ZipCodeProperties]):
    """GeoJSON Feature for ZIP codes."""


class CouncilDistrictFeature(GeoJSONFeature[CouncilDistrictProperties]):
    """GeoJSON Feature for council districts."""


class NeighborhoodFeature(GeoJSONFeature[NeighborhoodProperties]):
    """GeoJSON Feature for neighborhoods."""


class CityLimitsFeatureCollection(GeoJSONFeatureCollection[CityLimitsFeature]):
    """GeoJSON FeatureCollection for city limits."""


class PaHouseDistrictFeatureCollection(GeoJSONFeatureCollection[PaHouseDistrictFeature]):
    """GeoJSON FeatureCollection for PA House districts."""


class PaSenateDistrictFeatureCollection(GeoJSONFeatureCollection[PaSenateDistrictFeature]):
    """GeoJSON FeatureCollection for PA Senate districts."""


class SchoolCatchmentFeatureCollection(GeoJSONFeatureCollection[SchoolCatchmentFeature]):
    """GeoJSON FeatureCollection for school catchments."""


class PoliceDistrictFeatureCollection(GeoJSONFeatureCollection[PoliceDistrictFeature]):
    """GeoJSON FeatureCollection for police districts."""


class ZipCodeFeatureCollection(GeoJSONFeatureCollection[ZipCodeFeature]):
    """GeoJSON FeatureCollection for ZIP codes."""


class CouncilDistrictFeatureCollection(GeoJSONFeatureCollection[CouncilDistrictFeature]):
    """GeoJSON FeatureCollection for council districts."""


class NeighborhoodFeatureCollection(GeoJSONFeatureCollection[NeighborhoodFeature]):
    """GeoJSON FeatureCollection for neighborhoods."""


BoundaryFeatureCollection = (
    CityLimitsFeatureCollection
    | PaHouseDistrictFeatureCollection
    | PaSenateDistrictFeatureCollection
    | SchoolCatchmentFeatureCollection
    | PoliceDistrictFeatureCollection
    | ZipCodeFeatureCollection
    | CouncilDistrictFeatureCollection
    | NeighborhoodFeatureCollection
)
