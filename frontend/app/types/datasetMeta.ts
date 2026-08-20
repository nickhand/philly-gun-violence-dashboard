export interface DatasetMeta {
  data_through: string;
  last_updated: string;
  row_count?: number;
}

export interface CourtDatasetMeta extends DatasetMeta {
  candidate_count?: number;
  court_search_semantics_version?: number;
  coverage_complete?: boolean;
  extra_result_count?: number;
  failure_count?: number;
  flags_row_count?: number;
  flags_sha256?: string;
  has_partial_results?: boolean;
  input_count?: number;
  invalid_input_count?: number;
  missing_result_count?: number;
  publication_contract_version?: number;
  result_count?: number;
  selection_mode?: "full" | "incremental" | "sample";
  status?: "partial" | "success";
  unknown_result_count?: number;
}

export interface AllDatasetsMeta {
  shootings: DatasetMeta;
  homicides: DatasetMeta;
  courts: CourtDatasetMeta;
}
