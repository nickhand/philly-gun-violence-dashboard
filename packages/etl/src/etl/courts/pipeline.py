"""Post-scrape pipeline: aggregate results and write courts flags CSV."""

import pandas as pd
from aws_batch_scraper.aggregate import (
    aggregate_failures,
    aggregate_results,
    read_run_items,
    read_run_manifest,
    require_no_result_conflicts,
)
from aws_batch_scraper.types import ScrapeResult, ScrapeStatus
from loguru import logger
from mypy_boto3_s3.client import S3Client

from dashboard_utils.processed import read_processed_csv, write_processed_csv, write_processed_json
from etl.courts.config import CourtsWorkerConfig as WorkerConfig
from etl.courts.publication import (
    COURTS_PUBLICATION_CONTRACT_VERSION,
    court_flags_sha256,
)
from etl.courts.semantics import (
    COURT_SEARCH_SEMANTICS_VERSION,
    COURT_SEARCH_SEMANTICS_VERSION_COLUMN,
    sanitize_court_search_flags,
)
from etl.utils.storage import write_meta


def _results_to_flags(
    portal_results: dict[str, ScrapeResult],
    input_df: pd.DataFrame,
) -> pd.DataFrame:
    """Map conclusive portal outcomes to nullable flags.

    Failed, invalid, missing, and malformed-success outcomes remain ``<NA>``.
    They are observations of unknown state, not evidence that no case exists.
    """
    observed: dict[str, bool] = {}
    for key, result in portal_results.items():
        results = result.data.get("results") if result.data is not None else None
        if result.status == ScrapeStatus.SUCCESS and isinstance(results, list) and results:
            observed[str(key)] = True
        elif result.status == ScrapeStatus.NO_RESULTS and not results:
            observed[str(key)] = False

    output = input_df.copy()
    output["dc_key"] = output["dc_key"].astype(str)
    output["has_court_case"] = output["dc_key"].map(observed).astype("boolean")
    true_count = int(output["has_court_case"].fillna(False).sum())
    unknown_count = int(output["has_court_case"].isna().sum())
    logger.info(
        f"Flagged {true_count} incident numbers with court cases; "
        f"{unknown_count} outcome(s) remain unknown"
    )
    return output


def _merge_flags(existing: pd.DataFrame, current: pd.DataFrame) -> pd.DataFrame:
    """Overlay conclusive observations without trusting legacy false values.

    Before semantics version 2, the pipeline filled missing and failed searches
    with ``False``. Only a versioned row can therefore prove that an existing
    false came from an explicit no-results marker. Historical true values remain
    useful evidence and are preserved when the current run is inconclusive.
    """
    current_by_id = current.drop_duplicates("dc_key", keep="last").set_index("dc_key")[
        "has_court_case"
    ]
    current_by_id = current_by_id.astype("boolean")

    if existing.empty:
        merged = current_by_id
    else:
        previous_by_id = sanitize_court_search_flags(existing).set_index("dc_key")["has_court_case"]
        all_ids = previous_by_id.index.union(current_by_id.index, sort=False)
        merged = current_by_id.reindex(all_ids).combine_first(previous_by_id.reindex(all_ids))

    output = (
        merged.astype("boolean")
        .rename("has_court_case")
        .rename_axis("dc_key")
        .reset_index()
        .sort_values("dc_key")
        .reset_index(drop=True)
    )
    output[COURT_SEARCH_SEMANTICS_VERSION_COLUMN] = COURT_SEARCH_SEMANTICS_VERSION
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
    """Validate one owned run and publish stable flags only for a full run."""
    run_id = config.run_id.strip()
    if not run_id or run_id == "unknown":
        raise ValueError("Courts result processing requires a concrete run ID")

    logger.info(f"Step 1/4: fetching exact-run inputs and results for {run_id}...")
    manifest = read_run_manifest(s3, config, run_id, require_completed=True)
    run_items = read_run_items(s3, config, run_id, require_completed=True)
    require_no_result_conflicts(s3, config, run_id)
    conclusive_results = aggregate_results(s3, config, run_id=run_id)
    failed_results = aggregate_failures(s3, config, run_id)
    # Capture the report after aggregation as well as checking before it.  This
    # keeps published metadata bound to the final conflict inventory while any
    # newly visible unresolved evidence still fails closed before stable writes.
    conflict_report = require_no_result_conflicts(s3, config, run_id)
    unexpected_failure_statuses = {
        item_id: result.status.value
        for item_id, result in failed_results.items()
        if result.status not in {ScrapeStatus.FAILED, ScrapeStatus.INVALID_INPUT}
    }
    if unexpected_failure_statuses:
        raise ValueError(
            f"Run {run_id} has non-failure records under its failures prefix: "
            f"{unexpected_failure_statuses}"
        )
    overlapping_ids = conclusive_results.keys() & failed_results.keys()
    if overlapping_ids:
        raise ValueError(
            f"Run {run_id} has both result and failure records for: {sorted(overlapping_ids)}"
        )
    portal_results = {**failed_results, **conclusive_results}
    status_counts = {
        status.value: sum(1 for result in portal_results.values() if result.status == status)
        for status in ScrapeStatus
    }

    logger.info("Step 2/4: transforming results to flags...")
    input_df = pd.DataFrame({"dc_key": [item.item_id for item in run_items]})
    flags = _results_to_flags(portal_results, input_df)
    unknown_result_count = int(flags["has_court_case"].isna().sum())
    missing_result_count, extra_result_count = _result_coverage(portal_results, input_df)
    if extra_result_count:
        input_ids = set(input_df["dc_key"].astype(str))
        extra_ids = sorted(set(portal_results).difference(input_ids))
        raise ValueError(
            f"Run {run_id} has result records outside its immutable input set: {extra_ids}"
        )
    has_failures = status_counts[ScrapeStatus.FAILED.value] > 0
    has_invalid_inputs = status_counts[ScrapeStatus.INVALID_INPUT.value] > 0
    has_partial_results = unknown_result_count > 0 or has_failures or has_invalid_inputs
    if has_partial_results:
        logger.warning(
            "Courts results are partial: unknown_result_count={}, "
            "missing_result_count={}, failure_count={}, invalid_input_count={}",
            unknown_result_count,
            missing_result_count,
            status_counts[ScrapeStatus.FAILED.value],
            status_counts[ScrapeStatus.INVALID_INPUT.value],
        )

    if manifest.selection_mode != "full":
        logger.info(
            "Validated {} courts run {}; skipping all stable processed outputs "
            "because only a full run may publish",
            manifest.selection_mode,
            run_id,
        )
        return

    coverage_complete = (
        manifest.input_size == manifest.candidate_count
        and len(input_df) == manifest.input_size
        and len(portal_results) == len(input_df)
        and missing_result_count == 0
        and extra_result_count == 0
    )
    if not coverage_complete:
        raise ValueError(
            f"Full courts run {run_id} does not have complete terminal result coverage; "
            "refusing to replace the stable court-flags generation"
        )

    logger.info("Step 3/4: writing portal_results.json...")
    _write_portal_results(s3, portal_results)

    logger.info("Step 4/4: writing courts flags CSV...")
    existing = _read_existing_flags(s3)
    out = _merge_flags(existing, flags)

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
        unknown_result_count=unknown_result_count,
        has_partial_results=has_partial_results,
        publication_contract_version=COURTS_PUBLICATION_CONTRACT_VERSION,
        selection_mode=manifest.selection_mode,
        candidate_count=manifest.candidate_count,
        coverage_complete=coverage_complete,
        flags_row_count=len(out),
        flags_sha256=court_flags_sha256(out),
        court_search_semantics_version=COURT_SEARCH_SEMANTICS_VERSION,
        result_conflict_policy_version=conflict_report.conflict_policy_version,
        result_conflict_count=conflict_report.total_count,
        resolved_result_conflict_count=conflict_report.resolved_count,
        unresolved_result_conflict_count=conflict_report.unresolved_count,
        invalid_result_conflict_resolution_count=(conflict_report.invalid_resolution_count),
        result_conflict_evidence_sha256=conflict_report.evidence_sha256,
        run_id=config.run_id if config.run_id != "unknown" else None,
    )
    logger.info(f"Done. {len(out)} incidents written.")
