from pydantic import BaseModel, Field

from dashboard_utils.models.geojson import GeoJSONFeature, GeoJSONFeatureCollection


class StreetBlockSchema(BaseModel):
    """Schema for a street block."""

    street_name: str = Field(
        title="Street name",
        description="The name of the street.",
    )
    block_number: int = Field(
        title="Block number",
        description="The block number for the street segment.",
    )
    block_label: str = Field(
        title="Block label",
        description="The combined block label (e.g., '1200 BLOCK MARKET ST').",
    )
    segment_id: str = Field(
        title="Segment ID",
        description="Unique identifier for the street block segment.",
    )


class StreetBlockFeature(GeoJSONFeature[StreetBlockSchema]):
    """GeoJSON Feature wrapper for a street block."""


class StreetsFeatureCollection(GeoJSONFeatureCollection[StreetBlockFeature]):
    """GeoJSON FeatureCollection for street blocks."""
