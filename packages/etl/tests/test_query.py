"""Tests for bounded external geodata queries."""

from collections.abc import Callable
from typing import Any, cast
from urllib.parse import parse_qs

import httpx2 as httpx
import pytest

from etl.utils.query import CARTO, query_arcgis, query_carto

SERVICE_URL = "https://example.test/FeatureServer/0"


def _carto_collection(features: list[dict[str, object]]) -> dict[str, object]:
    return {"type": "FeatureCollection", "features": features}


def _carto_point(identifier: int) -> dict[str, object]:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [-75.0, 40.0]},
        "properties": {"id": identifier},
    }


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), timeout=1.0)


def _point_feature(identifier: int) -> dict[str, object]:
    return {
        "attributes": {"id": identifier, "OBJECTID": identifier},
        "geometry": {"x": -75.0 - identifier / 100, "y": 40.0},
    }


def _id_snapshot(object_ids: list[object]) -> dict[str, object]:
    return {"objectIdFieldName": "OBJECTID", "objectIds": object_ids}


def _request_parameters(request: httpx.Request) -> dict[str, str]:
    parameters = dict(request.url.params)
    if request.content:
        parameters.update(
            {name: values[-1] for name, values in parse_qs(request.content.decode()).items()}
        )
    return parameters


def test_query_carto_does_not_mutate_fields_and_uses_injected_client() -> None:
    """Adding the required geometry field must not surprise the caller."""
    requested_fields = ["id"]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_carto_collection([_carto_point(1)]))

    with _client(handler) as client:
        result = query_carto(
            "shootings",
            fields=requested_fields,
            limit=1,
            http_client=client,
        )

    assert requested_fields == ["id"]
    assert result["id"].tolist() == [1]
    assert len(requests) == 1
    assert str(requests[0].url).startswith(CARTO)
    assert requests[0].url.params["q"] == "SELECT id,the_geom FROM shootings LIMIT 1"


def test_query_carto_zero_limit_is_empty_without_network() -> None:
    """Zero means zero records rather than the old accidental unbounded query."""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("limit=0 must not make a network request")

    with _client(handler) as client:
        result = query_carto("shootings", fields=["id"], limit=0, http_client=client)

    assert result.empty
    assert list(result.columns) == ["id", "geometry"]
    assert result.crs is not None
    assert result.crs.to_epsg() == 4326


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"table_name": "shootings; DROP TABLE x"}, "table identifier"),
        ({"table_name": "shootings", "fields": ["id, bad"]}, "field identifier"),
        ({"table_name": "shootings", "limit": -1}, "non-negative"),
        ({"table_name": "shootings", "method": "DELETE"}, "Unsupported method"),
    ],
)
def test_query_carto_rejects_invalid_contract_before_network(
    kwargs: dict[str, object],
    message: str,
) -> None:
    """Invalid query contracts fail before reaching the external service."""
    with pytest.raises(ValueError, match=message):
        query_carto(**cast(Any, kwargs))


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"rows": []}, "FeatureCollection"),
        ({"type": "FeatureCollection"}, "features list"),
        (_carto_collection([{"type": "not-a-feature"}]), "feature 0"),
        ({"error": ["source unavailable"]}, "reported an error"),
    ],
)
def test_query_carto_rejects_malformed_source_payload(
    payload: dict[str, object],
    message: str,
) -> None:
    """CARTO's HTTP success is not enough to publish malformed data."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    with _client(handler) as client, pytest.raises(ValueError, match=message):
        query_carto("shootings", http_client=client)


def test_query_carto_rejects_http_and_json_failures() -> None:
    def unavailable(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    with _client(unavailable) as client, pytest.raises(httpx.HTTPStatusError):
        query_carto("shootings", http_client=client)

    def invalid_json(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    with (
        _client(invalid_json) as client,
        pytest.raises(ValueError, match="CARTO query response was not valid JSON"),
    ):
        query_carto("shootings", http_client=client)


def test_query_carto_retries_transient_server_failure(monkeypatch) -> None:
    attempts = 0
    sleeps: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503, text="temporarily unavailable")
        return httpx.Response(200, json=_carto_collection([_carto_point(1)]))

    monkeypatch.setattr("etl.utils.query.time.sleep", sleeps.append)
    with _client(handler) as client:
        result = query_carto("shootings", fields=["id"], http_client=client)

    assert result["id"].tolist() == [1]
    assert attempts == 3
    assert sleeps == [1.0, 2.0]


def test_query_arcgis_returns_typed_empty_result() -> None:
    """A legitimate zero-count query must not try to concatenate no pages."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/query"):
            return httpx.Response(200, json=_id_snapshot([]))
        return httpx.Response(200, json={"maxRecordCount": 2})

    with _client(handler) as client:
        result = query_arcgis(SERVICE_URL, fields=["id"], http_client=client)

    assert result.empty
    assert list(result.columns) == ["id", "geometry"]
    assert result.crs is not None
    assert result.crs.to_epsg() == 4326


def test_query_arcgis_rejects_deleted_snapshot_member() -> None:
    """A deletion after the ID snapshot is corruption, not silent truncation."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/query"):
            if _request_parameters(request).get("returnIdsOnly") == "true":
                return httpx.Response(200, json=_id_snapshot([1, 2]))
            return httpx.Response(200, json={"features": []})
        return httpx.Response(200, json={"maxRecordCount": 2})

    with _client(handler) as client, pytest.raises(RuntimeError, match="source changed.*missing"):
        query_arcgis(SERVICE_URL, http_client=client)


def test_query_arcgis_fetches_one_sorted_object_id_snapshot_in_exact_chunks() -> None:
    """Mutable offsets cannot skip or duplicate snapshotted records."""
    chunks: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if not request.url.path.endswith("/query"):
            return httpx.Response(200, json={"maxRecordCount": 2})
        parameters = _request_parameters(request)
        if parameters.get("returnIdsOnly") == "true":
            return httpx.Response(200, json=_id_snapshot([3, 1, 2]))
        assert request.method == "POST"
        chunk = parameters["objectIds"]
        chunks.append(chunk)
        identifiers = [int(value) for value in reversed(chunk.split(","))]
        return httpx.Response(
            200,
            json={"features": [_point_feature(identifier) for identifier in identifiers]},
        )

    with _client(handler) as client:
        result = query_arcgis(SERVICE_URL, fields=["id"], http_client=client)

    assert chunks == ["1,2", "3"]
    assert result["id"].tolist() == [1, 2, 3]
    assert "OBJECTID" not in result.columns
    assert result.crs is not None
    assert result.crs.to_epsg() == 4326


def test_query_arcgis_rejects_page_that_exceeds_remaining_limit() -> None:
    """A broken service must not make a bounded query return extra records."""

    def handler(request: httpx.Request) -> httpx.Response:
        if not request.url.path.endswith("/query"):
            return httpx.Response(200, json={"maxRecordCount": 2})
        parameters = _request_parameters(request)
        if parameters.get("returnIdsOnly") == "true":
            return httpx.Response(200, json=_id_snapshot(list(range(1, 11))))
        assert parameters["objectIds"] == "1"
        return httpx.Response(
            200,
            json={"features": [_point_feature(1), _point_feature(2)]},
        )

    with (
        _client(handler) as client,
        pytest.raises(RuntimeError, match="source changed.*unexpected"),
    ):
        query_arcgis(SERVICE_URL, fields=["id"], limit=1, http_client=client)


@pytest.mark.parametrize(
    ("snapshot", "message"),
    [
        ({"objectIds": [1]}, "objectIdFieldName"),
        ({"objectIdFieldName": "OBJECTID"}, "objectIds list"),
        (_id_snapshot([1, "2"]), "non-integer"),
        (_id_snapshot([1, 1]), "duplicate object IDs"),
        ({"error": {"message": "denied"}}, "reported an error"),
    ],
)
def test_query_arcgis_rejects_invalid_object_id_snapshot(
    snapshot: dict[str, object],
    message: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/query"):
            return httpx.Response(200, json=snapshot)
        return httpx.Response(200, json={"maxRecordCount": 2})

    with _client(handler) as client, pytest.raises(ValueError, match=message):
        query_arcgis(SERVICE_URL, http_client=client)


def test_query_arcgis_rejects_reserved_option_override_before_snapshot() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"maxRecordCount": 2})

    with _client(handler) as client, pytest.raises(ValueError, match="reserved fields"):
        query_arcgis(SERVICE_URL, http_client=client, objectIds="1")

    assert len(requests) == 1


@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        ({}, "maxRecordCount"),
        ({"maxRecordCount": 0}, "must be positive"),
        ({"error": {"message": "denied"}}, "reported an error"),
    ],
)
def test_query_arcgis_rejects_invalid_metadata(metadata: dict[str, object], message: str) -> None:
    """Malformed service metadata fails at the HTTP boundary."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=metadata)

    with _client(handler) as client, pytest.raises(ValueError, match=message):
        query_arcgis(SERVICE_URL, http_client=client)


def test_query_arcgis_rejects_negative_limit_before_network() -> None:
    """A negative operational limit is an illegal state."""
    with pytest.raises(ValueError, match="non-negative"):
        query_arcgis(SERVICE_URL, limit=-1)
