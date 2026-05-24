"""Offline tests for UJS classifier using HTML fixtures.

These tests do not require network access and can run in CI.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from etl.courts.scraper.classifier import (
    BLOCKED_MARKERS,
    Classification,
    ClassificationResult,
    NO_RESULTS_TEXT_MARKERS,
    PORTAL_URL,
    REDIRECT_URL_PATTERNS,
    SESSION_LOST_MARKERS,
    _check_text_markers,
    _check_url_patterns,
    classify_case_search,
)
from etl.courts.scraper.net_observer import NetworkObserver

# Path to fixtures
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "ujs"


def load_fixture(name: str) -> str:
    """Load an HTML fixture file."""
    fixture_path = FIXTURES_DIR / name
    return fixture_path.read_text()


class MockPage:
    """Mock Playwright page for testing classification."""

    def __init__(
        self,
        content: str,
        url: str = "https://ujsportal.pacourts.us/CaseSearch/Results",
        title: str = "Case Search",
    ):
        self._content = content
        self._url = url
        self._title = title
        self._selectors: dict[str, list[MagicMock]] = {}

    @property
    def url(self) -> str:
        return self._url

    def title(self) -> str:
        return self._title

    def content(self) -> str:
        return self._content

    def wait_for_selector(
        self,
        selector: str,
        timeout: int = 15000,
        state: str = "visible",
    ) -> MagicMock | None:
        """Mock wait_for_selector."""
        # Check if the selector exists in content
        if selector == "#caseSearchResultGrid":
            if "caseSearchResultGrid" in self._content:
                return MagicMock()
        raise Exception("Timeout waiting for selector")

    def query_selector_all(self, selector: str) -> list[MagicMock]:
        """Mock query_selector_all."""
        if selector == "#caseSearchResultGrid tbody tr":
            # Count actual rows in fixture
            from justhtml import JustHTML

            doc = JustHTML(self._content)
            rows = doc.query("#caseSearchResultGrid tbody tr")
            mock_rows = []
            for row in rows:
                text = row.to_text(strip=True)
                if text:
                    mock_row = MagicMock()
                    mock_row.inner_text.return_value = text
                    mock_rows.append(mock_row)
            return mock_rows
        return []


class TestTextMarkerDetection:
    """Tests for text marker detection."""

    def test_blocked_marker_found(self):
        """Should detect blocked markers in content."""
        content = "Access Denied - unusual traffic detected"
        found, marker = _check_text_markers(content, BLOCKED_MARKERS)
        assert found is True
        assert marker is not None

    def test_blocked_marker_not_found(self):
        """Should not detect blocked markers in clean content."""
        content = "Case Search Results - 5 records found"
        found, marker = _check_text_markers(content, BLOCKED_MARKERS)
        assert found is False
        assert marker is None

    def test_no_results_marker_found(self):
        """Should detect no results markers."""
        content = "No results found for your search criteria"
        found, marker = _check_text_markers(content, NO_RESULTS_TEXT_MARKERS)
        assert found is True
        assert marker is not None

    def test_session_lost_marker_found(self):
        """Should detect session lost markers."""
        content = "Your session has expired. Please log in again."
        found, marker = _check_text_markers(content, SESSION_LOST_MARKERS)
        assert found is True
        assert marker is not None


class TestURLPatternDetection:
    """Tests for URL pattern detection."""

    def test_redirect_pattern_found(self):
        """Should detect redirect URL patterns."""
        url = "https://ujsportal.pacourts.us/Login?returnUrl=/CaseSearch"
        found, pattern = _check_url_patterns(url, REDIRECT_URL_PATTERNS)
        assert found is True
        assert pattern is not None

    def test_redirect_pattern_not_found(self):
        """Should not detect redirect in normal search URL."""
        url = "https://ujsportal.pacourts.us/CaseSearch"
        found, pattern = _check_url_patterns(url, REDIRECT_URL_PATTERNS)
        assert found is False
        assert pattern is None


class TestClassifierWithFixtures:
    """Tests for classifier using HTML fixtures."""

    def test_classify_results_with_rows(self):
        """Should classify page with results as HAS_RESULTS."""
        content = load_fixture("results_with_rows.html")
        page = MockPage(content)
        observer = NetworkObserver()

        # Mock wait_for_selector to succeed
        with patch.object(page, "wait_for_selector", return_value=MagicMock()):
            result = classify_case_search(page, observer, results_wait_timeout_ms=100)

        assert result.classification == Classification.HAS_RESULTS
        assert result.row_count is not None
        assert result.row_count > 0
        assert result.marker_hits is not None
        assert result.marker_hits.get("results_container") is True
        assert result.marker_hits.get("has_rows") is True

    def test_classify_no_results(self):
        """Should classify page with no results as ZERO_RESULTS."""
        content = load_fixture("no_results.html")
        page = MockPage(content)
        observer = NetworkObserver()

        # Mock wait_for_selector to succeed (container exists)
        with patch.object(page, "wait_for_selector", return_value=MagicMock()):
            result = classify_case_search(page, observer, results_wait_timeout_ms=100)

        assert result.classification == Classification.ZERO_RESULTS
        assert result.row_count == 0
        assert result.marker_hits is not None
        assert result.marker_hits.get("no_results_text") is True

    def test_classify_blocked_interstitial(self):
        """Should classify blocked page as SOFT_BLOCKED."""
        content = load_fixture("blocked_interstitial.html")
        page = MockPage(content, title="Access Denied")
        observer = NetworkObserver()

        result = classify_case_search(page, observer, results_wait_timeout_ms=100)

        assert result.classification == Classification.SOFT_BLOCKED
        assert result.marker_hits is not None
        assert result.marker_hits.get("blocked_marker") is True

    def test_classify_redirected_landing(self):
        """Should classify landing page redirect as REDIRECTED_OR_SESSION_LOST."""
        content = load_fixture("redirected_landing.html")
        page = MockPage(content, url=PORTAL_URL)
        observer = NetworkObserver()

        result = classify_case_search(page, observer, results_wait_timeout_ms=100)

        # Should detect session lost or landing page
        assert result.classification in {
            Classification.REDIRECTED_OR_SESSION_LOST,
            Classification.UI_DRIFT_OR_UNKNOWN,
        }

    def test_classify_ui_drift(self):
        """Should classify unexpected UI as UI_DRIFT_OR_UNKNOWN."""
        content = load_fixture("ui_drift.html")
        page = MockPage(content)
        observer = NetworkObserver()

        result = classify_case_search(page, observer, results_wait_timeout_ms=100)

        assert result.classification == Classification.UI_DRIFT_OR_UNKNOWN

    def test_classify_with_403_status(self):
        """Should classify 403 responses as SOFT_BLOCKED."""
        content = "<html><body>Forbidden</body></html>"
        page = MockPage(content)
        observer = NetworkObserver()
        observer.status_histogram[403] = 1

        result = classify_case_search(page, observer, results_wait_timeout_ms=100)

        assert result.classification == Classification.SOFT_BLOCKED
        assert result.marker_hits is not None
        assert result.marker_hits.get("soft_block_status") is True

    def test_classify_with_429_status(self):
        """Should classify 429 responses as SOFT_BLOCKED."""
        content = "<html><body>Too Many Requests</body></html>"
        page = MockPage(content)
        observer = NetworkObserver()
        observer.status_histogram[429] = 1

        result = classify_case_search(page, observer, results_wait_timeout_ms=100)

        assert result.classification == Classification.SOFT_BLOCKED

    def test_classify_with_server_error(self):
        """Should classify 5xx responses as NETWORK_OR_SERVER_ERROR."""
        content = "<html><body>Internal Server Error</body></html>"
        page = MockPage(content)
        observer = NetworkObserver()
        observer.status_histogram[500] = 1

        result = classify_case_search(page, observer, results_wait_timeout_ms=100)

        assert result.classification == Classification.NETWORK_OR_SERVER_ERROR
        assert result.marker_hits is not None
        assert result.marker_hits.get("server_error_status") is True

    def test_visible_results_beat_noncritical_request_failure(self):
        """Visible result rows should win over generic failed asset requests."""
        content = load_fixture("results_with_rows.html")
        page = MockPage(content)
        observer = NetworkObserver()
        observer.requestfailed_count = 1
        observer.requestfailed_errors.append("https://example.invalid/tracker.js: failed")

        with patch.object(page, "wait_for_selector", return_value=MagicMock()):
            result = classify_case_search(page, observer, results_wait_timeout_ms=100)

        assert result.classification == Classification.HAS_RESULTS


class TestClassificationResult:
    """Tests for ClassificationResult dataclass."""

    def test_is_retryable_has_results(self):
        """HAS_RESULTS should not be retryable."""
        result = ClassificationResult(
            classification=Classification.HAS_RESULTS,
            row_count=5,
        )
        assert result.is_retryable is False
        assert result.is_success is True

    def test_is_retryable_zero_results(self):
        """ZERO_RESULTS should not be retryable."""
        result = ClassificationResult(
            classification=Classification.ZERO_RESULTS,
            row_count=0,
        )
        assert result.is_retryable is False
        assert result.is_success is True

    def test_is_retryable_soft_blocked(self):
        """SOFT_BLOCKED should be retryable."""
        result = ClassificationResult(
            classification=Classification.SOFT_BLOCKED,
        )
        assert result.is_retryable is True
        assert result.is_success is False

    def test_is_retryable_network_error(self):
        """NETWORK_OR_SERVER_ERROR should be retryable."""
        result = ClassificationResult(
            classification=Classification.NETWORK_OR_SERVER_ERROR,
        )
        assert result.is_retryable is True
        assert result.is_success is False

    def test_to_dict(self):
        """Should convert to JSON-serializable dict."""
        result = ClassificationResult(
            classification=Classification.HAS_RESULTS,
            subreason="Found 5 rows",
            row_count=5,
            final_url="https://example.com",
            marker_hits={"results_container": True},
            status_histogram={200: 10},
            requestfailed_count=0,
            elapsed_ms=1500,
        )
        d = result.to_dict()
        assert d["classification"] == "HAS_RESULTS"
        assert d["row_count"] == 5
        assert d["marker_hits"]["results_container"] is True
