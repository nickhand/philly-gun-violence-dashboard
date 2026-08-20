"""Fail-closed publication contract for court-search flags."""

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

import pandas as pd

from etl.courts.semantics import (
    COURT_SEARCH_SEMANTICS_VERSION,
    COURT_SEARCH_SEMANTICS_VERSION_COLUMN,
    sanitize_court_search_flags,
)

COURTS_PUBLICATION_CONTRACT_VERSION = 1
COURTS_FULL_SELECTION_MODE = "full"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CourtsPublicationError(ValueError):
    """Raised when court flags cannot be proven safe for shootings publication."""


def _require_exact_int(metadata: Mapping[str, Any], field: str, *, minimum: int = 0) -> int:
    value = metadata.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise CourtsPublicationError(
            f"Courts metadata field {field!r} must be an integer >= {minimum}"
        )
    return value


def _require_current_semantics(flags: pd.DataFrame) -> None:
    if COURT_SEARCH_SEMANTICS_VERSION_COLUMN not in flags:
        raise CourtsPublicationError(
            "Courts flags are missing the court-search semantics version column"
        )
    versions = pd.to_numeric(
        flags[COURT_SEARCH_SEMANTICS_VERSION_COLUMN],
        errors="coerce",
    )
    if versions.isna().any() or not versions.eq(COURT_SEARCH_SEMANTICS_VERSION).all():
        raise CourtsPublicationError(
            "Every court flag must use court-search semantics version "
            f"{COURT_SEARCH_SEMANTICS_VERSION}"
        )


def court_flags_sha256(flags: pd.DataFrame) -> str:
    """Return a deterministic logical digest for one complete flags generation.

    The digest is independent of CSV formatting and row order. It binds the
    stable metadata object to the exact incident IDs and tri-state values that
    the shootings transform consumes.
    """
    _require_current_semantics(flags)
    sanitized = sanitize_court_search_flags(flags).sort_values("dc_key")
    records: list[list[str | bool | None]] = []
    for row in sanitized.itertuples(index=False):
        value = row.has_court_case
        records.append(
            [
                str(row.dc_key),
                None if pd.isna(value) else bool(value),
            ]
        )
    canonical = json.dumps(
        {
            "court_search_semantics_version": COURT_SEARCH_SEMANTICS_VERSION,
            "flags": records,
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def require_publishable_court_flags(
    flags: pd.DataFrame,
    metadata: object,
) -> pd.DataFrame:
    """Validate full-run provenance and return sanitized publishable flags.

    This is intentionally stricter than merely checking row semantics. A
    sample or incremental run may contain individually valid observations, but
    it is not permitted to become the court-flags generation consumed by a
    shootings release.
    """
    if not isinstance(metadata, Mapping):
        raise CourtsPublicationError("Courts metadata must be a JSON object")

    contract_version = _require_exact_int(
        metadata,
        "publication_contract_version",
        minimum=1,
    )
    if contract_version != COURTS_PUBLICATION_CONTRACT_VERSION:
        raise CourtsPublicationError(
            "Unsupported courts publication contract version "
            f"{contract_version}; expected {COURTS_PUBLICATION_CONTRACT_VERSION}"
        )

    run_id = metadata.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise CourtsPublicationError("Courts metadata must identify a nonblank run_id")

    selection_mode = metadata.get("selection_mode")
    if selection_mode != COURTS_FULL_SELECTION_MODE:
        raise CourtsPublicationError(
            "Shootings publication requires court flags from an explicit full run; "
            f"found selection_mode={selection_mode!r}"
        )
    if metadata.get("coverage_complete") is not True:
        raise CourtsPublicationError(
            "Shootings publication requires complete court-run input coverage"
        )

    candidate_count = _require_exact_int(metadata, "candidate_count", minimum=1)
    input_count = _require_exact_int(metadata, "input_count", minimum=1)
    result_count = _require_exact_int(metadata, "result_count", minimum=0)
    missing_result_count = _require_exact_int(metadata, "missing_result_count", minimum=0)
    extra_result_count = _require_exact_int(metadata, "extra_result_count", minimum=0)
    flags_row_count = _require_exact_int(metadata, "flags_row_count", minimum=1)

    if input_count != candidate_count:
        raise CourtsPublicationError(
            "Full courts metadata has inconsistent candidate/input counts: "
            f"{candidate_count} candidates, {input_count} inputs"
        )
    if result_count != input_count or missing_result_count != 0 or extra_result_count != 0:
        raise CourtsPublicationError(
            "Courts metadata does not prove one terminal result record per full-run input"
        )
    if flags_row_count != len(flags):
        raise CourtsPublicationError(
            "Courts flags row count does not match its metadata: "
            f"{len(flags)} rows, expected {flags_row_count}"
        )

    metadata_semantics = _require_exact_int(
        metadata,
        "court_search_semantics_version",
        minimum=1,
    )
    if metadata_semantics != COURT_SEARCH_SEMANTICS_VERSION:
        raise CourtsPublicationError(
            "Courts metadata uses court-search semantics version "
            f"{metadata_semantics}; expected {COURT_SEARCH_SEMANTICS_VERSION}"
        )

    expected_digest = metadata.get("flags_sha256")
    if not isinstance(expected_digest, str) or _SHA256_RE.fullmatch(expected_digest) is None:
        raise CourtsPublicationError("Courts metadata flags_sha256 is not a SHA-256 digest")
    actual_digest = court_flags_sha256(flags)
    if actual_digest != expected_digest:
        raise CourtsPublicationError(
            "Courts flags do not match the full-run generation named by metadata"
        )

    return sanitize_court_search_flags(flags)
