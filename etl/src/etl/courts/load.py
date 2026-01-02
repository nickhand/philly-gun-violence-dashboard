"""Load/save helpers for courts portal scraping results."""

import json

import pandas as pd
from mypy_boto3_s3.client import S3Client

from dashboard_utils.aws import upload_file
from dashboard_utils.env import settings
from dashboard_utils.paths import data_dir, get_processed_path
from etl.courts.portal.schema import PortalResult

__all__ = ["read_existing_flags", "write_flags"]


def read_existing_flags() -> pd.DataFrame:
    """Read existing dc_key/has_court_case flags if present."""
    data_path = get_processed_path("courts_flags")
    if not data_path.exists():
        return pd.DataFrame(columns=["dc_key", "has_court_case"])
    return pd.read_csv(data_path, dtype={"dc_key": str})


def write_flags(s3: S3Client, df: pd.DataFrame) -> None:
    """Persist flags to CSV."""
    # Write locally
    path = get_processed_path("courts_flags")
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)

    # Key in s3 is relative to data_dir
    key = str(path.relative_to(data_dir()))

    # Mirror to s3
    upload_file(
        s3,
        path,
        bucket=settings.AWS_BUCKET_NAME,
        key=key,
        content_type="text/csv",
    )


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
    path = get_processed_path("portal_results")
    path.parent.mkdir(parents=True, exist_ok=True)

    # Save to a JSON file locally
    result_dicts = {
        k: [r.model_dump() for r in v] if v is not None else None for k, v in portal_results.items()
    }
    json.dump(result_dicts, path.open("w"))

    # Key in s3 is relative to data_dir
    key = str(path.relative_to(data_dir()))

    # Mirror to s3
    upload_file(
        s3,
        path,
        bucket=settings.AWS_BUCKET_NAME,
        key=key,
        content_type="text/csv",
    )
