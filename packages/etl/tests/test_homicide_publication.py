"""Atomic publication tests for homicide totals and metadata."""

import hashlib
import io
import json
from typing import Any, cast

import pandas as pd
import pytest
from botocore.exceptions import ClientError
from mypy_boto3_s3.client import S3Client

from dashboard_utils.config import get_s3_settings
from etl.homicides.load import (
    HomicideReleaseCommittedError,
    _prepare_homicide_publication,
    read_homicide_database_snapshot,
    read_homicide_pointer,
    write_homicide_database,
    write_homicide_release,
)
from etl.utils.release_pointer import (
    StableObjectConflict,
    StableObjectSnapshot,
    StablePointerRegression,
    StablePointerSnapshot,
)


class RecordingS3:
    """Record writes and optionally fail at one exact key."""

    def __init__(self, fail_key: str | None = None) -> None:
        self.puts: list[dict[str, Any]] = []
        self.fail_key = fail_key

    def put_object(self, **kwargs: Any) -> None:
        if kwargs["Key"] == self.fail_key:
            raise RuntimeError("simulated write failure")
        self.puts.append(kwargs)


class ConditionalHomicideS3:
    """In-memory S3 with conditional pointer writes and exact bodies."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.put_count = 0

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        assert Bucket == "test-bucket"
        try:
            body, etag = self.objects[Key]
        except KeyError as exc:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "missing"}},
                "GetObject",
            ) from exc
        return {"Body": io.BytesIO(body), "ETag": etag}

    def put_object(self, **kwargs: Any) -> None:
        assert kwargs["Bucket"] == "test-bucket"
        key = cast(str, kwargs["Key"])
        current = self.objects.get(key)
        if kwargs.get("IfNoneMatch") == "*" and current is not None:
            raise ClientError(
                {"Error": {"Code": "PreconditionFailed", "Message": "stale"}},
                "PutObject",
            )
        if "IfMatch" in kwargs and (current is None or current[1] != kwargs["IfMatch"]):
            raise ClientError(
                {"Error": {"Code": "PreconditionFailed", "Message": "stale"}},
                "PutObject",
            )
        self.put_count += 1
        self.objects[key] = (cast(bytes, kwargs["Body"]), f'"etag-{self.put_count}"')


@pytest.fixture(autouse=True)
def s3_settings(monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "test-bucket")
    monkeypatch.setenv("S3_PROCESSED_PREFIX", "processed")
    get_s3_settings.cache_clear()
    yield
    get_s3_settings.cache_clear()


def _totals() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "year": [2025, 2026],
            "annual": [250, None],
            "ytd": [190, 120],
        }
    )


def test_homicide_pointer_checksums_exact_immutable_objects() -> None:
    publication = _prepare_homicide_publication(
        _totals(),
        {"data_through": "2026-08-17", "last_updated": "2026-08-18T00:00:00Z"},
    )
    pointer = json.loads(publication.pointer_body)

    assert pointer["version"] == f"sha256:{publication.release_id}"
    assert pointer["totals"]["sha256"] == hashlib.sha256(publication.totals_body).hexdigest()
    assert pointer["metadata"]["sha256"] == hashlib.sha256(publication.metadata_body).hexdigest()
    assert f"/releases/{publication.release_id}/" in pointer["totals"]["key"]


def test_homicide_release_moves_pointer_before_compatibility_mirrors() -> None:
    s3 = RecordingS3()
    write_homicide_release(
        cast(S3Client, s3),
        _totals(),
        {"data_through": "2026-08-17", "last_updated": "2026-08-18T00:00:00Z"},
        expected_pointer=StablePointerSnapshot.missing(),
    )

    keys = [put["Key"] for put in s3.puts]
    assert "/releases/" in keys[0]
    assert "/releases/" in keys[1]
    assert keys[2:] == [
        "processed/homicides/release.json",
        "processed/homicides/homicide_totals.json",
        "processed/homicides/meta.json",
    ]
    assert s3.puts[0]["CacheControl"] == "public,max-age=31536000,immutable"


def test_failed_homicide_pointer_does_not_mutate_compatibility_mirrors() -> None:
    s3 = RecordingS3(fail_key="processed/homicides/release.json")

    with pytest.raises(RuntimeError, match="simulated write failure"):
        write_homicide_release(
            cast(S3Client, s3),
            _totals(),
            {"data_through": "2026-08-17", "last_updated": "2026-08-18T00:00:00Z"},
            expected_pointer=StablePointerSnapshot.missing(),
        )

    assert all("/releases/" in put["Key"] for put in s3.puts)


def test_compatibility_failure_is_reported_after_pointer_has_moved() -> None:
    s3 = RecordingS3(fail_key="processed/homicides/meta.json")

    with pytest.raises(HomicideReleaseCommittedError, match="committed"):
        write_homicide_release(
            cast(S3Client, s3),
            _totals(),
            {"data_through": "2026-08-17", "last_updated": "2026-08-18T00:00:00Z"},
            expected_pointer=StablePointerSnapshot.missing(),
        )

    assert any(put["Key"] == "processed/homicides/release.json" for put in s3.puts)


def test_stale_homicide_publisher_cannot_regress_newer_release_or_mirrors() -> None:
    s3 = ConditionalHomicideS3()
    client = cast(S3Client, s3)
    baseline_metadata = {
        "data_through": "2026-08-16",
        "last_updated": "2026-08-16T08:00:00Z",
    }
    write_homicide_release(
        client,
        _totals(),
        baseline_metadata,
        expected_pointer=StablePointerSnapshot.missing(),
    )
    shared_start = read_homicide_pointer(client)

    newer_metadata = {
        "data_through": "2026-08-18",
        "last_updated": "2026-08-18T08:00:00Z",
    }
    write_homicide_release(
        client,
        _totals(),
        newer_metadata,
        expected_pointer=shared_start,
    )
    newer_pointer = s3.objects["processed/homicides/release.json"][0]
    newer_mirror = s3.objects["processed/homicides/meta.json"][0]

    stale_metadata = {
        "data_through": "2026-08-17",
        "last_updated": "2026-08-17T08:00:00Z",
    }
    with pytest.raises(StablePointerRegression, match="equal or newer"):
        write_homicide_release(
            client,
            _totals(),
            stale_metadata,
            expected_pointer=shared_start,
        )

    assert s3.objects["processed/homicides/release.json"][0] == newer_pointer
    assert s3.objects["processed/homicides/meta.json"][0] == newer_mirror


def test_stale_homicide_publisher_cannot_regress_daily_history() -> None:
    s3 = ConditionalHomicideS3()
    client = cast(S3Client, s3)
    baseline = pd.DataFrame({"date": [pd.Timestamp("2026-08-16")], "total": [115]})
    write_homicide_database(
        client,
        baseline,
        expected_snapshot=StableObjectSnapshot.missing(),
    )
    shared_start = read_homicide_database_snapshot(client)

    newer = pd.concat(
        [
            baseline,
            pd.DataFrame({"date": [pd.Timestamp("2026-08-18")], "total": [117]}),
        ],
        ignore_index=True,
    )
    write_homicide_database(
        client,
        newer,
        expected_snapshot=shared_start,
    )
    key = "processed/homicides/homicide_totals_daily.csv"
    newer_body = s3.objects[key][0]

    stale = pd.concat(
        [
            baseline,
            pd.DataFrame({"date": [pd.Timestamp("2026-08-17")], "total": [116]}),
        ],
        ignore_index=True,
    )
    with pytest.raises(StableObjectConflict, match="changed during publication"):
        write_homicide_database(
            client,
            stale,
            expected_snapshot=shared_start,
        )

    assert s3.objects[key][0] == newer_body
