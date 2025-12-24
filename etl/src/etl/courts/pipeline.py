"""Orchestration for scraping courts data from the PA UJS portal."""

import pandas as pd
from loguru import logger

from etl.courts.extract import PortalBatchConfig, extract_portal
from etl.courts.load import read_existing_flags, write_flags
from etl.courts.transform import results_to_flags
from etl.utils.paths import get_processed_path
from etl.utils.storage import load_shootings_database, write_meta

__all__ = ["update_courts"]


def update_courts(cfg: PortalBatchConfig | None = None) -> pd.DataFrame:
    """
    Run the courts portal scraper and update local flags.

    Parameters
    ----------
    cfg : PortalBatchConfig, optional
        Batch scraping configuration. If None, uses defaults.

    Returns
    -------
    pandas.DataFrame
        Updated flag table with columns ``dc_key`` and ``has_court_case``.
    """
    if cfg is None:
        cfg = PortalBatchConfig()

    # Get unique incident numbers from shootings database
    gdf = load_shootings_database()
    data = pd.DataFrame({"dc_key": gdf["dc_key"].astype(str).unique()})
    incident_numbers = data[["dc_key"]].drop_duplicates()

    # Remove dc_keys we already know are true
    if cfg.exclude_known_cases:
        existing = read_existing_flags()
        if not existing.empty:
            known_true = existing.loc[existing["has_court_case"], "dc_key"]
            incident_numbers = incident_numbers[~incident_numbers["dc_key"].isin(known_true)]

    # Extract from portal
    portal_results, echoed_input = extract_portal(incident_numbers, cfg)
    flags = results_to_flags(portal_results, echoed_input)

    # Merge with existing (keep any prior entries)
    out: pd.DataFrame
    if cfg.exclude_known_cases:
        out = pd.concat([existing, flags]).drop_duplicates(subset=["dc_key"], keep="last")
    else:
        out = flags

    # Sort by dc_key in ascending order
    out = out.sort_values("dc_key", ascending=True).reset_index(drop=True)

    # Save updated flags
    write_flags(out)
    logger.info(f"Saved courts flags to {get_processed_path('courts_flags')}")
    write_meta("courts")

    return out
