"""Transform helpers for portal scraping results."""

import pandas as pd
from loguru import logger

from etl.courts.portal.schema import PortalResult

__all__ = ["results_to_flags"]


def results_to_flags(portal_results: list[PortalResult], input_df: pd.DataFrame) -> pd.DataFrame:
    """Convert portal results + input echo to a flag table with has_court_case.

    Parameters
    ----------
    portal_results : list[PortalResult]
        List of portal scraping results.
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
            {"dc_key": ["20" + r.dc_number for r in portal_results]},
            dtype=str,
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
