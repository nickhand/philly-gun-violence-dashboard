from functools import lru_cache
from pathlib import Path


def get_repo_root() -> Path:
    """
    Find the root directory of the repository.

    Assumes this file is located at etl/src/etl/utils/paths.py
    """
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / ".git").exists():
            return parent

    raise FileNotFoundError("Repository root not found.")


def data_dir() -> Path:
    """Return the path to the data directory located at the root of the repository."""
    return get_repo_root() / "data"


def reference_data_dir() -> Path:
    """Return the path to the reference data directory in the data directory."""
    return data_dir() / "reference"


def processed_data_dir() -> Path:
    """Return the path to the processed data directory in the data directory."""
    return data_dir() / "processed"


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
def processed_inventory() -> dict[str, Path]:
    """
    Lazily build an inventory of processed dataset paths.

    Returns
    -------
    dict
        Mapping from dataset key to full Path under ``data/processed``.
    """
    base = processed_data_dir()
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
    inventory = processed_inventory()
    try:
        return inventory[key]
    except KeyError as exc:
        raise KeyError(
            f"Unknown processed dataset key '{key}'. Known keys: {sorted(inventory)}"
        ) from exc
