from functools import lru_cache
from posixpath import join as posix_join

from dashboard_utils.config import get_s3_settings


def data_dir() -> str:
    """Return the S3 path for the data directory."""
    return f"s3://{get_s3_settings().s3_bucket}"


def reference_data_dir() -> str:
    """Return the S3 path to the reference data directory."""
    return posix_join(data_dir(), get_s3_settings().s3_reference_prefix)


def processed_data_dir() -> str:
    """Return the S3 path to the processed data directory."""
    return posix_join(data_dir(), get_s3_settings().s3_processed_prefix)


# -----------------------------------------------------------------------------
# Lazy processed path inventory
# -----------------------------------------------------------------------------

_PROCESSED_PATHS = {
    "shootings": ("shootings", "shootings.geojson"),
    "shootings_meta": ("shootings", "meta.json"),
    "street_blocks": ("streets", "street_blocks.geojson"),
    "homicides_daily": ("homicides", "homicide_totals_daily.csv"),
    "homicides_totals": ("homicides", "homicide_totals.json"),
    "homicides_meta": ("homicides", "meta.json"),
    "courts_flags": ("courts", "scraped_courts_data.csv"),
    "courts_meta": ("courts", "meta.json"),
    "portal_results": ("courts", "portal_results.json"),
}


@lru_cache(maxsize=1)
def processed_data_inventory() -> dict[str, str]:
    """
    Lazily build an inventory of processed dataset paths.

    Returns
    -------
    dict
        Mapping from dataset key to full S3 path under ``data/processed``.
    """
    base = processed_data_dir()
    return {key: posix_join(base, *parts) for key, parts in _PROCESSED_PATHS.items()}


def get_processed_path(key: str) -> str:
    """
    Retrieve a processed dataset path by key.

    Parameters
    ----------
    key : str
        Dataset identifier (e.g., "shootings", "homicides_daily").

    Returns
    -------
    str
        The corresponding processed dataset path.

    Raises
    ------
    KeyError
        If the key is not recognized.
    """
    inventory = processed_data_inventory()
    try:
        return inventory[key]
    except KeyError as exc:
        raise KeyError(
            f"Unknown processed dataset key '{key}'. Known keys: {sorted(inventory)}"
        ) from exc


def get_processed_key(key: str) -> str:
    """Return the processed S3 key for a dataset identifier."""
    try:
        parts = _PROCESSED_PATHS[key]
    except KeyError as exc:
        raise KeyError(
            f"Unknown processed dataset key '{key}'. Known keys: {sorted(_PROCESSED_PATHS)}"
        ) from exc
    return posix_join(get_s3_settings().s3_processed_prefix, *parts)


def get_reference_key(name: str) -> str:
    """Return the reference S3 key for a dataset name."""
    return posix_join(get_s3_settings().s3_reference_prefix, name)
