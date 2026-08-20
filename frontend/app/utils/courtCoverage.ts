import type { CourtDatasetMeta } from "../types/datasetMeta";

export interface CompleteCourtCoverage {
  candidateCount: number;
  failureCount: number;
  flagsRowCount: number;
  flagsSha256: string;
  invalidInputCount: number;
  processedAt: string;
  unknownResultCount: number;
}

const SHA256_PATTERN = /^[0-9a-f]{64}$/;

type CourtCountField =
  | "candidate_count"
  | "extra_result_count"
  | "failure_count"
  | "flags_row_count"
  | "input_count"
  | "invalid_input_count"
  | "missing_result_count"
  | "result_count"
  | "unknown_result_count";

type CourtMetaWithCounts = CourtDatasetMeta &
  Required<Pick<CourtDatasetMeta, CourtCountField>>;

function isNonnegativeSafeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function hasValidCourtCounts(
  value: CourtDatasetMeta | null | undefined,
): value is CourtMetaWithCounts {
  return Boolean(
    value &&
      isNonnegativeSafeInteger(value.candidate_count) &&
      value.candidate_count > 0 &&
      isNonnegativeSafeInteger(value.input_count) &&
      isNonnegativeSafeInteger(value.result_count) &&
      isNonnegativeSafeInteger(value.missing_result_count) &&
      isNonnegativeSafeInteger(value.extra_result_count) &&
      isNonnegativeSafeInteger(value.failure_count) &&
      isNonnegativeSafeInteger(value.invalid_input_count) &&
      isNonnegativeSafeInteger(value.unknown_result_count) &&
      isNonnegativeSafeInteger(value.flags_row_count),
  );
}

/**
 * Return only publication metadata that proves one complete, full run.
 * Older sample/incremental metadata deliberately produces no global coverage
 * claim, even if that smaller run succeeded for every selected record.
 */
export function getCompleteCourtCoverage(
  value: CourtDatasetMeta | null | undefined,
): CompleteCourtCoverage | null {
  if (
    !hasValidCourtCounts(value) ||
    value.selection_mode !== "full" ||
    value.coverage_complete !== true ||
    value.publication_contract_version !== 1 ||
    value.court_search_semantics_version !== 2 ||
    value.input_count !== value.candidate_count ||
    value.result_count !== value.input_count ||
    value.missing_result_count !== 0 ||
    value.extra_result_count !== 0 ||
    value.flags_row_count < value.candidate_count ||
    value.unknown_result_count > value.input_count ||
    value.failure_count + value.invalid_input_count >
      value.unknown_result_count ||
    value.has_partial_results !== (value.unknown_result_count > 0) ||
    value.status !== (value.has_partial_results ? "partial" : "success") ||
    typeof value.flags_sha256 !== "string" ||
    !SHA256_PATTERN.test(value.flags_sha256) ||
    typeof value.last_updated !== "string" ||
    !Number.isFinite(Date.parse(value.last_updated))
  ) {
    return null;
  }

  return {
    candidateCount: value.candidate_count,
    failureCount: value.failure_count,
    flagsRowCount: value.flags_row_count,
    flagsSha256: value.flags_sha256,
    invalidInputCount: value.invalid_input_count,
    processedAt: value.last_updated,
    unknownResultCount: value.unknown_result_count,
  };
}
