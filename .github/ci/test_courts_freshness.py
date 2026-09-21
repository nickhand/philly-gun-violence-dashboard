"""Court publication freshness must not inherit daily shootings freshness."""

import unittest
from datetime import UTC, datetime, timedelta

from check_courts_freshness import check_metadata


class CourtsFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 21, 19, tzinfo=UTC)
        self.metadata = {
            "run_id": "2026-09-18T021541Z-70ad",
            "last_updated": "2026-09-18T12:00:00Z",
            "selection_mode": "full",
            "coverage_complete": True,
            "status": "partial",
            "publication_contract_version": 2,
            "court_search_semantics_version": 2,
            "result_conflict_policy_version": 1,
            "missing_result_count": 0,
            "extra_result_count": 0,
            "unresolved_result_conflict_count": 0,
            "invalid_result_conflict_resolution_count": 0,
        }

    def test_complete_partial_publication_is_allowed(self):
        self.assertIn("3.29 days", check_metadata(self.metadata, now=self.now))

    def test_september_11_publication_fails_on_september_21(self):
        self.metadata["last_updated"] = "2026-09-11T10:40:23Z"
        with self.assertRaisesRegex(ValueError, "overdue"):
            check_metadata(self.metadata, now=self.now)

    def test_exact_age_boundary(self):
        self.metadata["last_updated"] = (self.now - timedelta(days=8)).isoformat()
        check_metadata(self.metadata, now=self.now)
        with self.assertRaises(ValueError):
            check_metadata(self.metadata, now=self.now + timedelta(seconds=1))

    def test_invalid_or_unproven_metadata_is_rejected(self):
        for key, value in [
            ("last_updated", None),
            ("last_updated", "2026-09-18"),
            ("last_updated", "2026-09-22T00:00:00Z"),
            ("last_updated", "bad"),
            ("selection_mode", "sample"),
            ("coverage_complete", False),
            ("run_id", "run\n::notice::injected"),
            ("missing_result_count", False),
            ("unresolved_result_conflict_count", 1),
        ]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                check_metadata({**self.metadata, key: value}, now=self.now)
