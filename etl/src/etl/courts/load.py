"""Load/save helpers for courts portal scraping results."""

import json

import pandas as pd

from etl.courts.portal.schema import PortalResult
from etl.utils.aws import mirror_to_s3
from etl.utils.paths import get_processed_path

__all__ = ["read_existing_flags", "write_flags"]


def read_existing_flags() -> pd.DataFrame:
    """Read existing dc_key/has_court_case flags if present."""
    data_path = get_processed_path("courts_flags")
    if not data_path.exists():
        return pd.DataFrame(columns=["dc_key", "has_court_case"])
    return pd.read_csv(data_path, dtype={"dc_key": str})


def write_flags(df: pd.DataFrame) -> None:
    """Persist flags to CSV."""
    data_path = get_processed_path("courts_flags")
    data_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(data_path, index=False)
    mirror_to_s3(data_path)


def write_portal_results(portal_results: list[PortalResult]) -> None:
    """Write portal results to processed data folder.

    Parameters
    ----------
    portal_results : list[PortalResult]
        List of portal result objects.
    """
    data_path = get_processed_path("portal_results")
    data_path.parent.mkdir(parents=True, exist_ok=True)

    # Save to a JSON file locally
    result_dicts = [r.model_dump() for r in portal_results]
    json.dump(result_dicts, data_path.open("w"))

    # Mirror to s3 too
    mirror_to_s3(data_path)
