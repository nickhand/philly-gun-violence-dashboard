import { apiFetch } from "./client";

/**
 * Response from the /boundaries endpoint listing available datasets.
 */
interface BoundaryDatasetsResponse {
  datasets: string[];
}

/**
 * GeoJSON Feature for boundary data.
 */
interface BoundaryFeature {
  type: "Feature";
  geometry: GeoJSON.Geometry;
  properties: Record<string, any>;
}

/**
 * GeoJSON FeatureCollection for boundary data.
 */
interface BoundaryFeatureCollection {
  type: "FeatureCollection";
  features: BoundaryFeature[];
}

/**
 * Fetches the list of available boundary datasets from the API.
 *
 * @returns Promise resolving to list of dataset names
 * @throws Error if request fails
 *
 * @example
 * ```typescript
 * const datasets = await fetchBoundaryDatasets();
 * console.log(datasets.datasets); // ['police-districts', 'council-districts', ...]
 * ```
 */
export async function fetchBoundaryDatasets(): Promise<BoundaryDatasetsResponse> {
  return await apiFetch<BoundaryDatasetsResponse>("/boundaries");
}

/**
 * Fetches boundary GeoJSON data for a specific dataset.
 *
 * Available datasets include:
 * - police-districts
 * - council-districts
 * - zip-codes
 * - neighborhoods
 * - house-districts (PA House)
 * - senate-districts (PA Senate)
 * - elementary-schools
 *
 * @param dataset - Name of the boundary dataset to fetch
 * @returns Promise resolving to GeoJSON FeatureCollection
 * @throws Error if dataset not found or request fails
 *
 * @example
 * ```typescript
 * const policeDistricts = await fetchBoundaries('police-districts');
 * console.log(policeDistricts.features.length);
 * ```
 */
export async function fetchBoundaries(
  dataset: string
): Promise<BoundaryFeatureCollection> {
  return await apiFetch<BoundaryFeatureCollection>(`/boundaries/${dataset}`);
}
