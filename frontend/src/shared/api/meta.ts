import { apiFetch } from "./client";

/**
 * Metadata about a dataset's freshness.
 */
export interface DatasetMeta {
  /** ISO timestamp when the ETL pipeline last ran */
  last_updated: string;
  /** Date string (YYYY-MM-DD) indicating the latest data in the dataset */
  data_through: string;
  /** Total number of records in the dataset (present for shootings) */
  row_count?: number;
}

/**
 * Metadata for all datasets.
 */
export interface AllDatasetsMeta {
  shootings: DatasetMeta;
  homicides: DatasetMeta;
  courts: DatasetMeta;
}

/**
 * Fetch metadata for all datasets.
 *
 * @returns Promise resolving to metadata for shootings, homicides, and courts
 */
export async function fetchAllMeta(): Promise<AllDatasetsMeta> {
  return apiFetch<AllDatasetsMeta>("/meta");
}

/**
 * Fetch metadata for the shootings dataset.
 *
 * @returns Promise resolving to shootings metadata
 */
export async function fetchShootingsMeta(): Promise<DatasetMeta> {
  return apiFetch<DatasetMeta>("/meta/shootings");
}
