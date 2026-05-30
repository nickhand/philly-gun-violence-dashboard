"""Post-scrape pipeline: aggregate results and write courts flags CSV."""

import pandas as pd
from aws_batch_scraper.aggregate import aggregate_results
from aws_batch_scraper.types import ScrapeResult, ScrapeStatus
from loguru import logger
from mypy_boto3_s3.client import S3Client

from dashboard_utils.processed import read_processed_csv, write_processed_csv, write_processed_json
from etl.courts.config import CourtsWorkerConfig as WorkerConfig
from etl.utils.storage import load_shootings_database, write_meta


def _results_to_flags(
    portal_results: dict[str, ScrapeResult],
    input_df: pd.DataFrame,
) -> pd.DataFrame:
    dc_numbers_with_cases = (
        pd.DataFrame(
            [
                key
                for key, result in portal_results.items()
                if result.status == ScrapeStatus.SUCCESS
                and result.data is not None
                and result.data.get("results")
            ],
            columns=["dc_key"],
        )
        .drop_duplicates()
        .assign(has_court_case=True)
    )
    output = input_df.merge(dc_numbers_with_cases, on="dc_key", how="left")
    output["has_court_case"] = output["has_court_case"].fillna(False)
    logger.info(f"Flagged {output.has_court_case.sum()} incident numbers with court cases")
    return output


def _read_existing_flags(s3: S3Client) -> pd.DataFrame:
    try:
        return read_processed_csv("courts_flags", s3=s3, dtype={"dc_key": str})
    except FileNotFoundError:
        return pd.DataFrame(columns=["dc_key", "has_court_case"])


def _write_portal_results(s3: S3Client, portal_results: dict[str, ScrapeResult]) -> None:
    write_processed_json(
        "portal_results",
        {key: result.model_dump(mode="json") for key, result in portal_results.items()},
        s3=s3,
    )


def _result_coverage(
    portal_results: dict[str, ScrapeResult],
    input_df: pd.DataFrame,
) -> tuple[int, int]:
    input_ids = set(input_df["dc_key"].astype(str))
    result_ids = set(portal_results)
    return len(input_ids - result_ids), len(result_ids - input_ids)


def process_results(s3: S3Client, config: WorkerConfig) -> None:
    """Aggregate S3 results and write courts flags CSV."""
    logger.info("Step 1/4: fetching per-incident results from S3...")
    portal_results = aggregate_results(s3, config)
    status_counts = {
        status.value: sum(1 for result in portal_results.values() if result.status == status)
        for status in ScrapeStatus
    }

    logger.info("Step 2/4: transforming results to flags...")
    gdf = load_shootings_database(s3=s3)
    input_df = pd.DataFrame({"dc_key": gdf["dc_key"].astype(str).unique()})
    flags = _results_to_flags(portal_results, input_df)
    missing_result_count, extra_result_count = _result_coverage(portal_results, input_df)
    has_failures = status_counts[ScrapeStatus.FAILED.value] > 0
    has_partial_results = missing_result_count > 0 or has_failures
    if has_partial_results:
        logger.warning(
            "Courts results are partial: missing_result_count={}, failure_count={}",
            missing_result_count,
            status_counts[ScrapeStatus.FAILED.value],
        )

    logger.info("Step 3/4: writing portal_results.json...")
    _write_portal_results(s3, portal_results)

    logger.info("Step 4/4: writing courts flags CSV...")
    existing = _read_existing_flags(s3)
    if not existing.empty:
        out = pd.concat([existing, flags]).drop_duplicates(subset=["dc_key"], keep="last")
    else:
        out = flags
    out = out.sort_values("dc_key").reset_index(drop=True)

    write_processed_csv("courts_flags", out, s3=s3)
    write_meta(
        subfolder="courts",
        s3=s3,
        status="partial" if has_partial_results else "success",
        pipeline="courts",
        source="pa_ujs_portal",
        input_count=len(input_df),
        output_count=len(out),
        result_count=len(portal_results),
        success_count=status_counts[ScrapeStatus.SUCCESS.value],
        no_results_count=status_counts[ScrapeStatus.NO_RESULTS.value],
        failure_count=status_counts[ScrapeStatus.FAILED.value],
        invalid_input_count=status_counts[ScrapeStatus.INVALID_INPUT.value],
        missing_result_count=missing_result_count,
        extra_result_count=extra_result_count,
        has_partial_results=has_partial_results,
        run_id=config.run_id if config.run_id != "unknown" else None,
    )
    logger.info(f"Done. {len(out)} incidents written.")
