import geopandas as gpd

from etl.config import settings
from etl.utils.query import query_carto


def fetch_shootings() -> gpd.GeoDataFrame:
    """Load shooting victims data from CARTO.

    Notes
    -----
    See https://www.opendataphilly.org/dataset/shooting-victims
    """
    return query_carto(
        table_name="shootings",
        method="GET",
    ).to_crs(settings.REFERENCE_CRS)


def fetch_criminal_incidents(
    *,
    fields: list[str] | None = None,
    where: str | None = None,
) -> gpd.GeoDataFrame:
    """Load criminal incidents data from CARTO.

    Notes
    -----
    See https://www.opendataphilly.org/dataset/criminal-incidents
    """
    return query_carto(
        table_name="incidents_part1_part2",
        method="POST",
        fields=fields,
        where=where,
    ).to_crs(settings.REFERENCE_CRS)
