"""Registery utility functions for geographic datasets."""

import functools
import importlib
from collections.abc import Callable, Generator
from typing import Any

import geopandas as gpd

from dashboard_utils.aws import make_s3_client, upload_file
from dashboard_utils.env import settings
from dashboard_utils.paths import data_dir, reference_data_dir

# Track a registry of geographic datasets
REGISTRY: dict[str, Callable[..., gpd.GeoDataFrame]] = {}


def iter_datasets() -> Generator[str]:
    """Iterate over all registered geographic datasets."""
    yield from REGISTRY.keys()


def register_datasets(module_path: str) -> None:
    """Import a module to register its datasets."""
    importlib.import_module(module_path)


def get_geographic_data(name: str, refresh: bool = False) -> gpd.GeoDataFrame:
    """Retrieve a geographic dataset by name from the registry."""
    if name not in REGISTRY:
        raise ValueError(f"Geographic dataset '{name}' is not registered.")
    fn = REGISTRY[name]
    return fn(refresh=refresh)


def register_geodataset(func: Callable[..., gpd.GeoDataFrame]) -> Callable[..., gpd.GeoDataFrame]:
    """
    Register and cache geographic dataset functions.

    This decorator:
    - Registers the dataset loader function in REGISTRY
    - Caches the result to data/reference/<name>.geojson
    - Allows bypassing cache with refresh=True
    """
    # Extract dataset name from the function name: assumes "get_<name>"
    name = func.__name__.split("get_")[-1]

    # Build cache path lazily to avoid touching filesystem at import time
    filepath = f"{name}.geojson"

    @functools.wraps(func)
    def wrapper(*args: Any, refresh: bool = False, **kwargs: Any) -> gpd.GeoDataFrame:
        """
        Cache and handle refreshing of geographic dataset.

        Parameters
        ----------
        refresh : bool
            If True, recompute and overwrite the cache.
            If False (default), load from cache if present.
        """
        # Create S3 client
        s3 = make_s3_client()

        # Determine cache path
        cache_path = reference_data_dir().joinpath(filepath)

        if not refresh and cache_path.exists():
            return gpd.read_file(cache_path)

        # Compute fresh result
        gdf = func(*args, **kwargs)
        gdf.to_file(cache_path, driver="GeoJSON")

        # Key in s3 is relative to data_dir
        key = str(cache_path.relative_to(data_dir()))

        # Mirror to s3
        upload_file(
            s3,
            cache_path,
            bucket=settings.AWS_BUCKET_NAME,
            key=key,
            content_type="application/geo+json",
        )

        # Return the GeoDataFrame
        return gdf

    # Register the wrapped function
    REGISTRY[name] = wrapper

    return wrapper
