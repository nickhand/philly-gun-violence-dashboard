import { describe, expect, it } from "vitest";

import type { CourtDatasetMeta } from "../../../app/types/datasetMeta";
import { getCompleteCourtCoverage } from "../../../app/utils/courtCoverage";

const validCoverage = {
  candidate_count: 15_753,
  court_search_semantics_version: 2,
  coverage_complete: true,
  data_through: "2026-08-20",
  extra_result_count: 0,
  failure_count: 0,
  flags_row_count: 15_753,
  flags_sha256: "a".repeat(64),
  has_partial_results: false,
  input_count: 15_753,
  invalid_result_conflict_resolution_count: 0,
  invalid_input_count: 0,
  last_updated: "2026-08-20T14:30:00Z",
  missing_result_count: 0,
  publication_contract_version: 2,
  resolved_result_conflict_count: 0,
  result_conflict_count: 0,
  result_conflict_evidence_sha256: "b".repeat(64),
  result_conflict_policy_version: 1,
  result_count: 15_753,
  run_id: "2026-08-20T140430Z-0116",
  selection_mode: "full",
  status: "success",
  unresolved_result_conflict_count: 0,
  unknown_result_count: 0,
} satisfies CourtDatasetMeta;

describe("complete court-publication coverage", () => {
  it("accepts a complete full-run publication contract", () => {
    expect(getCompleteCourtCoverage(validCoverage)).toEqual({
      candidateCount: 15_753,
      failureCount: 0,
      flagsRowCount: 15_753,
      flagsSha256: "a".repeat(64),
      invalidInputCount: 0,
      processedAt: "2026-08-20T14:30:00Z",
      unknownResultCount: 0,
    });
  });

  it("retains truthful inconclusive counts for a terminally complete partial run", () => {
    expect(
      getCompleteCourtCoverage({
        ...validCoverage,
        failure_count: 1,
        has_partial_results: true,
        status: "partial",
        unknown_result_count: 1,
      }),
    ).toMatchObject({
      candidateCount: 15_753,
      failureCount: 1,
      unknownResultCount: 1,
    });
  });

  it("accepts a full run with explicitly resolved conflict evidence", () => {
    expect(
      getCompleteCourtCoverage({
        ...validCoverage,
        resolved_result_conflict_count: 1,
        result_conflict_count: 1,
      }),
    ).toMatchObject({ candidateCount: 15_753, unknownResultCount: 0 });
  });

  it.each([
    ["sample selection", { selection_mode: "sample" }],
    ["incremental selection", { selection_mode: "incremental" }],
    ["missing provenance", { selection_mode: undefined }],
    ["missing run id", { run_id: undefined }],
    ["blank run id", { run_id: "  " }],
    ["incomplete coverage", { coverage_complete: false }],
    ["partial input", { input_count: 15_752 }],
    ["partial result coverage", { result_count: 15_752 }],
    ["missing terminal result", { missing_result_count: 1 }],
    ["extra terminal result", { extra_result_count: 1 }],
    ["incomplete flags generation", { flags_row_count: 15_752 }],
    ["legacy contract", { publication_contract_version: 1 }],
    ["unknown semantics", { court_search_semantics_version: 1 }],
    ["unknown conflict policy", { result_conflict_policy_version: 2 }],
    ["missing conflict total", { result_conflict_count: undefined }],
    ["non-integer conflict total", { result_conflict_count: 0.5 }],
    ["inconsistent conflict counts", { result_conflict_count: 1 }],
    [
      "unresolved conflict",
      { result_conflict_count: 1, unresolved_result_conflict_count: 1 },
    ],
    [
      "invalid conflict resolution",
      { invalid_result_conflict_resolution_count: 1 },
    ],
    [
      "malformed conflict digest",
      { result_conflict_evidence_sha256: "B".repeat(64) },
    ],
    ["inconsistent partial status", { has_partial_results: true }],
    ["malformed digest", { flags_sha256: "not-a-digest" }],
    ["malformed timestamp", { last_updated: "not-a-date" }],
  ] satisfies [string, Partial<CourtDatasetMeta>][])(
    "rejects %s",
    (_label, mutation) => {
    expect(
      getCompleteCourtCoverage({ ...validCoverage, ...mutation }),
    ).toBeNull();
    },
  );
});
