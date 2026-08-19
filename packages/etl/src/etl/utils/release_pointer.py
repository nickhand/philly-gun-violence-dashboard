"""Fail-closed helpers for monotonic S3 release pointers."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Final

from botocore.exceptions import BotoCoreError, ClientError
from mypy_boto3_s3.client import S3Client
from mypy_boto3_s3.type_defs import PutObjectRequestTypeDef

SHA256_PREFIX: Final = "sha256:"
SHA256_HEX_LENGTH: Final = 64
MAX_CONDITIONAL_CONFLICT_RETRIES: Final = 3


class StablePointerConflict(RuntimeError):
    """The stable pointer changed after a publisher captured its state."""


class StablePointerRegression(StablePointerConflict):
    """A candidate is not newer than the stable pointer it would replace."""


class StableObjectConflict(RuntimeError):
    """A mutable object changed after a publisher captured its state."""


@dataclass(frozen=True, slots=True)
class ReleaseOrder:
    """A release's source freshness and run-start tie breaker."""

    data_through: date | None
    run_started_at: datetime

    def __post_init__(self) -> None:
        """Normalize timestamps so comparisons cannot mix time zones."""
        if self.run_started_at.tzinfo is None or self.run_started_at.utcoffset() is None:
            raise ValueError("Release run_started_at must include a timezone")
        object.__setattr__(self, "run_started_at", self.run_started_at.astimezone(UTC))

    def sort_key(self) -> tuple[date, datetime]:
        """Return a total ordering, treating pre-release pointers as the baseline."""
        return (self.data_through or date.min, self.run_started_at)


@dataclass(frozen=True, slots=True)
class StablePointerSnapshot:
    """One exact, conditionally replaceable S3 pointer revision."""

    etag: str | None
    body: bytes | None
    version: str | None
    order: ReleaseOrder | None

    def __post_init__(self) -> None:
        """Require either a complete existing snapshot or an absent snapshot."""
        values = (self.etag, self.body, self.version, self.order)
        if any(value is None for value in values) and any(value is not None for value in values):
            raise ValueError("Stable pointer snapshot must be wholly present or absent")

    @classmethod
    def missing(cls) -> "StablePointerSnapshot":
        """Return the typed state for a pointer that did not exist."""
        return cls(etag=None, body=None, version=None, order=None)

    @property
    def exists(self) -> bool:
        """Return whether this snapshot names an existing object."""
        return self.etag is not None


@dataclass(frozen=True, slots=True)
class JsonPointerObject:
    """Exact S3 bytes and decoded object read in one request."""

    etag: str
    body: bytes
    value: dict[str, object]


@dataclass(frozen=True, slots=True)
class StableObjectSnapshot:
    """One exact mutable S3 object revision, or its confirmed absence."""

    etag: str | None
    body: bytes | None

    def __post_init__(self) -> None:
        """Keep absence distinct from a partially observed response."""
        if (self.etag is None) != (self.body is None):
            raise ValueError("Stable object snapshot must be wholly present or absent")

    @classmethod
    def missing(cls) -> "StableObjectSnapshot":
        """Return the typed state for an object that did not exist."""
        return cls(etag=None, body=None)


def _reject_constant(value: str) -> None:
    raise ValueError(f"JSON contains non-finite number {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"JSON contains duplicate key '{key}'")
        value[key] = item
    return value


def decode_json_object(body: bytes, *, label: str) -> dict[str, object]:
    """Decode strict UTF-8 JSON with unique keys and an object root."""
    try:
        value = json.loads(
            body,
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _is_not_found(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") in {
        "404",
        "NoSuchKey",
        "NotFound",
    }


def _error_code(exc: ClientError) -> str:
    value = exc.response.get("Error", {}).get("Code")
    return value if isinstance(value, str) else ""


def read_json_pointer(
    s3: S3Client,
    *,
    bucket: str,
    key: str,
    label: str,
) -> JsonPointerObject | None:
    """Read a pointer's body and ETag from the same S3 response."""
    try:
        response = s3.get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if _is_not_found(exc):
            return None
        raise
    body = response["Body"].read()
    if not isinstance(body, bytes):
        raise TypeError(f"{label} S3 body did not return bytes")
    etag = response.get("ETag")
    if not isinstance(etag, str) or not etag:
        raise ValueError(f"{label} S3 response is missing its ETag")
    return JsonPointerObject(
        etag=etag,
        body=body,
        value=decode_json_object(body, label=label),
    )


def read_stable_object(
    s3: S3Client,
    *,
    bucket: str,
    key: str,
    label: str,
) -> StableObjectSnapshot:
    """Read an object's exact bytes and ETag from one S3 response."""
    try:
        response = s3.get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if _is_not_found(exc):
            return StableObjectSnapshot.missing()
        raise
    body = response["Body"].read()
    if not isinstance(body, bytes):
        raise TypeError(f"{label} S3 body did not return bytes")
    etag = response.get("ETag")
    if not isinstance(etag, str) or not etag:
        raise ValueError(f"{label} S3 response is missing its ETag")
    return StableObjectSnapshot(etag=etag, body=body)


def validate_release_version(value: object, *, label: str) -> str:
    """Return a canonical content-addressed version string."""
    if not isinstance(value, str) or not value.startswith(SHA256_PREFIX):
        raise ValueError(f"{label} must be a SHA-256 version")
    digest = value.removeprefix(SHA256_PREFIX)
    if len(digest) != SHA256_HEX_LENGTH or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256 version")
    return value


def parse_aware_datetime(value: object, *, label: str) -> datetime:
    """Parse one timezone-aware ISO 8601 timestamp and normalize it to UTC."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty timestamp string")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} is not a valid ISO 8601 timestamp") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone")
    return timestamp.astimezone(UTC)


def release_order_from_metadata(
    metadata: dict[str, object],
    *,
    run_started_at: datetime | None = None,
    label: str,
) -> ReleaseOrder:
    """Build a total release order from strict freshness metadata."""
    data_through_value = metadata.get("data_through")
    if not isinstance(data_through_value, str):
        raise ValueError(f"{label} data_through must be a YYYY-MM-DD string")
    try:
        data_through = date.fromisoformat(data_through_value)
    except ValueError as exc:
        raise ValueError(f"{label} data_through must be a valid YYYY-MM-DD date") from exc
    if data_through.isoformat() != data_through_value:
        raise ValueError(f"{label} data_through must use YYYY-MM-DD")
    started_at = run_started_at or parse_aware_datetime(
        metadata.get("last_updated"),
        label=f"{label} last_updated",
    )
    return ReleaseOrder(data_through=data_through, run_started_at=started_at)


def read_verified_json_object(
    s3: S3Client,
    *,
    bucket: str,
    key: object,
    sha256: object,
    label: str,
) -> dict[str, object]:
    """Read and checksum one immutable JSON object named by a pointer."""
    if not isinstance(key, str) or not key:
        raise ValueError(f"{label} key must be a non-empty string")
    if (
        not isinstance(sha256, str)
        or len(sha256) != SHA256_HEX_LENGTH
        or any(character not in "0123456789abcdef" for character in sha256)
    ):
        raise ValueError(f"{label} sha256 must be a lowercase SHA-256 digest")
    response = s3.get_object(Bucket=bucket, Key=key)
    body = response["Body"].read()
    if not isinstance(body, bytes):
        raise TypeError(f"{label} S3 body did not return bytes")
    if hashlib.sha256(body).hexdigest() != sha256:
        raise ValueError(f"{label} checksum does not match its pointer")
    return decode_json_object(body, label=label)


def _raise_changed_pointer(
    *,
    candidate_order: ReleaseOrder,
    current: StablePointerSnapshot,
) -> None:
    if current.order is not None and candidate_order.sort_key() <= current.order.sort_key():
        raise StablePointerRegression(
            "Refusing to replace an equal or newer stable release pointer"
        )
    raise StablePointerConflict(
        "Stable release pointer changed during publication; rerun from the new generation"
    )


def move_stable_pointer(
    s3: S3Client,
    *,
    bucket: str,
    key: str,
    body: bytes,
    version: str,
    order: ReleaseOrder,
    expected: StablePointerSnapshot,
    read_current: Callable[[], StablePointerSnapshot],
    content_type: str,
    cache_control: str,
) -> None:
    """CAS one pointer without permitting stale or ambiguous publication.

    A changed pointer is never automatically rebased because release manifests
    can carry N-1 history derived from the captured generation. The caller must
    rerun from the new pointer instead.
    """
    validate_release_version(version, label="Candidate release version")
    if expected.body == body:
        return
    if expected.order is not None and order.sort_key() <= expected.order.sort_key():
        raise StablePointerRegression(
            "Refusing to replace an equal or newer stable release pointer"
        )

    request: PutObjectRequestTypeDef = {
        "Bucket": bucket,
        "Key": key,
        "Body": body,
        "ContentType": content_type,
        "CacheControl": cache_control,
    }
    if expected.etag is None:
        request["IfNoneMatch"] = "*"
    else:
        request["IfMatch"] = expected.etag
    for attempt in range(MAX_CONDITIONAL_CONFLICT_RETRIES):
        try:
            s3.put_object(**request)
            return
        except ClientError as exc:
            code = _error_code(exc)
            try:
                current = read_current()
            except Exception:
                if code in {"409", "ConditionalRequestConflict"}:
                    raise StablePointerConflict(
                        "Conditional pointer write was ambiguous and current state "
                        "could not be verified"
                    ) from exc
                raise
            if current.body == body:
                return
            if code in {"412", "PreconditionFailed"}:
                _raise_changed_pointer(candidate_order=order, current=current)
            if code in {"409", "ConditionalRequestConflict"}:
                if current.etag == expected.etag and current.body == expected.body:
                    if attempt + 1 < MAX_CONDITIONAL_CONFLICT_RETRIES:
                        continue
                    raise StablePointerConflict(
                        "Conditional pointer write remained ambiguous after bounded retries"
                    ) from exc
                _raise_changed_pointer(candidate_order=order, current=current)
            raise
        except BotoCoreError as exc:
            try:
                current = read_current()
            except Exception as verification_error:
                raise exc from verification_error
            if current.body == body:
                return
            raise

    raise StablePointerConflict("Conditional pointer write exhausted bounded retries")


def move_stable_object(
    s3: S3Client,
    *,
    bucket: str,
    key: str,
    body: bytes,
    expected: StableObjectSnapshot,
    read_current: Callable[[], StableObjectSnapshot],
    content_type: str,
) -> None:
    """Replace exactly one captured mutable object revision or fail closed."""
    if expected.body == body:
        return
    request: PutObjectRequestTypeDef = {
        "Bucket": bucket,
        "Key": key,
        "Body": body,
        "ContentType": content_type,
    }
    if expected.etag is None:
        request["IfNoneMatch"] = "*"
    else:
        request["IfMatch"] = expected.etag

    for attempt in range(MAX_CONDITIONAL_CONFLICT_RETRIES):
        try:
            s3.put_object(**request)
            return
        except ClientError as exc:
            code = _error_code(exc)
            try:
                current = read_current()
            except Exception:
                if code in {"409", "ConditionalRequestConflict"}:
                    raise StableObjectConflict(
                        "Conditional object write was ambiguous and current state "
                        "could not be verified"
                    ) from exc
                raise
            if current.body == body:
                return
            if code in {"412", "PreconditionFailed"}:
                raise StableObjectConflict(
                    "Mutable object changed during publication; rerun from its new revision"
                ) from exc
            if code in {"409", "ConditionalRequestConflict"}:
                if current == expected:
                    if attempt + 1 < MAX_CONDITIONAL_CONFLICT_RETRIES:
                        continue
                    raise StableObjectConflict(
                        "Conditional object write remained ambiguous after bounded retries"
                    ) from exc
                raise StableObjectConflict(
                    "Mutable object changed during publication; rerun from its new revision"
                ) from exc
            raise
        except BotoCoreError as exc:
            try:
                current = read_current()
            except Exception as verification_error:
                raise exc from verification_error
            if current.body == body:
                return
            raise

    raise StableObjectConflict("Conditional object write exhausted bounded retries")
