from functools import lru_cache
from pathlib import Path

from dashboard_utils.env import get_repo_root, is_prod_runtime, settings


def data_dir() -> str:
    """Return the path to the data directory located at the root of the repository."""
    # In production, data dir is an S3 bucket
    if is_prod_runtime():
        return f"s3://{settings.AWS_BUCKET_NAME}"
    # In local/dev, data dir is a local folder at the repo root
    else:
        return str(get_repo_root() / "data")


def reference_data_dir() -> Path:
    """Return the path to the reference data directory in the data directory."""
    return Path(data_dir()) / "reference"


def processed_data_dir() -> Path:
    """Return the path to the processed data directory in the data directory."""
    return Path(data_dir()) / "processed"


# -----------------------------------------------------------------------------
# Lazy processed path inventory
# -----------------------------------------------------------------------------

_PROCESSED_PATHS = {
    "shootings": ("shootings", "shootings.geojson"),
    "street_blocks": ("streets", "street_blocks.geojson"),
    "homicides_daily": ("homicides", "homicide_totals_daily.csv"),
    "homicides_totals": ("homicides", "homicide_totals.json"),
    "courts_flags": ("courts", "scraped_courts_data.csv"),
    "portal_results": ("courts", "portal_results.json"),
}


@lru_cache(maxsize=1)
def processed_data_inventory() -> dict[str, Path]:
    """
    Lazily build an inventory of processed dataset paths.

    Returns
    -------
    dict
        Mapping from dataset key to full Path under ``data/processed``.
    """
    base = Path(processed_data_dir())
    return {key: base.joinpath(*parts) for key, parts in _PROCESSED_PATHS.items()}


def get_processed_path(key: str) -> Path:
    """
    Retrieve a processed dataset path by key.

    Parameters
    ----------
    key : str
        Dataset identifier (e.g., "shootings", "homicides_daily").

    Returns
    -------
    pathlib.Path
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
