import re

import geopandas as gpd
import numpy as np
import pandas as pd
from loguru import logger
from mypy_boto3_s3.client import S3Client
from shapely.geometry import Point

from dashboard_utils.constants import DATE_FORMAT
from dashboard_utils.models.shootings import ShootingVictimsSchema
from etl.courts.semantics import sanitize_court_search_flags
from etl.shootings.transform.boundaries import join_with_boundary_datasets
from etl.shootings.transform.streets import join_with_street_blocks
from etl.utils.storage import load_courts_flags, load_shootings_database

__all__ = ["clean_shootings"]

BINARY_COLUMNS = ("fatal", "inside", "outside", "latino")
TRUE_BINARY_STRINGS = frozenset({"1", "1.0", "true", "t", "yes", "y"})
FALSE_BINARY_STRINGS = frozenset({"0", "0.0", "false", "f", "no", "n"})
MAX_FATAL_COUNT_DECREASE = 10


def _normalize_binary_value(value: object, column: str) -> bool:
    """Normalize a source binary value without silently guessing."""
    if value is None or value is pd.NA or value is pd.NaT:
        raise ValueError(f"Raw shootings column '{column}' contains a missing binary value")
    if isinstance(value, (float, np.floating)) and np.isnan(value):
        raise ValueError(f"Raw shootings column '{column}' contains a missing binary value")

    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in TRUE_BINARY_STRINGS:
            return True
        if normalized in FALSE_BINARY_STRINGS:
            return False
    elif isinstance(value, (bool, np.bool_)):
        return bool(value)
    elif isinstance(value, (int, float, np.integer, np.floating)):
        if value == 1:
            return True
        if value == 0:
            return False

    raise ValueError(f"Raw shootings column '{column}' contains unsupported binary value {value!r}")


def _normalize_binary_columns(df: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Return a copy with source binary fields normalized to real booleans."""
    normalized = df.copy()
    for column in BINARY_COLUMNS:
        normalized[column] = [
            _normalize_binary_value(value, column) for value in normalized[column].tolist()
        ]
    return normalized


def _require_plausible_outcomes(df: pd.DataFrame) -> None:
    """Reject a dataset that has lost either fatal or nonfatal victims."""
    fatal_count = int(df["fatal"].sum())
    nonfatal_count = len(df) - fatal_count
    if fatal_count == 0 or nonfatal_count == 0:
        raise ValueError(
            "Shootings outcome quality check failed: found "
            f"{fatal_count:,d} fatal and {nonfatal_count:,d} nonfatal victims; "
            "refusing to publish the dataset."
        )


def _run_checks(df_new: gpd.GeoDataFrame, *, s3: S3Client | None = None) -> None:
    """Validate shooting victims data."""
    # Get the existing data
    df_old = load_shootings_database(s3=s3)

    # Check for too many rows
    TOLERANCE = 100
    if len(df_new) - len(df_old) > TOLERANCE:
        logger.info(f"Length of new data: {len(df_new)}")
        logger.info(f"Length of old data: {len(df_old)}")
        raise ValueError(
            "New data seems to have too many rows...please manually confirm new data is correct."
        )

    # Check for too few rows
    TOLERANCE = 10
    if len(df_old) - len(df_new) > TOLERANCE:
        logger.info(f"Length of new data: {len(df_new)}")
        logger.info(f"Length of old data: {len(df_old)}")
        raise ValueError(
            "New data seems to have too few rows...please manually confirm new data is correct."
        )

    # Fatal shootings are cumulative historical records. A small decrease can
    # reflect source revisions, but a large drop is usually a parsing or source
    # schema regression and must not replace the known-good dataset.
    old_fatal_count = int(df_old["fatal"].sum())
    new_fatal_count = int(df_new["fatal"].sum())
    if old_fatal_count - new_fatal_count > MAX_FATAL_COUNT_DECREASE:
        logger.info(f"Fatal count in new data: {new_fatal_count}")
        logger.info(f"Fatal count in old data: {old_fatal_count}")
        raise ValueError(
            "New data has an implausible decrease in fatal shooting victims; "
            "please manually confirm the source data is correct."
        )


def _parse_location_block_num(s: str) -> int | None:
    """
    Parse a location string into a canonical block number.

    Handles examples like:
    - '500 block of EXAMPLE ST'
    - '500 BLOCK EXAMPLE ST'
    - '1000 W Dakota St'
    - '5200-5202 N 5TH ST' (takes the first number)
    """
    if not isinstance(s, str):
        return None

    s_clean = s.strip()

    # 1) If it explicitly mentions 'block', use that number
    #    e.g. '500 block of Example St' or '5300 BLOCK N 5TH ST'
    m_block = re.search(r"(\d+)\s*block", s_clean, flags=re.IGNORECASE)
    if m_block:
        num = int(m_block.group(1))
        return (num // 100) * 100

    # 2) Otherwise, look for a leading house number at the start of the string
    #    e.g. '1000 W Dakota St', '5200-5202 N 5TH ST'
    m_addr = re.match(r"^\s*(\d+)", s_clean)
    if m_addr:
        num = int(m_addr.group(1))
        return (num // 100) * 100

    # 3) If nothing matches (intersections like '52ND ST & MARKET ST', etc.), return None
    return None


def _validate_against_schema(df: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Validate the dataframe against the shooting victims schema."""
    # Check for missing columns
    fields = list(ShootingVictimsSchema.model_fields.keys())
    if any(col not in df.columns for col in fields):
        missing = [col for col in fields if col not in df.columns]
        raise ValueError(f"Missing columns for schema validation: {missing}")

    # Trim to just the schema fields
    # NOTE: this ignores geometry for now
    df_trimmed = df[fields]

    # Validate each row
    for i, row in df_trimmed.iterrows():
        # Convert to dict, replacing NaN with None
        result = {k: (None if pd.isna(v) else v) for k, v in row.to_dict().items()}

        # Validate
        try:
            ShootingVictimsSchema.model_validate(result)
        except Exception as e:
            raise ValueError(f"Row {i} in shootings data failed schema validation") from e

    return df[fields + ["geometry"]]


def clean_shootings(
    s3: S3Client,
    df: gpd.GeoDataFrame,
    *,
    ignore_checks: bool = False,
) -> gpd.GeoDataFrame:
    """Transform shooting victims data.

    Parameters
    ----------
    s3 : S3Client
        The S3 client to use.
    df : geopandas.GeoDataFrame
        Raw shootings data.
    ignore_checks : bool, optional
        If ``True``, skip validation checks.

    Returns
    -------
    geopandas.GeoDataFrame
        The cleaned and transformed shootings data.
    """
    # Remove officer involved
    df = df.query("officer_involved == 'N'")

    # Verify DC key first
    missing_dc_keys = df["dc_key"].isnull()
    if missing_dc_keys.sum() and not ignore_checks:
        n = missing_dc_keys.sum()
        raise ValueError(f"Found {n} rows with missing DC keys")

    # CARTO has returned these fields as both numeric 0/1 and string "0"/"1"
    # over time. Normalize both forms before any downstream logic uses them.
    df = _normalize_binary_columns(df)

    # Format
    df = (
        df.assign(
            time=lambda df: df.time.replace("<Null>", np.nan).fillna("00:00:00"),
            date=lambda df: pd.to_datetime(df.date_.str.slice(0, 10).str.cat(df.time, sep=" ")),
            dc_key=lambda df: df.dc_key.astype(float).astype(int).astype(str),
            year=lambda df: df.date.dt.year,
            race=lambda df: df.race.fillna("Other/Unknown"),
            age=lambda df: df.age.astype(float),
            age_group=lambda df: np.select(
                [
                    df.age <= 17,
                    (df.age > 17) & (df.age <= 30),
                    (df.age > 30) & (df.age <= 45),
                    (df.age > 45),
                ],
                ["Younger than 18", "18 to 30", "31 to 45", "Older than 45"],
                default="Unknown",
            ),
        )
        .assign(
            race=lambda df: df.race.where(~df.latino, other="H"),
        )
        .drop(columns=["point_x", "point_y", "date_", "time", "objectid"])
        # The extractor explicitly requests that CARTO omit this source-only field.
        .drop(columns=["cartodb_id"], errors="ignore")
        .sort_values("date", ascending=False)
        .reset_index(drop=True)
        .assign(date=lambda df: df.date.dt.strftime(DATE_FORMAT))
    )

    # Add a parsed block number column
    # We use the parsed block numbers to de-duplicate street matches later
    df["parsed_block_num"] = df.location.apply(_parse_location_block_num)

    # Add the other category for race/ethnicity
    main_race_categories = ["H", "W", "B", "A"]
    sel = df.race.isin(main_race_categories)
    df.loc[~sel, "race"] = "Other/Unknown"

    # Remove dates in the future
    future_dates = pd.to_datetime(df.date) > pd.Timestamp.now()
    if future_dates.sum() > 0:
        logger.warning(f"Found {future_dates.sum()} future date(s) in the data")
        df = df.loc[~future_dates].reset_index(drop=True)

    # This is an intrinsic output invariant, so --ignore-checks cannot bypass it.
    _require_plausible_outcomes(df)

    # CHECKS
    if not ignore_checks:
        _run_checks(df, s3=s3)

    # Join with boundary datasets
    df = join_with_boundary_datasets(df)

    # Handle NaN/None geometries by filling with empty Points
    df = df.assign(
        # GeoSeries.fillna accepts Shapely geometries; pandas-stubs models only scalars.
        geometry=lambda df: df.geometry.fillna(Point()),  # ty: ignore[invalid-argument-type]
    )

    # Join with the street blocks
    df = join_with_street_blocks(df, block_column="parsed_block_num").drop(
        columns=["parsed_block_num"]
    )

    # Join with courts data
    logger.info("Joining with courts flags dataset")
    courts_df = sanitize_court_search_flags(load_courts_flags(s3=s3))
    df = df.merge(courts_df, on="dc_key", how="left")

    # Validate against the schema
    df = _validate_against_schema(df)

    return df
