/**
 * Source configuration for map data layers.
 *
 * This module defines how to load GeoJSON data from the API for use in map layers.
 * Sources in the Vue2 version used ArcGIS Online servers; these have been migrated
 * to use our internal API endpoints.
 */

import { fetchBoundaryDatasets } from "@/shared/api/boundaries";

/**
 * Boundary source configuration.
 * Defines the MapLibre source ID for a given API dataset.
 */
interface BoundarySource {
  /** Source ID used in MapLibre layers */
  sourceId: string;
  /** Dataset name for API endpoint (/boundaries/{dataset}) */
  dataset: string;
}

/**
 * Convert an API dataset name to a MapLibre source ID.
 *
 * Uses the convention: boundary-<dataset>
 *
 * @param dataset - API dataset name (e.g., 'police-districts')
 * @returns MapLibre source ID (e.g., 'boundary-police-districts')
 *
 * @example
 * ```typescript
 * datasetToSourceId('police-districts'); // 'boundary-police-districts'
 * datasetToSourceId('zip-codes'); // 'boundary-zip-codes'
 * ```
 */
export function datasetToSourceId(dataset: string): string {
  return `boundary-${dataset}`;
}

/**
 * Extract dataset name from a MapLibre source ID.
 *
 * @param sourceId - MapLibre source ID
 * @returns Dataset name, or null if not a boundary source
 *
 * @example
 * ```typescript
 * sourceIdToDataset('boundary-police-districts'); // 'police-districts'
 * sourceIdToDataset('shootings'); // null
 * ```
 */
export function sourceIdToDataset(sourceId: string): string | null {
  if (!sourceId.startsWith("boundary-")) {
    return null;
  }
  return sourceId.substring("boundary-".length);
}

/**
 * Non-boundary source IDs.
 *
 * These are the source IDs for shootings and streets data.
 * Boundary sources use the predictable pattern: boundary-<dataset>
 */
export const SOURCES = {
  SHOOTINGS: "shootings",
  STREETS: "street-blocks",
} as const;

/**
 * Cached boundary sources fetched from the API.
 */
let cachedBoundarySources: BoundarySource[] | null = null;

/**
 * Fetch all boundary sources from the API.
 *
 * Queries the /boundaries endpoint for available datasets and converts them
 * to source IDs using the boundary-<dataset> convention.
 * Results are cached after first fetch.
 *
 * @param forceRefresh - Force refetch even if cached
 * @returns Array of boundary source configurations
 *
 * @example
 * ```typescript
 * const sources = await fetchBoundarySources();
 * // [
 * //   { sourceId: 'boundary-police-districts', dataset: 'police-districts' },
 * //   { sourceId: 'boundary-council-districts', dataset: 'council-districts' },
 * //   ...
 * // ]
 * ```
 */
export async function fetchBoundarySources(
  forceRefresh = false
): Promise<BoundarySource[]> {
  if (cachedBoundarySources && !forceRefresh) {
    return cachedBoundarySources;
  }

  const response = await fetchBoundaryDatasets();
  cachedBoundarySources = response.datasets.map((dataset) => ({
    dataset,
    sourceId: datasetToSourceId(dataset),
  }));

  return cachedBoundarySources;
}

/**
 * Get all boundary source IDs that need to be loaded from the API.
 *
 * @returns Promise resolving to array of source IDs for boundary datasets
 *
 * @example
 * ```typescript
 * const boundarySources = await getBoundarySources();
 * // ['boundary-police-districts', 'boundary-council-districts', ...]
 * ```
 */
export async function getBoundarySources(): Promise<string[]> {
  const sources = await fetchBoundarySources();
  return sources.map((s) => s.sourceId);
}

/**
 * Check if a source ID is a boundary dataset.
 *
 * @param sourceId - Source ID to check
 * @returns True if the source is a boundary dataset
 *
 * @example
 * ```typescript
 * isBoundarySource('boundary-police-districts'); // true
 * isBoundarySource('shootings'); // false
 * ```
 */
export function isBoundarySource(sourceId: string): boolean {
  return sourceId.startsWith("boundary-");
}

/**
 * Get the API dataset name for a source ID.
 *
 * @param sourceId - Source ID from layer config
 * @returns Dataset name for API endpoint, or null if not a boundary source
 *
 * @example
 * ```typescript
 * const dataset = getDatasetForSource('boundary-police-districts');
 * // 'police-districts'
 * const data = await fetchBoundaries(dataset);
 * ```
 */
export function getDatasetForSource(sourceId: string): string | null {
  return sourceIdToDataset(sourceId);
}
