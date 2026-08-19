"""Trust boundary for persisted court-search flags."""

import numpy as np
import pandas as pd

COURT_SEARCH_SEMANTICS_VERSION = 2
COURT_SEARCH_SEMANTICS_VERSION_COLUMN = "court_search_semantics_version"


def _normalize_persisted_flag(value: object) -> bool | None:
    """Parse the narrow boolean/null vocabulary written by pandas CSV output."""
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (float, np.floating)) and np.isnan(value):
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        if normalized == "True":
            return True
        if normalized == "False":
            return False
    raise ValueError(f"Court-search flag contains unsupported value {value!r}")


def sanitize_court_search_flags(flags: pd.DataFrame) -> pd.DataFrame:
    """Return nullable flags whose negative evidence has trusted provenance.

    Historical files had no semantics marker and filled failed, missing, and
    unsearched rows with ``False``. Their true values remain useful evidence,
    but false is retained only on a row explicitly marked with semantics v2.
    """
    required = {"dc_key", "has_court_case"}
    missing = required.difference(flags.columns)
    if missing:
        raise ValueError(f"Courts flags dataset is missing required columns: {sorted(missing)}")

    output = flags.loc[:, ["dc_key", "has_court_case"]].copy()
    if output["dc_key"].isna().any():
        raise ValueError("Courts flags dataset contains a missing dc_key")
    output["dc_key"] = output["dc_key"].astype(str)
    if output["dc_key"].str.strip().eq("").any():
        raise ValueError("Courts flags dataset contains a blank dc_key")
    duplicated = output.loc[output["dc_key"].duplicated(keep=False), "dc_key"].unique()
    if len(duplicated):
        raise ValueError(f"Courts flags dataset contains duplicate dc_key values: {duplicated[:5]}")

    normalized = pd.Series(
        pd.array(
            [_normalize_persisted_flag(value) for value in flags["has_court_case"]],
            dtype="boolean",
        ),
        index=flags.index,
    )
    if COURT_SEARCH_SEMANTICS_VERSION_COLUMN in flags:
        versions = pd.to_numeric(
            flags[COURT_SEARCH_SEMANTICS_VERSION_COLUMN],
            errors="coerce",
        )
        trusted = versions.eq(COURT_SEARCH_SEMANTICS_VERSION).fillna(False)
    else:
        trusted = pd.Series(False, index=flags.index, dtype=bool)

    untrusted_false = normalized.eq(False).fillna(False) & ~trusted
    output["has_court_case"] = normalized.mask(untrusted_false, pd.NA).astype("boolean")
    return output.reset_index(drop=True)
