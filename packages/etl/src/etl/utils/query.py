import re
import time
import warnings
from typing import Any, Literal

import geopandas as gpd
import httpx2 as httpx
import pandas as pd
from arcgis2geojson import arcgis2geojson

CARTO = "https://phl.carto.com/api/v2/sql"
HTTP_TIMEOUT = httpx.Timeout(60.0, connect=15.0)
HTTP_CONNECT_RETRIES = 2
HTTP_MAX_ATTEMPTS = 3
HTTP_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
SQL_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")


def query_carto(
    table_name: str,
    fields: list[str] | None = None,
    where: str | None = None,
    limit: int | None = None,
    method: Literal["GET", "POST"] = "GET",
    *,
    http_client: httpx.Client | None = None,
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
    if not SQL_IDENTIFIER.fullmatch(table_name):
        raise ValueError(f"Invalid CARTO table identifier: {table_name!r}")
    if limit is not None and limit < 0:
        raise ValueError("CARTO query limit must be non-negative")
    if method not in {"GET", "POST"}:
        raise ValueError(f"Unsupported method: {method}; use 'GET' or 'POST'")

    selected_fields = ["*"] if fields is None else list(fields)
    if not selected_fields:
        raise ValueError("CARTO fields must not be empty")
    if "*" in selected_fields and selected_fields != ["*"]:
        raise ValueError("CARTO wildcard must be the only selected field")
    invalid_fields = [
        field for field in selected_fields if field != "*" and not SQL_IDENTIFIER.fullmatch(field)
    ]
    if invalid_fields:
        raise ValueError(f"Invalid CARTO field identifier(s): {invalid_fields}")
    if selected_fields != ["*"] and "the_geom" not in selected_fields:
        selected_fields.append("the_geom")

    if limit == 0:
        result_fields = [field for field in selected_fields if field not in {"*", "the_geom"}]
        return _empty_geo_frame(result_fields)

    if http_client is not None:
        return _query_carto(
            http_client,
            table_name=table_name,
            fields=selected_fields,
            where=where,
            limit=limit,
            method=method,
        )

    transport = httpx.HTTPTransport(retries=HTTP_CONNECT_RETRIES)
    with httpx.Client(timeout=HTTP_TIMEOUT, transport=transport) as client:
        return _query_carto(
            client,
            table_name=table_name,
            fields=selected_fields,
            where=where,
            limit=limit,
            method=method,
        )


def _query_carto(
    client: httpx.Client,
    *,
    table_name: str,
    fields: list[str],
    where: str | None,
    limit: int | None,
    method: Literal["GET", "POST"],
) -> gpd.GeoDataFrame:
    """Execute one validated CARTO SQL request through an injected client."""
    # Join the fields into a string
    fields_str = ",".join(fields)

    # make the SQL query
    query = f"SELECT {fields_str} FROM {table_name}"
    if where:
        query += f" WHERE {where}"
    if limit is not None:
        query += f" LIMIT {limit}"

    params = {"q": query, "format": "geojson", "skipfields": "cartodb_id"}
    if method == "GET":
        response = _request_with_retries(
            client,
            "GET",
            CARTO,
            params=params,
            headers={"Content-Type": "application/json;charset=UTF-8"},
        )
    else:
        response = _request_with_retries(client, "POST", CARTO, data=params)

    payload = _response_object(response, context="CARTO query")
    if payload.get("type") != "FeatureCollection":
        raise ValueError("CARTO response must be a GeoJSON FeatureCollection")
    features = payload.get("features")
    if not isinstance(features, list):
        raise ValueError("CARTO FeatureCollection must contain a features list")
    if limit is not None and len(features) > limit:
        raise ValueError("CARTO response exceeded the requested limit")
    for index, feature in enumerate(features):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ValueError(f"CARTO feature {index} is invalid")

    if not features:
        result_fields = [field for field in fields if field not in {"*", "the_geom"}]
        return _empty_geo_frame(result_fields)
    try:
        return gpd.GeoDataFrame.from_features(payload, crs="EPSG:4326")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("CARTO response contains invalid GeoJSON features") from exc


def query_arcgis(
    url: str,
    fields: list[str] | None = None,
    where: str | None = None,
    limit: int | None = None,
    *,
    http_client: httpx.Client | None = None,
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
    http_client : httpx.Client, optional
        An injected HTTP client. Primarily useful for tests and callers that
        manage their own connection pool.
    **kwargs : dict, optional
        additional keyword arguments to pass to the ArcGIS query

    Example
    -------
    >>> url = "https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/Philadelphia_ZCTA_2018/FeatureServer/0"
    >>> gdf = query_arcgis(url, fields=["zip_code"], where="zip_code=19123")
    >>> gdf
    """
    if limit is not None and limit < 0:
        raise ValueError("ArcGIS query limit must be non-negative")

    if http_client is not None:
        return _query_arcgis(http_client, url, fields, where, limit, kwargs)

    transport = httpx.HTTPTransport(retries=HTTP_CONNECT_RETRIES)
    with httpx.Client(timeout=HTTP_TIMEOUT, transport=transport) as client:
        return _query_arcgis(client, url, fields, where, limit, kwargs)


def _response_object(response: httpx.Response, *, context: str) -> dict[str, Any]:
    """Return one validated external-service JSON object."""
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError(f"{context} response was not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{context} response must be a JSON object")
    if "error" in payload:
        raise ValueError(f"{context} response reported an error: {payload['error']!r}")
    return payload


def _request_with_retries(
    client: httpx.Client,
    method: Literal["GET", "POST"],
    url: str,
    **kwargs: Any,
) -> httpx.Response:
    """Retry transient network/server failures with a finite backoff."""
    for attempt in range(HTTP_MAX_ATTEMPTS):
        try:
            response = client.request(method, url, **kwargs)
        except (httpx.NetworkError, httpx.TimeoutException):
            if attempt == HTTP_MAX_ATTEMPTS - 1:
                raise
        else:
            if response.status_code not in HTTP_RETRYABLE_STATUS:
                return response
            if attempt == HTTP_MAX_ATTEMPTS - 1:
                return response
        time.sleep(float(2**attempt))
    raise RuntimeError("External HTTP retry loop exhausted unexpectedly")


def _empty_geo_frame(fields: list[str] | None) -> gpd.GeoDataFrame:
    """Return a typed empty external-source result with WGS84 geometry."""
    data = {field: pd.Series(dtype="object") for field in dict.fromkeys(fields or [])}
    data["geometry"] = gpd.GeoSeries([], crs="EPSG:4326")
    return gpd.GeoDataFrame(data, geometry="geometry", crs="EPSG:4326")


def _query_arcgis(
    client: httpx.Client,
    url: str,
    fields: list[str] | None,
    where: str | None,
    limit: int | None,
    query_options: dict[str, Any],
) -> gpd.GeoDataFrame:
    """Execute a deterministic query against one snapshotted object-ID set."""
    metadata = _response_object(
        _request_with_retries(client, "GET", url, params={"f": "pjson"}),
        context="ArcGIS metadata",
    )
    try:
        max_record_count = int(metadata["maxRecordCount"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("ArcGIS metadata is missing a valid maxRecordCount") from exc
    if max_record_count <= 0:
        raise ValueError("ArcGIS maxRecordCount must be positive")

    reserved_options = {
        "f",
        "objectIds",
        "orderByFields",
        "outFields",
        "outSR",
        "resultOffset",
        "resultRecordCount",
        "returnCountOnly",
        "returnIdsOnly",
        "where",
    }
    overridden = sorted(reserved_options.intersection(query_options))
    if overridden:
        raise ValueError(f"ArcGIS query options cannot override reserved fields: {overridden}")

    # default behavior matches all features
    if where is None:
        where = "1=1"

    if fields is not None and not fields:
        raise ValueError("ArcGIS fields must not be empty")

    query_url = f"{url.rstrip('/')}/query"

    # ArcGIS documents the ID-only result as unbounded by maxRecordCount. Capture
    # membership once, then fetch only these immutable identifiers. Inserts after
    # this point are intentionally excluded; deletes are detected as corruption.
    response = _request_with_retries(
        client,
        "GET",
        query_url,
        params={"where": where, "returnIdsOnly": "true", "f": "json"},
    )
    ids_payload = _response_object(response, context="ArcGIS object ID snapshot")
    object_id_field = ids_payload.get("objectIdFieldName")
    if not isinstance(object_id_field, str) or not object_id_field.strip():
        raise ValueError("ArcGIS object ID snapshot is missing objectIdFieldName")
    raw_object_ids = ids_payload.get("objectIds")
    if not isinstance(raw_object_ids, list):
        raise ValueError("ArcGIS object ID snapshot is missing an objectIds list")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in raw_object_ids):
        raise ValueError("ArcGIS object ID snapshot contains a non-integer object ID")
    if len(set(raw_object_ids)) != len(raw_object_ids):
        raise ValueError("ArcGIS object ID snapshot contains duplicate object IDs")
    object_ids = sorted(raw_object_ids)

    # Check the limit
    if limit is not None:
        object_ids = object_ids[:limit]
    total_size = len(object_ids)
    if total_size == 0:
        return _empty_geo_frame(fields)

    requested_fields = None if fields is None else list(fields)
    fetch_fields = ["*"] if requested_fields is None else list(requested_fields)
    if fetch_fields != ["*"] and object_id_field.casefold() not in {
        field.casefold() for field in fetch_fields
    }:
        fetch_fields.append(object_id_field)
    params: dict[str, Any] = dict(
        f="json",
        outSR="4326",
        outFields=",".join(fetch_fields),
        **query_options,
    )

    calls = (total_size + max_record_count - 1) // max_record_count
    if calls > 10:
        warnings.warn(
            f"Long download time — total download will require {calls} separate requests",
            stacklevel=2,
        )

    out: list[gpd.GeoDataFrame] = []
    for start in range(0, total_size, max_record_count):
        requested_ids = object_ids[start : start + max_record_count]
        params["objectIds"] = ",".join(str(value) for value in requested_ids)

        # Exact-ID batches can exceed conservative proxy URL limits. ArcGIS
        # query endpoints accept form-encoded POSTs, which keep the snapshot
        # membership out of the request target without changing semantics.
        response = _request_with_retries(client, "POST", query_url, data=params)
        page_payload = _response_object(response, context="ArcGIS feature page")
        features = page_payload.get("features")
        if not isinstance(features, list):
            raise ValueError("ArcGIS feature page is missing a features list")
        by_id: dict[int, dict[str, Any]] = {}
        for index, feature in enumerate(features):
            if not isinstance(feature, dict):
                raise ValueError(f"ArcGIS feature page contains an invalid feature at {index}")
            attributes = feature.get("attributes")
            if not isinstance(attributes, dict):
                raise ValueError(f"ArcGIS feature page contains invalid attributes at {index}")
            object_id = attributes.get(object_id_field)
            if isinstance(object_id, bool) or not isinstance(object_id, int):
                raise ValueError(f"ArcGIS feature page has no valid object ID at {index}")
            if object_id in by_id:
                raise ValueError(f"ArcGIS feature page returned duplicate object ID {object_id}")
            by_id[object_id] = feature
        if set(by_id) != set(requested_ids):
            missing = sorted(set(requested_ids) - set(by_id))
            unexpected = sorted(set(by_id) - set(requested_ids))
            raise RuntimeError(
                "ArcGIS source changed during its object-ID snapshot fetch: "
                f"missing={missing}, unexpected={unexpected}"
            )

        try:
            geojson = [arcgis2geojson(by_id[object_id]) for object_id in requested_ids]
            gdf = gpd.GeoDataFrame.from_features(geojson, crs="EPSG:4326")
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("ArcGIS feature page contains invalid features") from exc
        out.append(gdf)

    combined = pd.concat(out, axis=0, ignore_index=True)
    result = gpd.GeoDataFrame(combined, geometry="geometry", crs="EPSG:4326")
    if (
        requested_fields is not None
        and requested_fields != ["*"]
        and object_id_field.casefold() not in {field.casefold() for field in requested_fields}
    ):
        result = result.drop(columns=[object_id_field])
    return result
