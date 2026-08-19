"""Load/save helpers for homicide statistics."""

import hashlib
import io
import json
from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd
from loguru import logger
from mypy_boto3_s3.client import S3Client

from dashboard_utils.config import get_s3_settings
from dashboard_utils.paths import get_processed_key
from etl.utils.release_pointer import (
    ReleaseOrder,
    StableObjectSnapshot,
    StablePointerSnapshot,
    decode_json_object,
    move_stable_object,
    move_stable_pointer,
    read_json_pointer,
    read_stable_object,
    read_verified_json_object,
    release_order_from_metadata,
    validate_release_version,
)

__all__ = [
    "HomicideReleaseCommittedError",
    "homicide_database_from_snapshot",
    "read_homicide_database_snapshot",
    "write_homicide_database",
    "write_homicide_release",
]

PROCESSED_RELEASE_CACHE_CONTROL: Final = "public,max-age=31536000,immutable"
RELEASE_POINTER_CACHE_CONTROL: Final = "no-cache"


class HomicideReleaseCommittedError(RuntimeError):
    """The authoritative release moved but a legacy mirror did not."""


@dataclass(frozen=True, slots=True)
class HomicidePublication:
    """Exact immutable homicide objects and their stable pointer."""

    release_id: str
    totals_body: bytes
    metadata_body: bytes
    pointer_body: bytes


def read_homicide_database_snapshot(s3: S3Client) -> StableObjectSnapshot:
    """Capture the exact daily-history revision before extraction begins."""
    return read_stable_object(
        s3,
        bucket=get_s3_settings().s3_bucket,
        key=get_processed_key("homicides_daily"),
        label="Homicide daily database",
    )


def homicide_database_from_snapshot(snapshot: StableObjectSnapshot) -> pd.DataFrame:
    """Parse the exact captured daily-history CSV used for conditional writing."""
    if snapshot.body is None:
        raise FileNotFoundError("Homicide daily database does not exist")
    try:
        database = pd.read_csv(io.BytesIO(snapshot.body), parse_dates=["date"])
    except (KeyError, UnicodeDecodeError, pd.errors.ParserError, ValueError) as exc:
        raise ValueError("Homicide daily database is not a valid CSV with dates") from exc
    missing = {"date", "total"} - set(database.columns)
    if missing:
        raise ValueError(f"Homicide daily database is missing columns: {sorted(missing)}")
    return database.sort_values("date")


def write_homicide_database(
    s3: S3Client,
    database: pd.DataFrame,
    *,
    expected_snapshot: StableObjectSnapshot,
) -> None:
    """
    Persist the homicide daily totals database.

    Parameters
    ----------
    s3 : S3Client
        The S3 client to use for uploading the database.
    database : pandas.DataFrame
        DataFrame with columns ``date`` and ``total``.
    """
    cleaned = database.drop_duplicates(subset=["date"], keep="last").sort_values("date")
    buffer = io.StringIO(newline="")
    cleaned.to_csv(buffer, index=False, lineterminator="\n")
    body = buffer.getvalue().encode("utf-8")
    move_stable_object(
        s3,
        bucket=get_s3_settings().s3_bucket,
        key=get_processed_key("homicides_daily"),
        body=body,
        expected=expected_snapshot,
        read_current=lambda: read_homicide_database_snapshot(s3),
        content_type="text/csv",
    )


def _json_body(value: object) -> bytes:
    """Return deterministic, strict JSON bytes for a release object."""
    return (
        json.dumps(value, allow_nan=False, indent=2, sort_keys=True, separators=(",", ": ")) + "\n"
    ).encode("utf-8")


def _prepare_homicide_publication(
    merged_totals: pd.DataFrame,
    metadata: dict[str, object],
) -> HomicidePublication:
    """Build and checksum every release object before writing to S3."""
    totals = merged_totals.set_index("year").replace({np.nan: None}).to_dict(orient="index")
    totals_body = _json_body(totals)
    metadata_body = _json_body({**metadata, "release_pointer_schema_version": 1})
    digest = hashlib.sha256(totals_body + b"\0" + metadata_body).hexdigest()
    prefix = get_s3_settings().s3_processed_prefix
    pointer = {
        "schema_version": 1,
        "version": f"sha256:{digest}",
        "totals": {
            "key": f"{prefix}/homicides/releases/{digest}/homicide_totals.json",
            "sha256": hashlib.sha256(totals_body).hexdigest(),
        },
        "metadata": {
            "key": f"{prefix}/homicides/releases/{digest}/meta.json",
            "sha256": hashlib.sha256(metadata_body).hexdigest(),
        },
    }
    return HomicidePublication(
        release_id=digest,
        totals_body=totals_body,
        metadata_body=metadata_body,
        pointer_body=_json_body(pointer),
    )


def _homicide_pointer_key() -> str:
    """Return the configured stable homicide release pointer key."""
    return f"{get_s3_settings().s3_processed_prefix}/homicides/release.json"


def _validate_homicide_member(
    value: object,
    *,
    expected_key: str,
    label: str,
) -> dict[str, object]:
    """Validate one checksummed immutable homicide release member."""
    if not isinstance(value, dict) or set(value) != {"key", "sha256"}:
        raise ValueError(f"{label} must contain only key and sha256")
    if value.get("key") != expected_key:
        raise ValueError(f"{label} has an invalid release key")
    checksum = value.get("sha256")
    if (
        not isinstance(checksum, str)
        or len(checksum) != 64
        or any(character not in "0123456789abcdef" for character in checksum)
    ):
        raise ValueError(f"{label} has an invalid sha256")
    return value


def read_homicide_pointer(s3: S3Client) -> StablePointerSnapshot:
    """Capture the exact homicide pointer revision before extraction begins."""
    settings = get_s3_settings()
    raw = read_json_pointer(
        s3,
        bucket=settings.s3_bucket,
        key=_homicide_pointer_key(),
        label="Homicide release pointer",
    )
    if raw is None:
        return StablePointerSnapshot.missing()
    pointer = raw.value
    if set(pointer) != {"schema_version", "version", "totals", "metadata"}:
        raise ValueError("Homicide release pointer has an invalid schema")
    if pointer.get("schema_version") != 1:
        raise ValueError("Homicide release pointer has an unsupported schema version")
    version = validate_release_version(
        pointer.get("version"),
        label="Homicide release pointer version",
    )
    release_id = version.removeprefix("sha256:")
    release_prefix = f"{settings.s3_processed_prefix}/homicides/releases/{release_id}"
    _validate_homicide_member(
        pointer.get("totals"),
        expected_key=f"{release_prefix}/homicide_totals.json",
        label="Homicide totals pointer",
    )
    metadata_pointer = _validate_homicide_member(
        pointer.get("metadata"),
        expected_key=f"{release_prefix}/meta.json",
        label="Homicide metadata pointer",
    )
    metadata = read_verified_json_object(
        s3,
        bucket=settings.s3_bucket,
        key=metadata_pointer["key"],
        sha256=metadata_pointer["sha256"],
        label="Homicide release metadata",
    )
    return StablePointerSnapshot(
        etag=raw.etag,
        body=raw.body,
        version=version,
        order=release_order_from_metadata(metadata, label="Homicide release metadata"),
    )


def _homicide_publication_identity(
    publication: HomicidePublication,
) -> tuple[str, ReleaseOrder]:
    """Validate a homicide pointer against its exact prepared metadata bytes."""
    pointer = decode_json_object(
        publication.pointer_body,
        label="Candidate homicide release pointer",
    )
    version = validate_release_version(
        pointer.get("version"),
        label="Candidate homicide release version",
    )
    if version != f"sha256:{publication.release_id}":
        raise ValueError("Candidate homicide pointer version does not match its release id")
    metadata_pointer = pointer.get("metadata")
    if not isinstance(metadata_pointer, dict):
        raise ValueError("Candidate homicide pointer has invalid metadata")
    if metadata_pointer.get("sha256") != hashlib.sha256(publication.metadata_body).hexdigest():
        raise ValueError("Candidate homicide metadata checksum does not match its bytes")
    metadata = decode_json_object(
        publication.metadata_body,
        label="Candidate homicide release metadata",
    )
    return version, release_order_from_metadata(
        metadata,
        label="Candidate homicide release metadata",
    )


def write_homicide_release(
    s3: S3Client,
    merged_totals: pd.DataFrame,
    metadata: dict[str, object],
    *,
    expected_pointer: StablePointerSnapshot,
) -> None:
    """Publish totals and metadata together behind one atomic pointer."""
    publication = _prepare_homicide_publication(merged_totals, metadata)
    settings = get_s3_settings()
    bucket = settings.s3_bucket
    release_prefix = f"{settings.s3_processed_prefix}/homicides/releases/{publication.release_id}"
    s3.put_object(
        Bucket=bucket,
        Key=f"{release_prefix}/homicide_totals.json",
        Body=publication.totals_body,
        ContentType="application/json; charset=utf-8",
        CacheControl=PROCESSED_RELEASE_CACHE_CONTROL,
    )
    s3.put_object(
        Bucket=bucket,
        Key=f"{release_prefix}/meta.json",
        Body=publication.metadata_body,
        ContentType="application/json; charset=utf-8",
        CacheControl=PROCESSED_RELEASE_CACHE_CONTROL,
    )

    version, order = _homicide_publication_identity(publication)
    move_stable_pointer(
        s3,
        bucket=bucket,
        key=_homicide_pointer_key(),
        body=publication.pointer_body,
        version=version,
        order=order,
        expected=expected_pointer,
        read_current=lambda: read_homicide_pointer(s3),
        content_type="application/json; charset=utf-8",
        cache_control=RELEASE_POINTER_CACHE_CONTROL,
    )

    # Compatibility mirrors follow the authoritative pointer. A pointer-aware
    # API therefore cannot observe a mixed pair during the first migration.
    try:
        s3.put_object(
            Bucket=bucket,
            Key=f"{settings.s3_processed_prefix}/homicides/homicide_totals.json",
            Body=publication.totals_body,
            ContentType="application/json; charset=utf-8",
        )
        s3.put_object(
            Bucket=bucket,
            Key=f"{settings.s3_processed_prefix}/homicides/meta.json",
            Body=publication.metadata_body,
            ContentType="application/json; charset=utf-8",
        )
    except Exception as exc:
        logger.exception(
            "Homicide release {} committed, but compatibility mirror update failed",
            publication.release_id,
        )
        raise HomicideReleaseCommittedError(
            f"Homicide release {publication.release_id} committed; "
            "compatibility mirror update failed"
        ) from exc
