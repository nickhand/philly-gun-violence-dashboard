"""Tests for shared dashboard-utils path helpers used by ETL."""

from dashboard_utils.config import get_s3_settings
from dashboard_utils.paths import get_processed_key, get_reference_key


def test_s3_prefix_settings_are_used(monkeypatch) -> None:
    """Processed/reference key helpers should respect configured prefixes."""
    monkeypatch.setenv("S3_BUCKET", "bucket")
    monkeypatch.setenv("S3_PROCESSED_PREFIX", "custom-processed")
    monkeypatch.setenv("S3_REFERENCE_PREFIX", "custom-reference")
    get_s3_settings.cache_clear()

    assert get_processed_key("courts_flags") == "custom-processed/courts/scraped_courts_data.csv"
    assert get_reference_key("boundaries_manifest.json") == (
        "custom-reference/boundaries_manifest.json"
    )

    get_s3_settings.cache_clear()
