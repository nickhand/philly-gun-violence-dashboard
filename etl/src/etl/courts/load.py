"""Load/save helpers for courts portal scraping results."""

import pandas as pd
from mypy_boto3_s3.client import S3Client

from dashboard_utils.aws import make_s3_client, read_csv_df, write_csv_df, write_json
from dashboard_utils.env import settings
from dashboard_utils.paths import get_processed_key
from etl.courts.portal.schema import PortalResult

__all__ = ["read_existing_flags", "write_flags"]


def read_existing_flags() -> pd.DataFrame:
    """Read existing dc_key/has_court_case flags if present."""
    s3 = make_s3_client()
    key = get_processed_key("courts_flags")
    try:
        return read_csv_df(s3, bucket=settings.AWS_BUCKET_NAME, key=key, dtype={"dc_key": str})
    except FileNotFoundError:
        return pd.DataFrame(columns=["dc_key", "has_court_case"])


def write_flags(s3: S3Client, df: pd.DataFrame) -> None:
    """Persist flags to CSV."""
    key = get_processed_key("courts_flags")
    write_csv_df(s3, settings.AWS_BUCKET_NAME, key, df)


def write_portal_results(
    s3: S3Client,
    portal_results: dict[str, list[PortalResult] | None],
) -> None:
    """Write portal results to processed data folder.

    Parameters
    ----------
    s3 : S3Client
        The S3 client to use for uploading the portal results.
    portal_results : dict[str, list[PortalResult] | None]
        Dictionary mapping incident numbers to lists of portal result objects (or None).
    """
    result_dicts = {
        k: [r.model_dump() for r in v] if v is not None else None for k, v in portal_results.items()
    }
    key = get_processed_key("portal_results")
    write_json(s3, settings.AWS_BUCKET_NAME, key, result_dicts)
