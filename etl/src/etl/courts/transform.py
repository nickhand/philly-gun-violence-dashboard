"""Transform helpers for portal scraping results."""

import pandas as pd
from loguru import logger

from etl.courts.scraper.schema import PortalResult

__all__ = ["results_to_flags"]


def results_to_flags(
    portal_results: dict[str, list[PortalResult] | None],
    input_df: pd.DataFrame,
) -> pd.DataFrame:
    """Convert portal results + input echo to a flag table with has_court_case.

    Parameters
    ----------
    portal_results : dict[str, list[PortalResult] | None]
        Dictionary mapping incident numbers to lists of portal scraping results (or None).
    input_df : pd.DataFrame
        Original input DataFrame with a 'dc_key' column.

    Returns
    -------
    pd.DataFrame
        Input DataFrame merged with a 'has_court_case' boolean column.
    """
    # Get the DC numbers with court cases
    dc_numbers_with_cases = (
        pd.DataFrame(
            [k for k, v in portal_results.items() if v is not None and len(v) > 0],
            columns=["dc_key"],
        )
        .drop_duplicates()
        .assign(has_court_case=True)
    )

    # Merge back to input
    output = input_df.merge(dc_numbers_with_cases, on="dc_key", how="left")

    # Fill missing court case flags with False
    missing_flags = output["has_court_case"].isnull()
    output.loc[missing_flags, "has_court_case"] = False

    # Log summary and return
    logger.info(f"Flagged {output.has_court_case.sum()} incident numbers with court cases")
    return output
