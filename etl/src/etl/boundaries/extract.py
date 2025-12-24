import geopandas as gpd

from etl.config import settings
from etl.utils.misc import number_to_string
from etl.utils.query import query_arcgis
from etl.utils.registry import register_geodataset


@register_geodataset
def get_city_limits() -> gpd.GeoDataFrame:
    """Load the city limits."""
    url = "https://opendata.arcgis.com/datasets/405ec3da942d4e20869d4e1449a2be48_0.geojson"
    return gpd.read_file(url).to_crs(settings.REFERENCE_CRS)


@register_geodataset
def get_pa_house_districts() -> gpd.GeoDataFrame:
    """PA House districts in in Philadelphia."""
    return (
        query_arcgis(
            url="https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/Gun_Violence_Dashboard_PA_House_Districts/FeatureServer/0",
            fields=["house_district"],
        )
        .assign(house_district=lambda df: df.house_district.apply(number_to_string))
        .to_crs(settings.REFERENCE_CRS)
    )


@register_geodataset
def get_pa_senate_districts() -> gpd.GeoDataFrame:
    """PA Senate districts in in Philadelphia."""
    return (
        query_arcgis(
            url="https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/Gun_Violence_Dashboard_PA_Senate_Districts/FeatureServer/0",
            fields=["senate_district"],
        )
        .assign(senate_district=lambda df: df.senate_district.apply(number_to_string))
        .to_crs(settings.REFERENCE_CRS)
    )


@register_geodataset
def get_school_catchments() -> gpd.GeoDataFrame:
    """Elementary school catchments in in Philadelphia."""
    return query_arcgis(
        url="https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/Gun_Violence_Dashboard_School_Catchments/FeatureServer/0",
        fields=["school_name"],
    ).to_crs(settings.REFERENCE_CRS)


@register_geodataset
def get_police_districts() -> gpd.GeoDataFrame:
    """Police Districts in Philadelphia."""
    return (
        query_arcgis(
            url="https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/Gun_Violence_Dashboard_Police_Districts/FeatureServer/0",
            fields=["police_district"],
        )
        .to_crs(settings.REFERENCE_CRS)
        .assign(police_district=lambda df: df.police_district.apply(number_to_string))
    )


@register_geodataset
def get_zip_codes() -> gpd.GeoDataFrame:
    """ZIP Codes in Philadelphia."""
    return (
        query_arcgis(
            url="https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/Gun_Violence_Dashboard_ZIP_Codes/FeatureServer/0",
            fields=["zip_code"],
        )
        .to_crs(settings.REFERENCE_CRS)
        .assign(zip_code=lambda df: df.zip_code.apply(number_to_string))
    )


@register_geodataset
def get_council_districts() -> gpd.GeoDataFrame:
    """Council Districts in Philadelphia."""
    return (
        query_arcgis(
            url="https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/Gun_Violence_Dashboard_Council_Districts/FeatureServer/0/",
            fields=["council_district"],
        )
        .assign(council_district=lambda df: df.council_district.apply(number_to_string))
        .to_crs(settings.REFERENCE_CRS)
    )


@register_geodataset
def get_neighborhoods() -> gpd.GeoDataFrame:
    """Neighborhoods in Philadelphia."""
    return query_arcgis(
        url="https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/Gun_Violence_Dashboard_Neighborhoods/FeatureServer/0",
        fields=["neighborhood"],
    ).to_crs(settings.REFERENCE_CRS)
