"""Tests for network observer."""

from unittest.mock import MagicMock

from etl.courts.verification.net_observer import NetworkObserver


class TestNetworkObserver:
    """Tests for NetworkObserver."""

    def test_initial_state(self):
        """Should start with empty counters."""
        observer = NetworkObserver()
        assert observer.status_histogram == {}
        assert observer.requestfailed_count == 0
        assert observer.requestfailed_errors == []

    def test_on_response_counts_status(self):
        """Should count response status codes."""
        observer = NetworkObserver()

        # Mock responses
        response_200 = MagicMock()
        response_200.status = 200
        response_304 = MagicMock()
        response_304.status = 304

        observer._on_response(response_200)
        observer._on_response(response_200)
        observer._on_response(response_304)

        assert observer.status_histogram[200] == 2
        assert observer.status_histogram[304] == 1

    def test_on_requestfailed_counts(self):
        """Should count failed requests."""
        observer = NetworkObserver()

        request = MagicMock()
        request.url = "https://example.com/resource"
        request.failure = "net::ERR_CONNECTION_REFUSED"

        observer._on_requestfailed(request)
        observer._on_requestfailed(request)

        assert observer.requestfailed_count == 2
        assert len(observer.requestfailed_errors) == 2

    def test_error_limit(self):
        """Should limit stored error messages."""
        observer = NetworkObserver()
        observer._max_errors = 5

        for i in range(10):
            request = MagicMock()
            request.url = f"https://example.com/resource{i}"
            request.failure = f"Error {i}"
            observer._on_requestfailed(request)

        assert observer.requestfailed_count == 10
        assert len(observer.requestfailed_errors) == 5  # Limited

    def test_reset(self):
        """Should clear all counters on reset."""
        observer = NetworkObserver()
        observer.status_histogram[200] = 5
        observer.requestfailed_count = 2
        observer.requestfailed_errors.append("error")

        observer.reset()

        assert observer.status_histogram == {}
        assert observer.requestfailed_count == 0
        assert observer.requestfailed_errors == []

    def test_has_soft_block_status(self):
        """Should detect soft-block status codes."""
        observer = NetworkObserver()
        observer.status_histogram[200] = 10
        assert observer.has_soft_block_status() is False

        observer.status_histogram[403] = 1
        assert observer.has_soft_block_status() is True

        observer.reset()
        observer.status_histogram[429] = 1
        assert observer.has_soft_block_status() is True

    def test_has_server_error_status(self):
        """Should detect server error status codes."""
        observer = NetworkObserver()
        observer.status_histogram[200] = 10
        assert observer.has_server_error_status() is False

        observer.status_histogram[500] = 1
        assert observer.has_server_error_status() is True

        observer.reset()
        observer.status_histogram[502] = 1
        assert observer.has_server_error_status() is True

    def test_get_snapshot(self):
        """Should return snapshot of current state."""
        observer = NetworkObserver()
        observer.status_histogram[200] = 5
        observer.requestfailed_count = 1
        observer.requestfailed_errors.append("error1")

        snapshot = observer.get_snapshot()

        assert snapshot["status_histogram"] == {200: 5}
        assert snapshot["requestfailed_count"] == 1
        assert snapshot["requestfailed_errors"] == ["error1"]

        # Snapshot should be a copy
        snapshot["status_histogram"][200] = 999
        assert observer.status_histogram[200] == 5


class TestNetworkObserverAttach:
    """Tests for attach/detach functionality."""

    def test_attach_adds_listeners(self):
        """Should add event listeners to page."""
        observer = NetworkObserver()
        page = MagicMock()

        observer.attach(page)

        page.on.assert_any_call("response", observer._on_response)
        page.on.assert_any_call("requestfailed", observer._on_requestfailed)
        assert observer._attached is True

    def test_attach_idempotent(self):
        """Should not add listeners twice."""
        observer = NetworkObserver()
        page = MagicMock()

        observer.attach(page)
        observer.attach(page)

        # Should only be called twice total (once per event type)
        assert page.on.call_count == 2

    def test_detach_removes_listeners(self):
        """Should remove event listeners from page."""
        observer = NetworkObserver()
        page = MagicMock()

        observer.attach(page)
        observer.detach(page)

        page.remove_listener.assert_any_call("response", observer._on_response)
        page.remove_listener.assert_any_call("requestfailed", observer._on_requestfailed)
        assert observer._attached is False

    def test_detach_when_not_attached(self):
        """Should handle detach when not attached."""
        observer = NetworkObserver()
        page = MagicMock()

        # Should not raise
        observer.detach(page)
        page.remove_listener.assert_not_called()
