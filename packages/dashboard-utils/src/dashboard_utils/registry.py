"""Registry utility functions for geographic datasets."""

import functools
import importlib
from collections.abc import Callable, Generator
from typing import Any

import geopandas as gpd

from dashboard_utils.aws import make_s3_client, read_geojson_gdf, write_geojson_gdf
from dashboard_utils.config import get_s3_settings
from dashboard_utils.constants import REFERENCE_CRS
from dashboard_utils.paths import get_reference_key

# Track a registry of geographic datasets
REGISTRY: dict[str, Callable[..., gpd.GeoDataFrame]] = {}


def iter_datasets() -> Generator[str]:
    """Iterate over all registered geographic datasets."""
    yield from REGISTRY.keys()


def register_datasets(module_path: str) -> None:
    """Import a module to register its datasets."""
    importlib.import_module(module_path)


def get_geographic_data(
    name: str,
    refresh: bool = False,
    *,
    write_cache: bool = True,
) -> gpd.GeoDataFrame:
    """Retrieve a geographic dataset by name from the registry."""
    if name not in REGISTRY:
        raise ValueError(f"Geographic dataset '{name}' is not registered.")
    fn = REGISTRY[name]
    return fn(refresh=refresh, write_cache=write_cache)


def register_geodataset(func: Callable[..., gpd.GeoDataFrame]) -> Callable[..., gpd.GeoDataFrame]:
    """
    Register and read geographic dataset functions.

    This decorator:
    - Registers the dataset loader function in REGISTRY
    - Reads the dataset from S3 when refresh=False
    - Recomputes and uploads to S3 when refresh=True
    """
    # Extract the dataset name from a function named "get_<name>".
    function_name = getattr(func, "__name__", None)
    if not isinstance(function_name, str):
        raise TypeError("Geodataset loaders must be functions with a name.")
    if not function_name.startswith("get_"):
        raise ValueError("Geodataset loader names must start with 'get_'.")
    name = function_name.removeprefix("get_")

    # Build cache path lazily to avoid touching filesystem at import time
    filepath = f"{name}.geojson"

    @functools.wraps(func)
    def wrapper(
        *args: Any,
        refresh: bool = False,
        write_cache: bool = True,
        **kwargs: Any,
    ) -> gpd.GeoDataFrame:
        """
        Read and handle refreshing of geographic dataset.

        Parameters
        ----------
        refresh : bool
            If True, recompute and overwrite the cache.
            If False (default), load from cache if present.
        write_cache : bool
            When refreshing, whether to update the stable compatibility key.
            Atomic multi-dataset publishers disable this and write mirrors only
            after their generation pointer has moved successfully.
        """
        # Create S3 client
        s3 = make_s3_client()

        # Key in s3 is relative to the reference folder
        key = get_reference_key(filepath)

        if not refresh:
            return read_geojson_gdf(
                s3,
                bucket=get_s3_settings().s3_bucket,
                key=key,
            ).to_crs(REFERENCE_CRS)

        # Compute fresh result
        gdf = func(*args, **kwargs)

        # Mirror to s3 unless a multi-dataset publisher owns commit ordering.
        if write_cache:
            write_geojson_gdf(s3, get_s3_settings().s3_bucket, key, gdf)

        # Return the GeoDataFrame
        return gdf

    # Register the wrapped function
    REGISTRY[name] = wrapper

    return wrapper
