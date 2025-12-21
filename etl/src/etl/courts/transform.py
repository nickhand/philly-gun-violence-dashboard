"""
Transform helpers for portal scraping results.
"""

import pandas as pd
from loguru import logger

__all__ = ["results_to_flags"]


def results_to_flags(portal_results: list[dict], input_df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert portal results + input echo to a flag table with has_court_case.
    """
    dc_numbers_with_cases = (
        pd.DataFrame(
            {"dc_key": ["20" + rr["dc_number"] for r in portal_results for rr in r]},
            dtype=str,
        )
        .drop_duplicates()
        .assign(has_court_case=True)
    )
    output = input_df.merge(dc_numbers_with_cases, on="dc_key", how="left").assign(
        has_court_case=lambda df: df.has_court_case.fillna(False)
    )
    logger.info("Flagged %d incident numbers with court cases", output.has_court_case.sum())
    return output
