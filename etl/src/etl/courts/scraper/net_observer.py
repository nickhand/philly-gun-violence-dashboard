"""Playwright network observer for UJS CaseSearch scraper.

Captures HTTP response statuses and request failures during page interactions
to support response classification.
"""

from dataclasses import dataclass, field
from typing import Any

from playwright.sync_api import Page, Request, Response


@dataclass
class NetworkObserver:
    """Observe network activity on a Playwright page.

    Captures response status codes and request failures for use in
    classification.
    """

    status_histogram: dict[int, int] = field(default_factory=dict)
    requestfailed_count: int = 0
    requestfailed_errors: list[str] = field(default_factory=list)
    _max_errors: int = 20
    _attached: bool = field(default=False, repr=False)

    def reset(self) -> None:
        """Reset all counters and error lists for a new attempt."""
        self.status_histogram.clear()
        self.requestfailed_count = 0
        self.requestfailed_errors.clear()

    def _on_response(self, response: Response) -> None:
        status = response.status
        self.status_histogram[status] = self.status_histogram.get(status, 0) + 1

    def _on_requestfailed(self, request: Request) -> None:
        self.requestfailed_count += 1
        if len(self.requestfailed_errors) < self._max_errors:
            failure = request.failure
            error_text = failure if failure else "Unknown failure"
            self.requestfailed_errors.append(f"{request.url}: {error_text}")

    def attach(self, page: Page) -> None:
        if self._attached:
            return
        page.on("response", self._on_response)
        page.on("requestfailed", self._on_requestfailed)
        self._attached = True

    def detach(self, page: Page) -> None:
        if not self._attached:
            return
        try:
            page.remove_listener("response", self._on_response)
            page.remove_listener("requestfailed", self._on_requestfailed)
        except Exception:
            pass
        self._attached = False

    def has_soft_block_status(self, blocked_codes: set[int] | None = None) -> bool:
        if blocked_codes is None:
            blocked_codes = {403, 429}
        return any(code in self.status_histogram for code in blocked_codes)

    def has_server_error_status(self, error_codes: set[int] | None = None) -> bool:
        if error_codes is None:
            error_codes = {500, 502, 503, 504}
        return any(code in self.status_histogram for code in error_codes)

    def get_snapshot(self) -> dict[str, Any]:
        return {
            "status_histogram": dict(self.status_histogram),
            "requestfailed_count": self.requestfailed_count,
            "requestfailed_errors": list(self.requestfailed_errors),
        }
