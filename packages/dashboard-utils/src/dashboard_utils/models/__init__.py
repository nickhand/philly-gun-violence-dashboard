"""Shared Pydantic models."""

from dashboard_utils.models.boundaries import BoundaryFeatureCollection
from dashboard_utils.models.geojson import GeoJSONFeature, GeoJSONFeatureCollection
from dashboard_utils.models.shootings import ShootingsFeatureCollection, ShootingVictimsSchema
from dashboard_utils.models.streets import StreetBlockSchema, StreetsFeatureCollection

__all__ = [
    "BoundaryFeatureCollection",
    "GeoJSONFeature",
    "GeoJSONFeatureCollection",
    "ShootingsFeatureCollection",
    "ShootingVictimsSchema",
    "StreetsFeatureCollection",
    "StreetBlockSchema",
]
