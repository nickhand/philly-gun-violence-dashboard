from typing import cast

import geopandas as gpd
import networkx as nx
from geopandas import GeoDataFrame

from dashboard_utils.models.streets import StreetBlockSchema
from etl.utils.misc import number_to_string


def dedupe_streets(gdf: GeoDataFrame, street_col: str = "street_name") -> GeoDataFrame:
    """
    Deduplicate street segments.

    This function removes segments that are spatial duplicates or strictly
    contained within others on the same street.

    Strategy:
    - Use a spatial self-join with predicate='within' to find segments whose
      geometry is fully inside another segment with the same street name.
    - Also detect exact geometry duplicates (same street_name + same geometry).
    - Build connected components of these relationships.
    - For each component, keep only the longest segment and drop the rest.

    Parameters
    ----------
    gdf : GeoDataFrame
        Input street centerline GeoDataFrame. Must be in a projected CRS.
    street_col : str, default "street_name"
        Column containing the street name.

    Returns
    -------
    GeoDataFrame
        A copy of `gdf` with duplicate/contained segments removed.
    """
    if gdf.crs is None or gdf.crs.is_geographic:
        raise ValueError(
            "dedupe_streets expects a projected CRS; call .to_crs(...) first "
            "if you're in EPSG:4326."
        )

    gdf = gdf.copy().reset_index(drop=True)
    gdf["__gid"] = gdf.index
    gdf["__length"] = gdf.geometry.length

    # --- 1. Find within-duplicates on the same street via spatial self-join ---
    left = gdf[["__gid", street_col, "geometry"]]
    right = left.copy()

    within_pairs = gpd.sjoin(
        left,
        right,
        how="inner",
        predicate="within",
        lsuffix="inner",
        rsuffix="outer",
    )

    # Drop self-pairs
    within_pairs = within_pairs[within_pairs["__gid_inner"] != within_pairs["__gid_outer"]]

    # Only care about same-street pairs
    within_pairs = within_pairs[
        within_pairs[f"{street_col}_inner"] == within_pairs[f"{street_col}_outer"]
    ]

    # Keep just the ids we need
    within_pairs = within_pairs[["__gid_inner", "__gid_outer"]].drop_duplicates()

    # --- 2. Also detect exact-geometry duplicates on the same street ---
    # Use WKB as a stable hash for geometry equality
    # (GeoPandas 0.14+ has .geometry.to_wkb(); older versions use .apply)
    wkb = gdf.geometry.to_wkb()
    dup_groups = gdf.groupby([street_col, wkb])["__gid"].apply(list).reset_index(name="gids")

    equal_edges = []
    for _, row in dup_groups.iterrows():
        gids = row["gids"]
        if len(gids) > 1:
            # connect all gids in this group (chain is enough)
            for i in range(len(gids) - 1):
                equal_edges.append((gids[i], gids[i + 1]))

    # --- 3. Build graph of duplicate relationships ---
    G: nx.Graph[int] = nx.Graph()
    G.add_nodes_from(gdf["__gid"])

    # edges from within (contained) relationships
    G.add_edges_from(within_pairs.itertuples(index=False, name=None))

    # edges from exact-geometry duplicates
    G.add_edges_from(equal_edges)

    # --- 4. For each connected component, keep only the longest segment ---
    keep_gids: set[int] = set()
    for comp in nx.connected_components(G):
        comp_list = list(comp)

        # If this component has no duplicate relationships (isolated node),
        # comp_list will be size 1 and we just keep it.
        if len(comp_list) == 1:
            keep_gids.add(comp_list[0])
            continue

        sub = gdf[gdf["__gid"].isin(comp_list)]
        # pick the row with the maximum length
        keep_gid = sub.loc[sub["__length"].idxmax(), "__gid"]
        keep_gids.add(cast(int, keep_gid))

    cleaned = gdf[gdf["__gid"].isin(keep_gids)].copy()
    cleaned = cleaned.drop(columns=["__gid", "__length"])

    return cleaned


def centerlines_to_blocks(centerlines: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Street centerlines in Philadelphia, aggregated by block."""
    # 1. Normalize street name (case, whitespace)
    gdf = centerlines.copy()
    gdf["street_name"] = gdf["street_name"].str.upper().str.strip()

    # 2. Drop rows without a usable block
    gdf = gdf.dropna(subset=["block_number"])

    # 3. Dissolve geometries to block level
    blocks = gdf.dissolve(
        by=["street_name", "block_number"],
        as_index=False,  # keep cols instead of index
    )

    # 4. Add a nice label
    blocks["block_label"] = (
        blocks["block_number"]
        .apply(number_to_string)
        .str.cat(
            blocks["street_name"],
            sep=" BLOCK ",
        )
    )

    # 5. Give each block a unique id
    blocks = blocks.reset_index(drop=True).copy()
    blocks["segment_id"] = blocks.index
    blocks["segment_id"] = blocks["segment_id"].astype(str)

    # 6. De-duplicate segments
    blocks = dedupe_streets(blocks, street_col="street_name")

    # 7. Validate each record
    # NOTE: we don't validate geometry so drop it
    for record in blocks.drop(columns=["geometry"]).to_dict(orient="records"):
        StreetBlockSchema.model_validate(record)

    return blocks
