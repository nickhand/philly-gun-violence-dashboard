import geopandas as gpd

from dashboard_utils.constants import REFERENCE_CRS
from dashboard_utils.registry import register_geodataset
from etl.utils.query import query_arcgis


@register_geodataset
def get_street_centerlines() -> gpd.GeoDataFrame:
    """Street centerlines in Philadelphia."""
    return (
        query_arcgis(
            url="https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/Street_Centerline/FeatureServer/0",
            fields=["stname", "l_hundred"],
        )
        .rename(columns={"stname": "street_name", "l_hundred": "block_number"})
        .to_crs(REFERENCE_CRS)
    )
