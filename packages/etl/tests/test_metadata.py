"""Tests for processed dataset metadata."""

import json

import pandas as pd

from dashboard_utils.config import get_s3_settings
from etl.utils.storage import write_meta


class FakeS3:
    def __init__(self) -> None:
        self.puts: list[dict[str, object]] = []

    def put_object(self, **kwargs: object) -> None:
        self.puts.append(kwargs)


def test_write_meta_preserves_base_fields_and_adds_extra(monkeypatch) -> None:
    monkeypatch.setenv("S3_BUCKET", "bucket")
    monkeypatch.setenv("S3_PROCESSED_PREFIX", "processed")
    get_s3_settings.cache_clear()

    s3 = FakeS3()
    write_meta(
        subfolder="shootings",
        data_through=pd.Timestamp("2026-05-24 12:00:00"),
        s3=s3,  # ty: ignore[invalid-argument-type]
        pipeline="shootings",
        row_count=123,
        max_event_date=pd.Timestamp("2026-05-24 08:00:00"),
    )

    assert s3.puts[0]["Bucket"] == "bucket"
    assert s3.puts[0]["Key"] == "processed/shootings/meta.json"

    body = json.loads(s3.puts[0]["Body"])  # ty: ignore[invalid-argument-type]
    assert body["status"] == "success"
    assert body["data_through"] == "2026-05-24"
    assert body["schema_version"] == 1
    assert body["pipeline"] == "shootings"
    assert body["row_count"] == 123
    assert body["max_event_date"] == "2026-05-24T08:00:00"
    assert "last_updated" in body

    get_s3_settings.cache_clear()
