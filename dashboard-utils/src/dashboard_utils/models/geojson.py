from typing import Any, Literal

from pydantic import BaseModel


class GeoJSONFeature[PropsT: BaseModel](BaseModel):
    """Generic GeoJSON Feature wrapper."""

    type: Literal["Feature"]
    geometry: dict[str, Any] | None
    properties: PropsT


class GeoJSONFeatureCollection[FeatureT: BaseModel](BaseModel):
    """Generic GeoJSON FeatureCollection wrapper."""

    type: Literal["FeatureCollection"]
    features: list[FeatureT]
