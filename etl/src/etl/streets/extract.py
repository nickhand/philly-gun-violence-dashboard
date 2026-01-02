import geopandas as gpd

from etl.config import REFERENCE_CRS
from etl.utils.query import query_arcgis
from etl.utils.registry import register_geodataset


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
