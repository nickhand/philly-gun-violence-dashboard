"""Registry utility functions for geographic datasets."""

import functools
import importlib
from collections.abc import Callable, Generator
from typing import Any

import geopandas as gpd

from dashboard_utils.aws import make_s3_client, read_geojson_gdf, write_geojson_gdf
from dashboard_utils.env import s3_settings
from dashboard_utils.paths import get_reference_key

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
    Register and read geographic dataset functions.

    This decorator:
    - Registers the dataset loader function in REGISTRY
    - Reads the dataset from S3 when refresh=False
    - Recomputes and uploads to S3 when refresh=True
    """
    # Extract dataset name from the function name: assumes "get_<name>"
    name = func.__name__.split("get_")[-1]

    # Build cache path lazily to avoid touching filesystem at import time
    filepath = f"{name}.geojson"

    @functools.wraps(func)
    def wrapper(*args: Any, refresh: bool = False, **kwargs: Any) -> gpd.GeoDataFrame:
        """
        Read and handle refreshing of geographic dataset.

        Parameters
        ----------
        refresh : bool
            If True, recompute and overwrite the cache.
            If False (default), load from cache if present.
        """
        # Create S3 client
        s3 = make_s3_client()

        # Key in s3 is relative to the reference folder
        key = get_reference_key(filepath)

        if not refresh:
            return read_geojson_gdf(s3, bucket=s3_settings.AWS_BUCKET_NAME, key=key)

        # Compute fresh result
        gdf = func(*args, **kwargs)

        # Mirror to s3
        write_geojson_gdf(s3, s3_settings.AWS_BUCKET_NAME, key, gdf)

        # Return the GeoDataFrame
        return gdf

    # Register the wrapped function
    REGISTRY[name] = wrapper

    return wrapper
