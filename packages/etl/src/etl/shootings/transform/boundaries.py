import geopandas as gpd
import numpy as np
import pandas as pd
from loguru import logger

from dashboard_utils.registry import get_geographic_data, iter_datasets, register_datasets

from ..extract import fetch_criminal_incidents

__all__ = ["join_with_boundary_datasets"]


def _run_spatial_join(
    data: gpd.GeoDataFrame,
    geo: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Merge a geographic dataset into the data GeoDataFrame using a spatial join.

    Parameters
    ----------
    data : geopandas.GeoDataFrame
        The input data with point geometries.
    geo : geopandas.GeoDataFrame
        The geographic dataset with polygon geometries.

    Returns
    -------
    geopandas.GeoDataFrame
        The merged GeoDataFrame with new geographic columns.
    """
    # Do the spatial join
    out = gpd.sjoin(data, geo, how="left", predicate="within")

    # NOTE: sometimes this will match multiple geo boundaries
    # REMOVE THEM
    duplicated = out.index.duplicated()
    if duplicated.sum():
        out = out.loc[~duplicated]

    return out.drop(labels=["index_right"], axis=1)


def _backfill_location_data(df: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Backfill missing location data from criminal incidents dataset."""
    # The list of dc keys for missing geometries
    dc_key_list = ", ".join(df.loc[df.geometry.isnull(), "dc_key"].apply(lambda x: f"'{x}'"))

    # Query with a post request
    where = f"dc_key IN ( {dc_key_list} )"
    incidents = fetch_criminal_incidents(
        where=where,
        fields=["dc_key"],
    )

    # Ensure dc_key is string
    incidents["dc_key"] = incidents["dc_key"].astype(str)

    # Did we get any matches?
    missing = df.geometry.isnull().sum()
    matches = len(incidents)
    logger.info(f"Found {matches} matches for {missing} missing geometries")

    # Merge
    if matches > 0:
        missing_sel = df.geometry.isnull()
        missing_df = df.loc[missing_sel]
        df2 = missing_df.drop(columns=["geometry"]).merge(
            incidents[["dc_key", "geometry"]].drop_duplicates(subset=["dc_key"]),
            on="dc_key",
            how="left",
        )

        # Combine the dataframes with new matches and return
        return gpd.GeoDataFrame(
            pd.concat(
                [df.loc[~missing_sel], df2],
                axis=0,
            ).reset_index(drop=True)
        )

    # Return original dataframe if no matches
    return df


def join_with_boundary_datasets(df: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Add geographic columns to the input dataframe."""
    # Register the geographic datasets
    register_datasets("etl.boundaries.extract")

    # Get a fresh copy
    df = df.copy().reset_index(drop=True)
    assert df.crs is not None

    # The original length
    original_length = len(df)

    # -------------------------------------------------------------------------
    # 1. Set locations outside city limits to null
    # -------------------------------------------------------------------------

    # Check city limits
    city_limits = get_geographic_data("city_limits")
    city_limits = city_limits.to_crs(df.crs)
    outside_limits = ~df.geometry.within(city_limits.iloc[0].geometry)
    missing = outside_limits.sum()

    # Set missing geometry to null
    logger.info(f"{missing} shootings outside city limits")
    if missing > 0:
        df.loc[outside_limits, "geometry"] = np.nan

    # -------------------------------------------------------------------------
    # 2. Backfill missing location data from criminal incidents dataset
    # -------------------------------------------------------------------------
    df = _backfill_location_data(df)
    assert df.crs is not None

    # -------------------------------------------------------------------------
    # 3. Add geographic columns
    # -------------------------------------------------------------------------
    for dataset in iter_datasets():
        # Skip city limits
        if dataset == "city_limits":
            continue
        logger.info(f"Joining with geographic dataset: {dataset}")

        # Track original columns
        original_columns = set(df.columns)

        # Load the geo dataset
        geo = get_geographic_data(dataset)
        geo = geo.to_crs(df.crs)

        # Merge
        df = df.pipe(_run_spatial_join, geo)

        new_columns = set(df.columns) - original_columns
        if len(new_columns) != 1:
            raise ValueError(f"Expected one new column from merging {dataset}, got {new_columns}")

        # Note: We do NOT invalidate geometry when boundary join fails.
        # A point may be within city limits but fall outside a specific boundary
        # layer (e.g., school catchments) due to boundary misalignment.
        # The boundary column will be null but the point should still be mappable.

    # Check the length
    if len(df) != original_length:
        raise ValueError("Length of data has changed; this shouldn't happen!")

    return df
