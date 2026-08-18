import geopandas as gpd
from loguru import logger

from etl.utils.storage import load_street_blocks


def _pick_best_match(
    df: gpd.GeoDataFrame,
    block_column: str = "parsed_block_num",
) -> gpd.GeoDataFrame:
    """Pick the best matching street block for a shooting incident.

    Parameters
    ----------
    df : geopandas.GeoDataFrame
        The GeoDataFrame containing all candidate street block matches for a
        single shooting incident.
    block_column : str, optional
        The name of the column containing the parsed block number for the shooting
        incident, by default "parsed_block_num".

    Returns
    -------
    geopandas.GeoDataFrame
        A single-row GeoDataFrame with the best matching street block.
    """
    # df = all rows for one shooting_id
    # 1. Prefer a match where block_num == parsed_block_num
    exact = df[df["block_number"] == df[block_column]]
    if len(exact) == 1:
        return exact.iloc[[0]]
    elif len(exact) > 1:
        # rare, but pick nearest among them
        return exact.sort_values("dist").iloc[[0]]

    # 2. Fallback: nearest geometry
    return df.sort_values("dist").iloc[[0]]


def join_with_street_blocks(
    shootings_df: gpd.GeoDataFrame,
    block_column: str = "parsed_block_num",
) -> gpd.GeoDataFrame:
    """Join shootings with street block geometries."""
    if block_column not in shootings_df.columns:
        raise ValueError(
            "shootings_df must have 'parsed_block_num' column to join with street blocks."
        )

    # Logging
    logger.info("Joining with street blocks dataset")

    # Load street blocks dataset and trim to the necessary columns
    blocks = load_street_blocks()[["geometry", "block_number", "street_name", "segment_id"]]

    # Use a spatial join to find nearest block
    joined = (
        gpd.sjoin_nearest(shootings_df, blocks, how="left", distance_col="dist")
        .reset_index(drop=False)
        .rename(columns={"index": "shooting_id"})
    )

    # De-duplicate to pick best match per shooting; keep shooting_id via index
    out: gpd.GeoDataFrame = (
        joined.groupby("shooting_id", group_keys=True)
        .apply(
            _pick_best_match,
            block_column=block_column,
            include_groups=False,
        )  # ty: ignore[no-matching-overload]  # pandas-stubs omits include_groups.
        .reset_index(level=0)
    )

    # Make sure block number is an int, even if it's missing
    out["block_number"] = out["block_number"].astype("Int64")

    # Return with unnecessary columns dropped
    return out.drop(columns=["dist", "index_right", "shooting_id"])
