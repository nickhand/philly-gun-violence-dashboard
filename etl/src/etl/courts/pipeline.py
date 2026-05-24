"""Post-scrape pipeline: aggregate results and write courts flags CSV."""

import pandas as pd
from loguru import logger
from mypy_boto3_s3.client import S3Client

from etl.courts.batch.aggregate import aggregate_results
from etl.courts.config import WorkerConfig
from etl.courts.load import read_existing_flags, write_flags, write_portal_results
from etl.courts.transform import results_to_flags
from etl.utils.storage import load_shootings_database, write_meta


def process_results(s3: S3Client, config: WorkerConfig) -> None:
    """Aggregate S3 results and write courts flags CSV."""
    logger.info("Step 1/4: fetching per-incident results from S3...")
    portal_results = aggregate_results(s3, config)

    logger.info("Step 2/4: transforming results to flags...")
    gdf = load_shootings_database(s3=s3)
    input_df = pd.DataFrame({"dc_key": gdf["dc_key"].astype(str).unique()})
    flags = results_to_flags(portal_results, input_df)

    logger.info("Step 3/4: writing portal_results.json...")
    write_portal_results(s3, portal_results)

    logger.info("Step 4/4: writing courts flags CSV...")
    existing = read_existing_flags()
    if not existing.empty:
        out = pd.concat([existing, flags]).drop_duplicates(subset=["dc_key"], keep="last")
    else:
        out = flags
    out = out.sort_values("dc_key").reset_index(drop=True)

    write_flags(s3, out)
    write_meta(subfolder="courts")
    logger.info(f"Done. {len(out)} incidents written.")


