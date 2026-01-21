"""Tests for shard assignment and context."""

import pytest

from etl.courts.verification.shard import (
    AuditContext,
    assign_shard,
    get_shard_artifact_path,
    normalize_incident_number,
)


class TestNormalizeIncidentNumber:
    """Tests for incident number normalization."""

    def test_already_normalized(self):
        """Should preserve already-normalized numbers."""
        assert normalize_incident_number("1234567890") == "1234567890"

    def test_strip_whitespace(self):
        """Should strip whitespace."""
        assert normalize_incident_number("  1234567890  ") == "1234567890"

    def test_uppercase(self):
        """Should convert to uppercase."""
        assert normalize_incident_number("abc1234567") == "ABC1234567"

    def test_12_digit_format(self):
        """Should handle 12-digit format by stripping first 2 chars."""
        assert normalize_incident_number("201234567890") == "1234567890"

    def test_preserves_short_values(self):
        """Should preserve values shorter than 12 digits."""
        assert normalize_incident_number("12345") == "12345"


class TestAssignShard:
    """Tests for deterministic shard assignment."""

    def test_single_shard(self):
        """Should always return 0 for single shard."""
        assert assign_shard("1234567890", 1) == 0
        assert assign_shard("0987654321", 1) == 0

    def test_deterministic(self):
        """Should return same shard for same input."""
        shard1 = assign_shard("1234567890", 10)
        shard2 = assign_shard("1234567890", 10)
        assert shard1 == shard2

    def test_valid_range(self):
        """Should return values in valid range."""
        for i in range(100):
            incident = f"{i:010d}"
            shard = assign_shard(incident, 10)
            assert 0 <= shard < 10

    def test_distribution(self):
        """Should distribute roughly evenly across shards."""
        shard_count = 10
        counts = [0] * shard_count
        for i in range(1000):
            incident = f"{i:010d}"
            shard = assign_shard(incident, shard_count)
            counts[shard] += 1

        # Each shard should have roughly 100 items (+/- 50)
        for count in counts:
            assert 50 < count < 150

    def test_invalid_shard_count(self):
        """Should raise for invalid shard count."""
        with pytest.raises(ValueError):
            assign_shard("1234567890", 0)
        with pytest.raises(ValueError):
            assign_shard("1234567890", -1)


class TestAuditContext:
    """Tests for AuditContext."""

    def test_create_valid_context(self):
        """Should create valid context."""
        ctx = AuditContext(
            run_id="test-run",
            shard_id=0,
            shard_count=1,
        )
        assert ctx.run_id == "test-run"
        assert ctx.shard_id == 0
        assert ctx.shard_count == 1

    def test_invalid_shard_id_negative(self):
        """Should raise for negative shard_id."""
        with pytest.raises(ValueError):
            AuditContext(run_id="test", shard_id=-1, shard_count=1)

    def test_invalid_shard_count(self):
        """Should raise for invalid shard_count."""
        with pytest.raises(ValueError):
            AuditContext(run_id="test", shard_id=0, shard_count=0)

    def test_shard_id_exceeds_count(self):
        """Should raise if shard_id >= shard_count."""
        with pytest.raises(ValueError):
            AuditContext(run_id="test", shard_id=5, shard_count=5)

    def test_is_my_shard(self):
        """Should correctly identify items for this shard."""
        ctx = AuditContext(run_id="test", shard_id=0, shard_count=2)

        # Collect items for this shard
        my_items = []
        for i in range(100):
            incident = f"{i:010d}"
            if ctx.is_my_shard(incident):
                my_items.append(incident)

        # Should have roughly half
        assert 40 < len(my_items) < 60

    def test_filter_my_items(self):
        """Should filter list to only this shard's items."""
        ctx = AuditContext(run_id="test", shard_id=1, shard_count=3)
        items = [f"{i:010d}" for i in range(100)]

        filtered = ctx.filter_my_items(items)

        # All filtered items should belong to shard 1
        for item in filtered:
            assert assign_shard(normalize_incident_number(item), 3) == 1

    def test_to_dict(self):
        """Should convert to JSON-serializable dict."""
        ctx = AuditContext(
            run_id="test-run",
            shard_id=2,
            shard_count=5,
            task_id="task-123",
        )
        d = ctx.to_dict()
        assert d["run_id"] == "test-run"
        assert d["shard_id"] == 2
        assert d["shard_count"] == 5
        assert d["task_id"] == "task-123"
        assert "created_at" in d


class TestGetShardArtifactPath:
    """Tests for artifact path generation."""

    def test_local_path(self):
        """Should build correct local path."""
        path = get_shard_artifact_path("artifacts", "run-123", 2, "audit_final.ndjson.gz")
        assert path == "artifacts/run-123/shard=2/audit_final.ndjson.gz"

    def test_s3_path(self):
        """Should build correct S3 path."""
        path = get_shard_artifact_path("s3://bucket/prefix", "run-123", 0, "audit_attempts.ndjson")
        assert path == "s3://bucket/prefix/run-123/shard=0/audit_attempts.ndjson"

    def test_strips_trailing_slash(self):
        """Should strip trailing slash from base path."""
        path = get_shard_artifact_path("artifacts/", "run-123", 1, "file.txt")
        assert path == "artifacts/run-123/shard=1/file.txt"
