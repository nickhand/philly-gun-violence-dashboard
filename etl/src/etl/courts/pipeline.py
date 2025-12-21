"""
Orchestration for scraping courts data from the PA UJS portal.
"""

import pandas as pd
from loguru import logger

from .extract import PortalBatchConfig, extract_portal
from .load import DATA_PATH, read_existing_flags, write_flags
from etl.utils.paths import processed_data_dir
import geopandas as gpd
from .transform import results_to_flags

__all__ = ["update_courts", "merge_flags"]


def _load_shootings_default() -> pd.DataFrame:
    """
    Load the shootings GeoJSON from processed data for dc_key inputs.
    """
    path = processed_data_dir() / "shootings" / "shootings.geojson"
    if not path.exists():
        raise RuntimeError(f"Missing shootings database at {path}")
    gdf = gpd.read_file(path)
    return pd.DataFrame({"dc_key": gdf["dc_key"].astype(str).unique()})


def update_courts(
    data: pd.DataFrame | None = None,
    *,
    cfg: PortalBatchConfig | None = None,
    load_shootings=None,
) -> pd.DataFrame:
    """
    Run the courts portal scraper and update local flags.

    Parameters
    ----------
    data : pandas.DataFrame
        Input data with a ``dc_key`` column.
    data : pandas.DataFrame, optional
        Input data with a ``dc_key`` column. If None, attempts to load the
        shootings database via ``load_existing_shootings_database``.
    cfg : PortalBatchConfig, optional
        Batch scraping configuration. If None, uses defaults.
    load_shootings : callable, optional
        Function that returns a dataframe with a ``dc_key`` column when ``data``
        is not provided. Defaults to attempting to import from shootings.

    Returns
    -------
    pandas.DataFrame
        Updated flag table with columns ``dc_key`` and ``has_court_case``.
    """
    if cfg is None:
        cfg = PortalBatchConfig()

    if data is None:
        loader = load_shootings or _load_shootings_default
        data = loader()

    incident_numbers = data[["dc_key"]].drop_duplicates()

    # Remove dc_keys we already know are true
    existing = read_existing_flags()
    if not existing.empty:
        known_true = existing[existing["has_court_case"] == True]["dc_key"]
        incident_numbers = incident_numbers[
            ~incident_numbers["dc_key"].isin(known_true)
        ]

    portal_results, echoed_input = extract_portal(incident_numbers, cfg)
    flags = results_to_flags(portal_results, echoed_input)

    # Merge with existing (keep any prior entries)
    combined = pd.concat([existing, flags]).drop_duplicates(
        subset=["dc_key"], keep="last"
    )
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
