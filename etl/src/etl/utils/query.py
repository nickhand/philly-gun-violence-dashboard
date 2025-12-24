import urllib
import warnings
from typing import Any, Literal

import geopandas as gpd
import httpx
import pandas as pd
from arcgis2geojson import arcgis2geojson

CARTO = "https://phl.carto.com/api/v2/sql"


def query_carto(
    table_name: str,
    fields: list[str] | None = None,
    where: str | None = None,
    limit: int | None = None,
    method: Literal["GET", "POST"] = "GET",
) -> gpd.GeoDataFrame:
    """
    Query a CARTO database API, returning a GeoDataFrame.

    Parameters
    ----------
    table_name : str
        the name of the database table to query
    fields : list of str, optional
        the name of the fields to return; the default behavior returns
        all fields
    where : str, optional
        the where clause to select a subset of the data
    limit : int, optional
        limit the returned data to this many features
    method : {'GET', 'POST'}, optional
        the HTTP method to use for the request; default is 'GET'

    Example
    -------
    >>> where = "date_ > current_date - 30"
    >>> gdf = query_carto("shootings", fields=["age", "fatal"], where=where, limit=5)
    >>> gdf
    """
    if fields is None:
        fields = ["*"]
    elif "the_geom" not in fields:
        fields.append("the_geom")

    # Join the fields into a string
    fields_str = ",".join(fields)

    # make the SQL query
    query = f"SELECT {fields_str} FROM {table_name}"
    if where:
        query += f" WHERE {where}"
    if limit:
        query += f" LIMIT {limit}"

    # Put in the request to the CARTO API
    params = dict(q=query, format="geojson", skipfields=["cartodb_id"])
    if method == "GET":
        r = httpx.get(
            CARTO,
            params=urllib.parse.urlencode(params, quote_via=urllib.parse.quote),
            headers={"Content-Type": "application/json;charset=UTF-8"},
        )
    elif method == "POST":
        r = httpx.post(CARTO, data=params)
    else:
        raise ValueError(f"Unsupported method: {method}; use 'GET' or 'POST'")

    # Check for errors
    r.raise_for_status()

    # Convert to a GeoDataFrame and return
    return gpd.GeoDataFrame.from_features(r.json(), crs="EPSG:4326")


def query_arcgis(
    url: str,
    fields: list[str] | None = None,
    where: str | None = None,
    limit: int | None = None,
    **kwargs: Any,
) -> gpd.GeoDataFrame:
    """
    Scrape features from a ArcGIS Server REST API and return a GeoDataFrame.

    Parameters
    ----------
    url : str
        the REST API url for the Feature Service
    fields : list of str, optional
        the list of fields to include; the default behavior ('None')
        returns all fields
    where : str, optional
        a string specifying the selection clause to select a subset of
        data; the default behavior ('None') selects all data
    limit : int, optional
        limit the returned data to this many features
    **kwargs : dict, optional
        additional keyword arguments to pass to the ArcGIS query

    Example
    -------
    >>> url = "https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/Philadelphia_ZCTA_2018/FeatureServer/0"
    >>> gdf = query_arcgis(url, fields=["zip_code"], where="zip_code=19123")
    >>> gdf
    """
    # Get the max record count
    metadata = httpx.get(url, params=dict(f="pjson")).json()
    max_record_count = metadata["maxRecordCount"]

    # default behavior matches all features
    if where is None:
        where = "1=1"

    # Return all fields or list of fields
    fields_combined = "*" if fields is None else ", ".join(fields)

    # Extract object IDs of features
    queryURL = f"{url}/query"

    # Get the total record count
    response = httpx.get(
        queryURL,
        params=dict(
            where=where,
            returnCountOnly="true",
            f="json",
        ),
    )
    response.raise_for_status()
    total_size = response.json()["count"]

    # Check the limit
    if limit is not None:
        total_size = min(limit, total_size)

    # Params for this request
    resultOffset = 0
    params = dict(
        f="json",
        outSR="4326",
        outFields=fields_combined,
        resultOffset=resultOffset,
        where=where,
        **kwargs,
    )

    calls = total_size // max_record_count
    if calls > 10:
        warnings.warn(
            f"Long download time — total download will require {calls} separate requests",
            stacklevel=2,
        )

    out = []
    while params["resultOffset"] < total_size:
        remaining = total_size - params["resultOffset"]
        if remaining < max_record_count:
            params["resultRecordCount"] = remaining

        # Get raw features
        response = httpx.get(queryURL, params=params)
        response.raise_for_status()
        json = response.json()

        # Convert to GeoJSON and save
        geojson = [arcgis2geojson(f) for f in json["features"]]
        gdf = gpd.GeoDataFrame.from_features(geojson, crs="EPSG:4326")
        out.append(gdf)

        params["resultOffset"] += len(out[-1])

    return gpd.GeoDataFrame(pd.concat(out, axis=0).reset_index(drop=True))
