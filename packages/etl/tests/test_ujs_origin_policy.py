"""Tests for the courts browser's exact-origin network policy."""

from unittest.mock import MagicMock

import pytest

from etl.courts.scraper.origin_policy import (
    PortalOriginPolicy,
    PortalOriginPolicyError,
    is_allowed_portal_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://ujsportal.pacourts.us/CaseSearch",
        "https://ujsportal.pacourts.us:443/resource/site.css?v=1",
    ],
)
def test_exact_ujs_https_origin_is_allowed(url: str) -> None:
    assert is_allowed_portal_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://ujsportal.pacourts.us/CaseSearch",
        "https://ujsportal.pacourts.us.evil.example/CaseSearch",
        "https://evil.example/",
        "https://ujsportal.pacourts.us:444/CaseSearch",
        "https://user@ujsportal.pacourts.us/CaseSearch",
        "data:text/plain,hello",
        "not a URL",
        None,
    ],
)
def test_every_other_origin_or_malformed_url_is_rejected(url: object) -> None:
    assert not is_allowed_portal_url(url)


def test_route_aborts_off_origin_and_retains_only_redacted_origin() -> None:
    policy = PortalOriginPolicy()
    route = MagicMock()
    request = MagicMock()
    request.url = "https://evil.example/private?incident=secret-value"

    policy.handle_route(route, request)

    route.abort.assert_called_once_with("blockedbyclient")
    route.continue_.assert_not_called()
    assert policy.violations == ("https://evil.example",)
    page = MagicMock(url="https://ujsportal.pacourts.us/CaseSearch")
    with pytest.raises(PortalOriginPolicyError) as exc_info:
        policy.assert_page(page)
    assert "secret-value" not in str(exc_info.value)


def test_route_continues_allowed_origin_and_final_page_must_remain_allowed() -> None:
    policy = PortalOriginPolicy()
    route = MagicMock()
    request = MagicMock(url="https://ujsportal.pacourts.us/resource/site.css")

    policy.handle_route(route, request)

    route.continue_.assert_called_once_with()
    route.abort.assert_not_called()
    policy.assert_page(MagicMock(url="https://ujsportal.pacourts.us/CaseSearch"))
    with pytest.raises(PortalOriginPolicyError, match="final page"):
        policy.assert_page(MagicMock(url="https://example.com/redirect"))


def test_every_websocket_is_closed_and_becomes_a_policy_violation() -> None:
    policy = PortalOriginPolicy()
    websocket = MagicMock(url="wss://ujsportal.pacourts.us/events?secret=value")

    policy.handle_websocket(websocket)

    websocket.close.assert_called_once_with(
        code=1008,
        reason="WebSocket disabled by courts origin policy",
    )
    assert policy.violations == ("wss://ujsportal.pacourts.us",)
    with pytest.raises(PortalOriginPolicyError) as exc_info:
        policy.assert_page(MagicMock(url="https://ujsportal.pacourts.us/CaseSearch"))
    assert "secret=value" not in str(exc_info.value)
