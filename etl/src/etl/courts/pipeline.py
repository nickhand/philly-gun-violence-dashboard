"""
Orchestration for scraping courts data from the PA UJS portal.
"""

import pandas as pd
from loguru import logger

from .extract import PortalBatchConfig, extract_portal
from .load import DATA_PATH, read_existing_flags, write_flags
from .transform import results_to_flags

__all__ = ["update_courts", "merge_flags"]


def update_courts(
    data: pd.DataFrame,
    *,
    cfg: PortalBatchConfig | None = None,
) -> pd.DataFrame:
    """
    Run the courts portal scraper and update local flags.

    Parameters
    ----------
    data : pandas.DataFrame
        Input data with a ``dc_key`` column.
    cfg : PortalBatchConfig, optional
        Batch scraping configuration. If None, uses defaults.

    Returns
    -------
    pandas.DataFrame
        Updated flag table with columns ``dc_key`` and ``has_court_case``.
    """
    if cfg is None:
        cfg = PortalBatchConfig()

    incident_numbers = data[["dc_key"]].drop_duplicates()

    # Remove dc_keys we already know are true
    existing = read_existing_flags()
    if not existing.empty:
        known_true = existing[existing["has_court_case"] == True]["dc_key"]
        incident_numbers = incident_numbers[~incident_numbers["dc_key"].isin(known_true)]

    portal_results, echoed_input = extract_portal(incident_numbers, cfg)
    flags = results_to_flags(portal_results, echoed_input)

    # Merge with existing (keep any prior entries)
    combined = pd.concat([existing, flags]).drop_duplicates(subset=["dc_key"], keep="last")
    combined = combined.sort_values("dc_key")
    write_flags(combined)
    logger.info("Saved courts flags to %s", DATA_PATH)
    return combined


def merge_flags(data: pd.DataFrame, debug: bool = False) -> pd.DataFrame:
    """
    Merge courts flags into an existing dataframe by dc_key.
    """
    existing = read_existing_flags()
    if existing.empty:
        if debug:
            logger.debug("No existing courts data at %s", DATA_PATH)
        data = data.copy()
        data["has_court_case"] = False
        return data

    if debug:
        logger.debug("Merging courts flags into dataframe")
    return data.merge(existing, on="dc_key", how="left").assign(
        has_court_case=lambda df: df["has_court_case"].fillna(False)
    )
