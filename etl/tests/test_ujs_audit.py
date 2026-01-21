"""Tests for audit logging module."""

import gzip
import json
import tempfile
from pathlib import Path

import pytest

from etl.courts.verification.audit import (
    AttemptAuditRow,
    AttemptTracker,
    AuditWriter,
)
from etl.courts.verification.classifier import Classification, ClassificationResult
from etl.courts.verification.shard import AuditContext


class TestAttemptAuditRow:
    """Tests for AttemptAuditRow."""

    def test_create_row(self):
        """Should create a valid attempt row."""
        row = AttemptAuditRow(
            run_id="test-run",
            shard_id=0,
            shard_count=1,
            task_id="task-1",
            incident_number_raw="1234567890",
            incident_number_normalized="1234567890",
            attempt_index=1,
            attempt_timestamp_start="2024-01-01T00:00:00Z",
            attempt_timestamp_end="2024-01-01T00:00:05Z",
            elapsed_ms=5000,
            classification="HAS_RESULTS",
            subreason="Found 2 rows",
            final_url="https://example.com",
            row_count=2,
            marker_hits={"results_container": True},
            status_histogram={200: 5},
            requestfailed_count=0,
            will_retry=False,
            sleep_s=None,
            screenshot_path=None,
        )
        assert row.run_id == "test-run"
        assert row.attempt_index == 1

    def test_to_dict(self):
        """Should convert to JSON-serializable dict."""
        row = AttemptAuditRow(
            run_id="test",
            shard_id=0,
            shard_count=1,
            task_id=None,
            incident_number_raw="123",
            incident_number_normalized="123",
            attempt_index=1,
            attempt_timestamp_start="2024-01-01T00:00:00Z",
            attempt_timestamp_end="2024-01-01T00:00:01Z",
            elapsed_ms=1000,
            classification="HAS_RESULTS",
            subreason=None,
            final_url="https://example.com",
            row_count=1,
            marker_hits=None,
            status_histogram=None,
            requestfailed_count=0,
            will_retry=False,
            sleep_s=None,
            screenshot_path=None,
        )
        d = row.to_dict()
        assert d["run_id"] == "test"
        assert d["attempt_index"] == 1
        # Should be JSON-serializable
        json.dumps(d)


class TestAuditWriter:
    """Tests for AuditWriter."""

    def test_creates_output_directory(self):
        """Should create output directory structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            writer = AuditWriter(
                base_path=tmpdir,
                run_id="test-run",
                shard_id=0,
                compress=False,
            )
            assert writer.output_dir.exists()
            # AuditWriter now creates {base_path}/audit/ subfolder
            assert writer.output_dir == Path(tmpdir) / "audit"

    def test_write_attempt_uncompressed(self):
        """Should write attempt records as NDJSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            writer = AuditWriter(tmpdir, "run", 0, compress=False)

            row = AttemptAuditRow(
                run_id="run",
                shard_id=0,
                shard_count=1,
                task_id=None,
                incident_number_raw="123",
                incident_number_normalized="123",
                attempt_index=1,
                attempt_timestamp_start="2024-01-01T00:00:00Z",
                attempt_timestamp_end="2024-01-01T00:00:01Z",
                elapsed_ms=1000,
                classification="HAS_RESULTS",
                subreason=None,
                final_url="https://example.com",
                row_count=1,
                marker_hits=None,
                status_histogram=None,
                requestfailed_count=0,
                will_retry=False,
                sleep_s=None,
                screenshot_path=None,
            )
            writer.write_attempt(row)
            writer.close()

            # Read back
            with open(writer.attempts_path) as f:
                line = f.readline()
                data = json.loads(line)
                assert data["incident_number_raw"] == "123"

    def test_write_compressed(self):
        """Should write gzipped NDJSON when compress=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            writer = AuditWriter(tmpdir, "run", 0, compress=True)

            row = AttemptAuditRow(
                run_id="run",
                shard_id=0,
                shard_count=1,
                task_id=None,
                incident_number_raw="456",
                incident_number_normalized="456",
                attempt_index=1,
                attempt_timestamp_start="2024-01-01T00:00:00Z",
                attempt_timestamp_end="2024-01-01T00:00:01Z",
                elapsed_ms=1000,
                classification="ZERO_RESULTS",
                subreason=None,
                final_url="https://example.com",
                row_count=0,
                marker_hits=None,
                status_histogram=None,
                requestfailed_count=0,
                will_retry=False,
                sleep_s=None,
                screenshot_path=None,
            )
            writer.write_attempt(row)
            writer.close()

            assert writer.attempts_path.suffix == ".gz"
            # Read back
            with gzip.open(writer.attempts_path, "rt") as f:
                line = f.readline()
                data = json.loads(line)
                assert data["incident_number_raw"] == "456"

    def test_context_manager(self):
        """Should work as context manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with AuditWriter(tmpdir, "run", 0, compress=False) as writer:
                assert writer.output_dir.exists()


class TestAttemptTracker:
    """Tests for AttemptTracker."""

    def test_add_attempt(self):
        """Should track attempts and build audit rows."""
        ctx = AuditContext(run_id="test", shard_id=0, shard_count=1)
        tracker = AttemptTracker(
            audit_context=ctx,
            incident_number_raw="1234567890",
            incident_number_normalized="1234567890",
        )

        result = ClassificationResult(
            classification=Classification.SOFT_BLOCKED,
            subreason="HTTP 403",
            elapsed_ms=1000,
        )

        row = tracker.add_attempt(
            result=result,
            attempt_index=1,
            timestamp_start="2024-01-01T00:00:00Z",
            timestamp_end="2024-01-01T00:00:01Z",
            will_retry=True,
            sleep_s=5.0,
            screenshot_path=None,
        )

        assert row.classification == "SOFT_BLOCKED"
        assert row.will_retry is True
        assert len(tracker.attempts) == 1

    def test_build_final_row_has_results(self):
        """Should build final row with HAS_RESULTS priority."""
        ctx = AuditContext(run_id="test", shard_id=0, shard_count=1)
        tracker = AttemptTracker(
            audit_context=ctx,
            incident_number_raw="123",
            incident_number_normalized="123",
        )

        # First attempt: SOFT_BLOCKED
        tracker.add_attempt(
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

        # Second attempt: HAS_RESULTS
        tracker.add_attempt(
            result=ClassificationResult(
                classification=Classification.HAS_RESULTS,
                row_count=3,
                elapsed_ms=2000,
            ),
            attempt_index=2,
            timestamp_start="2024-01-01T00:00:06Z",
            timestamp_end="2024-01-01T00:00:08Z",
            will_retry=False,
            sleep_s=None,
            screenshot_path=None,
        )

        final = tracker.build_final_row()

        assert final.final_classification == "HAS_RESULTS"
        assert final.attempt_count_total == 2
        assert final.first_success_attempt_index == 2
        assert final.row_count == 3

    def test_build_final_row_zero_results_priority(self):
        """ZERO_RESULTS should take priority over other failures."""
        ctx = AuditContext(run_id="test", shard_id=0, shard_count=1)
        tracker = AttemptTracker(
            audit_context=ctx,
            incident_number_raw="123",
            incident_number_normalized="123",
        )

        # First attempt: SOFT_BLOCKED
        tracker.add_attempt(
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

        # Second attempt: ZERO_RESULTS
        tracker.add_attempt(
            result=ClassificationResult(
                classification=Classification.ZERO_RESULTS,
                row_count=0,
                elapsed_ms=2000,
            ),
            attempt_index=2,
            timestamp_start="2024-01-01T00:00:06Z",
            timestamp_end="2024-01-01T00:00:08Z",
            will_retry=False,
            sleep_s=None,
            screenshot_path=None,
        )

        final = tracker.build_final_row()

        assert final.final_classification == "ZERO_RESULTS"
        assert final.first_success_attempt_index == 2

    def test_build_final_row_aggregates_histogram(self):
        """Should aggregate status histograms across attempts."""
        ctx = AuditContext(run_id="test", shard_id=0, shard_count=1)
        tracker = AttemptTracker(
            audit_context=ctx,
            incident_number_raw="123",
            incident_number_normalized="123",
        )

        tracker.add_attempt(
            result=ClassificationResult(
                classification=Classification.HAS_RESULTS,
                status_histogram={200: 5, 304: 2},
                elapsed_ms=1000,
            ),
            attempt_index=1,
            timestamp_start="2024-01-01T00:00:00Z",
            timestamp_end="2024-01-01T00:00:01Z",
            will_retry=False,
            sleep_s=None,
            screenshot_path=None,
        )

        final = tracker.build_final_row()
        assert final.status_histogram_agg == {200: 5, 304: 2}

    def test_build_final_row_no_attempts_raises(self):
        """Should raise if no attempts recorded."""
        ctx = AuditContext(run_id="test", shard_id=0, shard_count=1)
        tracker = AttemptTracker(
            audit_context=ctx,
            incident_number_raw="123",
            incident_number_normalized="123",
        )

        with pytest.raises(ValueError, match="No attempts"):
            tracker.build_final_row()
