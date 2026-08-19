"""Fail-closed browser-origin enforcement for the public UJS portal."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import SplitResult, urlsplit

from playwright.sync_api import Page, Request, Route, WebSocketRoute

PORTAL_HOST = "ujsportal.pacourts.us"


class PortalOriginPolicyError(RuntimeError):
    """A browser request or final page escaped the reviewed UJS origin."""


def _split_allowed_url(url: object) -> SplitResult | None:
    if not isinstance(url, str):
        return None
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname != PORTAL_HOST
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return parsed


def is_allowed_portal_url(url: object) -> bool:
    """Return whether a URL belongs to the one permitted HTTPS portal origin."""
    return _split_allowed_url(url) is not None


def _redacted_origin(url: object) -> str:
    if not isinstance(url, str):
        return "<non-string URL>"
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return "<malformed URL>"
    host = parsed.hostname or "<missing-host>"
    suffix = f":{port}" if port is not None else ""
    return f"{parsed.scheme or '<missing-scheme>'}://{host}{suffix}"


@dataclass
class PortalOriginPolicy:
    """Abort every browser request outside the exact public UJS HTTPS origin."""

    _violations: list[str] = field(default_factory=list, init=False, repr=False)

    def handle_route(self, route: Route, request: Request) -> None:
        """Continue one allowed request or abort and retain a policy violation."""
        if is_allowed_portal_url(request.url):
            route.continue_()
            return
        if len(self._violations) < 10:
            self._violations.append(_redacted_origin(request.url))
        route.abort("blockedbyclient")

    def handle_websocket(self, websocket: WebSocketRoute) -> None:
        """Record and close every WebSocket; the live portal requires none."""
        if len(self._violations) < 10:
            self._violations.append(_redacted_origin(websocket.url))
        websocket.close(code=1008, reason="WebSocket disabled by courts origin policy")

    def assert_page(self, page: Page) -> None:
        """Reject an attempted escape or an off-origin final page."""
        if self._violations:
            raise PortalOriginPolicyError(
                f"Browser attempted a request outside the UJS origin: {self._violations[0]}"
            )
        if not is_allowed_portal_url(page.url):
            raise PortalOriginPolicyError(
                f"Browser final page escaped the UJS origin: {_redacted_origin(page.url)}"
            )

    @property
    def violations(self) -> tuple[str, ...]:
        """Return redacted attempted origins for diagnostics and tests."""
        return tuple(self._violations)
