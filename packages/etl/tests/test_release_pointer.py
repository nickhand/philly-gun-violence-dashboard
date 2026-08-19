"""Adversarial tests for monotonic conditional release pointers."""

import io
import json
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from botocore.exceptions import ClientError
from mypy_boto3_s3.client import S3Client

from etl.utils.release_pointer import (
    ReleaseOrder,
    StablePointerConflict,
    StablePointerRegression,
    StablePointerSnapshot,
    decode_json_object,
    move_stable_pointer,
)

BUCKET = "test-bucket"
KEY = "processed/example/release.json"


def _error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, "PutObject")


class ConditionalS3:
    """In-memory S3 model with PutObject preconditions."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.put_count = 0
        self.transient_conflicts = 0

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        assert Bucket == BUCKET
        body, etag = self.objects[Key]
        return {"Body": io.BytesIO(body), "ETag": etag}

    def put_object(self, **kwargs: Any) -> None:
        assert kwargs["Bucket"] == BUCKET
        self.put_count += 1
        if self.transient_conflicts:
            self.transient_conflicts -= 1
            raise _error("ConditionalRequestConflict")
        key = cast(str, kwargs["Key"])
        current = self.objects.get(key)
        if kwargs.get("IfNoneMatch") == "*" and current is not None:
            raise _error("PreconditionFailed")
        if "IfMatch" in kwargs and (current is None or current[1] != kwargs["IfMatch"]):
            raise _error("PreconditionFailed")
        body = cast(bytes, kwargs["Body"])
        self.objects[key] = (body, f'"etag-{self.put_count}"')


def _body(character: str) -> bytes:
    return json.dumps({"version": f"sha256:{character * 64}"}).encode()


def _order(day: int, hour: int) -> ReleaseOrder:
    return ReleaseOrder(
        data_through=date(2026, 8, day),
        run_started_at=datetime(2026, 8, day, hour, tzinfo=UTC),
    )


def _snapshot(
    s3: ConditionalS3,
    orders: dict[bytes, ReleaseOrder],
) -> StablePointerSnapshot:
    body, etag = s3.objects[KEY]
    value = decode_json_object(body, label="Test pointer")
    version = value["version"]
    assert isinstance(version, str)
    return StablePointerSnapshot(
        etag=etag,
        body=body,
        version=version,
        order=orders[body],
    )


def _move(
    s3: ConditionalS3,
    *,
    body: bytes,
    order: ReleaseOrder,
    expected: StablePointerSnapshot,
    orders: dict[bytes, ReleaseOrder],
) -> None:
    version = decode_json_object(body, label="Candidate")["version"]
    assert isinstance(version, str)
    move_stable_pointer(
        cast(S3Client, s3),
        bucket=BUCKET,
        key=KEY,
        body=body,
        version=version,
        order=order,
        expected=expected,
        read_current=lambda: _snapshot(s3, orders),
        content_type="application/json",
        cache_control="no-cache",
    )


def test_stale_overlapping_publisher_cannot_regress_newer_pointer() -> None:
    baseline = _body("a")
    stale = _body("b")
    newer = _body("c")
    orders = {
        baseline: _order(16, 8),
        stale: _order(17, 8),
        newer: _order(18, 8),
    }
    s3 = ConditionalS3()
    s3.objects[KEY] = (baseline, '"baseline"')
    shared_start = _snapshot(s3, orders)

    _move(s3, body=newer, order=orders[newer], expected=shared_start, orders=orders)

    with pytest.raises(StablePointerRegression, match="equal or newer"):
        _move(s3, body=stale, order=orders[stale], expected=shared_start, orders=orders)

    assert s3.objects[KEY][0] == newer


def test_changed_pointer_for_newer_candidate_requires_fresh_rerun() -> None:
    baseline = _body("a")
    intervening = _body("b")
    candidate = _body("c")
    orders = {
        baseline: _order(16, 8),
        intervening: _order(17, 8),
        candidate: _order(18, 8),
    }
    s3 = ConditionalS3()
    s3.objects[KEY] = (baseline, '"baseline"')
    shared_start = _snapshot(s3, orders)
    _move(
        s3,
        body=intervening,
        order=orders[intervening],
        expected=shared_start,
        orders=orders,
    )

    with pytest.raises(StablePointerConflict, match="rerun from the new generation"):
        _move(
            s3,
            body=candidate,
            order=orders[candidate],
            expected=shared_start,
            orders=orders,
        )

    assert s3.objects[KEY][0] == intervening


def test_known_regression_is_rejected_before_any_s3_write() -> None:
    current = _body("a")
    candidate = _body("b")
    orders = {current: _order(18, 8), candidate: _order(17, 8)}
    s3 = ConditionalS3()
    s3.objects[KEY] = (current, '"current"')
    expected = _snapshot(s3, orders)

    with pytest.raises(StablePointerRegression):
        _move(
            s3,
            body=candidate,
            order=orders[candidate],
            expected=expected,
            orders=orders,
        )

    assert s3.put_count == 0


def test_409_is_retried_only_after_current_revision_is_verified_unchanged() -> None:
    current = _body("a")
    candidate = _body("b")
    orders = {current: _order(17, 8), candidate: _order(18, 8)}
    s3 = ConditionalS3()
    s3.objects[KEY] = (current, '"current"')
    s3.transient_conflicts = 1
    expected = _snapshot(s3, orders)

    _move(
        s3,
        body=candidate,
        order=orders[candidate],
        expected=expected,
        orders=orders,
    )

    assert s3.put_count == 2
    assert s3.objects[KEY][0] == candidate
