"""Playwright network observer for UJS CaseSearch scraper.

Captures HTTP response statuses and request failures during page interactions
to support response classification and audit logging.
"""

from dataclasses import dataclass, field

from playwright.sync_api import Page, Request, Response


@dataclass
class NetworkObserver:
    """Observe network activity on a Playwright page.

    Captures response status codes and request failures for use in
    classification and audit logging.

    Attributes
    ----------
    status_histogram : dict[int, int]
        Count of responses by HTTP status code.
    requestfailed_count : int
        Number of requests that failed.
    requestfailed_errors : list[str]
        Error messages from failed requests (bounded).
    _max_errors : int
        Maximum number of error messages to retain.
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
        """Handle a response event from Playwright.

        Parameters
        ----------
        response : Response
            The Playwright response object.
        """
        status = response.status
        self.status_histogram[status] = self.status_histogram.get(status, 0) + 1

    def _on_requestfailed(self, request: Request) -> None:
        """Handle a request failure event from Playwright.

        Parameters
        ----------
        request : Request
            The Playwright request object that failed.
        """
        self.requestfailed_count += 1

        # Capture error message if under limit
        if len(self.requestfailed_errors) < self._max_errors:
            failure = request.failure
            error_text = failure if failure else "Unknown failure"
            self.requestfailed_errors.append(f"{request.url}: {error_text}")

    def attach(self, page: Page) -> None:
        """Attach event listeners to a Playwright page.

        Parameters
        ----------
        page : Page
            The Playwright page to observe.
        """
        if self._attached:
            return

        page.on("response", self._on_response)
        page.on("requestfailed", self._on_requestfailed)
        self._attached = True

    def detach(self, page: Page) -> None:
        """Detach event listeners from a Playwright page.

        Parameters
        ----------
        page : Page
            The Playwright page to stop observing.
        """
        if not self._attached:
            return

        try:
            page.remove_listener("response", self._on_response)
            page.remove_listener("requestfailed", self._on_requestfailed)
        except Exception:
            # Ignore errors if page is already closed
            pass
        self._attached = False

    def has_soft_block_status(self, blocked_codes: set[int] | None = None) -> bool:
        """Check if any blocked status codes were observed.

        Parameters
        ----------
        blocked_codes : set[int] | None
            Status codes to consider as soft-blocked. Defaults to {403, 429}.

        Returns
        -------
        bool
            True if any blocked status codes were observed.
        """
        if blocked_codes is None:
            blocked_codes = {403, 429}
        return any(code in self.status_histogram for code in blocked_codes)

    def has_server_error_status(self, error_codes: set[int] | None = None) -> bool:
        """Check if any server error status codes were observed.

        Parameters
        ----------
        error_codes : set[int] | None
            Status codes to consider as server errors. Defaults to {500, 502, 503, 504}.

        Returns
        -------
        bool
            True if any server error status codes were observed.
        """
        if error_codes is None:
            error_codes = {500, 502, 503, 504}
        return any(code in self.status_histogram for code in error_codes)

    def get_snapshot(self) -> dict:
        """Get a snapshot of current network stats.

        Returns
        -------
        dict
            Dictionary with status_histogram, requestfailed_count, and errors.
        """
        return {
            "status_histogram": dict(self.status_histogram),
            "requestfailed_count": self.requestfailed_count,
            "requestfailed_errors": list(self.requestfailed_errors),
        }
