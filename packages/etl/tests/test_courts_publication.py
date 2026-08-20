"""Tests for the courts-to-shootings publication trust boundary."""

from copy import deepcopy
from io import StringIO

import pandas as pd
import pytest

from etl.courts.publication import (
    COURTS_PUBLICATION_CONTRACT_VERSION,
    CourtsPublicationError,
    court_flags_sha256,
    require_publishable_court_flags,
)
from etl.courts.semantics import COURT_SEARCH_SEMANTICS_VERSION


def _flags() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "dc_key": ["100", "200", "300"],
            "has_court_case": pd.array([True, False, pd.NA], dtype="boolean"),
            "court_search_semantics_version": [2, 2, 2],
        }
    )


def _metadata(flags: pd.DataFrame) -> dict[str, object]:
    return {
        "publication_contract_version": COURTS_PUBLICATION_CONTRACT_VERSION,
        "run_id": "run-full",
        "selection_mode": "full",
        "coverage_complete": True,
        "candidate_count": 3,
        "input_count": 3,
        "result_count": 3,
        "missing_result_count": 0,
        "extra_result_count": 0,
        "flags_row_count": len(flags),
        "flags_sha256": court_flags_sha256(flags),
        "court_search_semantics_version": COURT_SEARCH_SEMANTICS_VERSION,
    }


def test_publishable_flags_require_explicit_full_run_provenance() -> None:
    flags = _flags()

    result = require_publishable_court_flags(flags, _metadata(flags)).set_index("dc_key")

    assert bool(result.loc["100", "has_court_case"]) is True
    assert bool(result.loc["200", "has_court_case"]) is False
    assert pd.isna(result.loc["300", "has_court_case"])
    assert list(result.columns) == ["has_court_case"]


def test_flags_digest_is_independent_of_row_order() -> None:
    flags = _flags()

    assert court_flags_sha256(flags) == court_flags_sha256(flags.iloc[::-1])


def test_flags_digest_survives_stable_csv_round_trip() -> None:
    flags = _flags()
    serialized = flags.to_csv(index=False)
    restored = pd.read_csv(StringIO(serialized), dtype={"dc_key": str})

    assert court_flags_sha256(restored) == court_flags_sha256(flags)
    require_publishable_court_flags(restored, _metadata(flags))


@pytest.mark.parametrize("selection_mode", ["sample", "incremental", None])
def test_non_full_run_cannot_feed_shootings(selection_mode: object) -> None:
    flags = _flags()
    metadata = _metadata(flags)
    metadata["selection_mode"] = selection_mode

    with pytest.raises(CourtsPublicationError, match="explicit full run"):
        require_publishable_court_flags(flags, metadata)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("coverage_complete", False, "complete court-run input coverage"),
        ("candidate_count", 4, "inconsistent candidate/input counts"),
        ("result_count", 2, "one terminal result record"),
        ("missing_result_count", 1, "one terminal result record"),
        ("extra_result_count", 1, "one terminal result record"),
        ("flags_row_count", 2, "row count does not match"),
    ],
)
def test_inconsistent_coverage_evidence_fails_closed(
    field: str,
    value: object,
    message: str,
) -> None:
    flags = _flags()
    metadata = _metadata(flags)
    metadata[field] = value

    with pytest.raises(CourtsPublicationError, match=message):
        require_publishable_court_flags(flags, metadata)


def test_flags_must_match_metadata_generation_digest() -> None:
    flags = _flags()
    metadata = _metadata(flags)
    changed = flags.copy()
    changed.loc[changed["dc_key"] == "100", "has_court_case"] = False

    with pytest.raises(CourtsPublicationError, match="do not match.*generation"):
        require_publishable_court_flags(changed, metadata)


def test_every_flag_requires_current_semantics_even_with_matching_metadata() -> None:
    flags = _flags()
    metadata = _metadata(flags)
    legacy = deepcopy(flags)
    legacy.loc[legacy["dc_key"] == "200", "court_search_semantics_version"] = 1

    with pytest.raises(CourtsPublicationError, match="Every court flag.*version 2"):
        require_publishable_court_flags(legacy, metadata)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("publication_contract_version", True),
        ("candidate_count", 3.0),
        ("input_count", "3"),
        ("flags_sha256", "not-a-digest"),
        ("run_id", ""),
    ],
)
def test_malformed_provenance_fields_fail_closed(field: str, value: object) -> None:
    flags = _flags()
    metadata = _metadata(flags)
    metadata[field] = value

    with pytest.raises(CourtsPublicationError):
        require_publishable_court_flags(flags, metadata)
