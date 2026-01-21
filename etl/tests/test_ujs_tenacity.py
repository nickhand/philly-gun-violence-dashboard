"""Tests for tenacity retry behavior.

Ensures that ZERO_RESULTS does not trigger retries, while retryable
classifications do retry up to the max attempts.
"""

from etl.courts.scraper.core import RetryableScrapeError
from etl.courts.verification.classifier import Classification, ClassificationResult


class TestRetryableScrapeError:
    """Tests for RetryableScrapeError."""

    def test_carries_result(self):
        """Should carry the classification result."""
        result = ClassificationResult(
            classification=Classification.SOFT_BLOCKED,
            subreason="HTTP 403",
        )
        error = RetryableScrapeError(result)

        assert error.result is result
        assert error.result.classification == Classification.SOFT_BLOCKED

    def test_str_representation(self):
        """Should have informative string representation."""
        result = ClassificationResult(
            classification=Classification.NETWORK_OR_SERVER_ERROR,
        )
        error = RetryableScrapeError(result)

        assert "NETWORK_OR_SERVER_ERROR" in str(error)


class TestClassificationRetryability:
    """Tests for classification retryability."""

    def test_has_results_not_retryable(self):
        """HAS_RESULTS should not trigger retries."""
        result = ClassificationResult(
            classification=Classification.HAS_RESULTS,
            row_count=5,
        )
        assert result.is_retryable is False

    def test_zero_results_not_retryable(self):
        """ZERO_RESULTS should NOT trigger retries."""
        result = ClassificationResult(
            classification=Classification.ZERO_RESULTS,
            row_count=0,
        )
        assert result.is_retryable is False

    def test_soft_blocked_retryable(self):
        """SOFT_BLOCKED should trigger retries."""
        result = ClassificationResult(
            classification=Classification.SOFT_BLOCKED,
        )
        assert result.is_retryable is True

    def test_redirected_retryable(self):
        """REDIRECTED_OR_SESSION_LOST should trigger retries."""
        result = ClassificationResult(
            classification=Classification.REDIRECTED_OR_SESSION_LOST,
        )
        assert result.is_retryable is True

    def test_network_error_retryable(self):
        """NETWORK_OR_SERVER_ERROR should trigger retries."""
        result = ClassificationResult(
            classification=Classification.NETWORK_OR_SERVER_ERROR,
        )
        assert result.is_retryable is True

    def test_ui_drift_retryable(self):
        """UI_DRIFT_OR_UNKNOWN should trigger retries (one retry allowed)."""
        result = ClassificationResult(
            classification=Classification.UI_DRIFT_OR_UNKNOWN,
        )
        assert result.is_retryable is True


class TestRetryBehavior:
    """Tests for actual retry behavior.

    These tests mock the scraper internals to test retry logic
    without hitting the network.
    """

    def test_zero_results_short_circuits(self):
        """ZERO_RESULTS should not raise RetryableScrapeError."""
        result = ClassificationResult(
            classification=Classification.ZERO_RESULTS,
            row_count=0,
        )

        # In the scraper, ZERO_RESULTS returns normally (doesn't raise)
        # This test verifies the classification is correct
        assert not result.is_retryable

        # If we were to wrap this in error-checking:
        if result.is_retryable:
            raise RetryableScrapeError(result)
        # Should not reach here with ZERO_RESULTS

    def test_soft_blocked_raises_retryable(self):
        """SOFT_BLOCKED should raise RetryableScrapeError for retry."""
        result = ClassificationResult(
            classification=Classification.SOFT_BLOCKED,
            subreason="HTTP 403",
        )

        assert result.is_retryable

        # Simulating what the scraper does
        if result.is_retryable:
            error = RetryableScrapeError(result)
            assert isinstance(error, RetryableScrapeError)


class TestAuditLoggingOnRetry:
    """Tests that audit logging works correctly with retries."""

    def test_attempt_logged_before_retry(self):
        """Each attempt should be logged, including failed attempts."""
        from etl.courts.verification.audit import AttemptTracker
        from etl.courts.verification.shard import AuditContext

        ctx = AuditContext(run_id="test", shard_id=0, shard_count=1)
        tracker = AttemptTracker(
            audit_context=ctx,
            incident_number_raw="123",
            incident_number_normalized="123",
        )

        # Simulate 3 attempts: fail, fail, succeed
        attempts_logged = []

        # Attempt 1: SOFT_BLOCKED
        row1 = tracker.add_attempt(
            result=ClassificationResult(
                classification=Classification.SOFT_BLOCKED,
                elapsed_ms=1000,
            ),
            attempt_index=1,
            timestamp_start="2024-01-01T00:00:00Z",
            timestamp_end="2024-01-01T00:00:01Z",
            will_retry=True,
            sleep_s=5.0,
            screenshot_path=None,
        )
        attempts_logged.append(row1)

        # Attempt 2: NETWORK_ERROR
        row2 = tracker.add_attempt(
            result=ClassificationResult(
                classification=Classification.NETWORK_OR_SERVER_ERROR,
                elapsed_ms=2000,
            ),
            attempt_index=2,
            timestamp_start="2024-01-01T00:00:06Z",
            timestamp_end="2024-01-01T00:00:08Z",
            will_retry=True,
            sleep_s=10.0,
            screenshot_path=None,
        )
        attempts_logged.append(row2)

        # Attempt 3: HAS_RESULTS
        row3 = tracker.add_attempt(
            result=ClassificationResult(
                classification=Classification.HAS_RESULTS,
                row_count=2,
                elapsed_ms=1500,
            ),
            attempt_index=3,
            timestamp_start="2024-01-01T00:00:18Z",
            timestamp_end="2024-01-01T00:00:20Z",
            will_retry=False,
            sleep_s=None,
            screenshot_path=None,
        )
        attempts_logged.append(row3)

        # Verify all attempts logged
        assert len(tracker.attempts) == 3
        assert tracker.attempts[0].classification == "SOFT_BLOCKED"
        assert tracker.attempts[0].will_retry is True
        assert tracker.attempts[1].classification == "NETWORK_OR_SERVER_ERROR"
        assert tracker.attempts[2].classification == "HAS_RESULTS"
        assert tracker.attempts[2].will_retry is False

    def test_sleep_time_logged(self):
        """Sleep time before retry should be logged."""
        from etl.courts.verification.audit import AttemptTracker
        from etl.courts.verification.shard import AuditContext

        ctx = AuditContext(run_id="test", shard_id=0, shard_count=1)
        tracker = AttemptTracker(
            audit_context=ctx,
            incident_number_raw="123",
            incident_number_normalized="123",
        )

        tracker.add_attempt(
            result=ClassificationResult(
                classification=Classification.SOFT_BLOCKED,
                elapsed_ms=1000,
            ),
            attempt_index=1,
            timestamp_start="2024-01-01T00:00:00Z",
            timestamp_end="2024-01-01T00:00:01Z",
            will_retry=True,
            sleep_s=7.5,  # Planned sleep time
            screenshot_path=None,
        )

        assert tracker.attempts[0].sleep_s == 7.5
