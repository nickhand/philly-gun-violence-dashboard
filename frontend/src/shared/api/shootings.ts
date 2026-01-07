import type { PageMeta } from "@/shared/types/pagination";
import type { ShootingVictimsGeoJsonApi } from "@/shared/types/shootings";
import { apiFetch } from "@/shared/api/client";
import { fetchAllPages } from "@/shared/utils/pagination";

/** Paginated response for shootings data */
export interface ShootingsPage extends PageMeta {
  type: "FeatureCollection";
  features: ShootingVictimsGeoJsonApi["features"];
}

/** API response for available shooting data years */
export interface ShootingsYearsResponse {
  years: number[];
}

/**
 * Fetches all available years with shooting victim data.
 *
 * @returns Promise resolving to array of years with data
 * @throws Error if the API request fails
 *
 * @example
 * ```ts
 * const years = await fetchShootingsYears();
 * // [2015, 2016, ..., 2024]
 * ```
 */
export async function fetchShootingsYears(): Promise<number[]> {
  const response = await apiFetch<ShootingsYearsResponse>("/shootings/years");
  return response.years;
}

/**
 * Fetches a single page of shooting victims data with optional filters.
 *
 * @param params - Query parameters for filtering and pagination
 * @param params.year - Optional year to filter by (null for all years)
 * @param params.limit - Maximum number of features to return per page
 * @param params.offset - Number of features to skip (for pagination)
 * @returns Promise resolving to a paginated GeoJSON FeatureCollection with metadata
 * @throws Error if the API request fails
 *
 * @example
 * ```ts
 * // Fetch first page for 2024
 * const page = await fetchShootingsPage({ year: 2024, limit: 2000, offset: 0 });
 *
 * // Fetch all years
 * const allYears = await fetchShootingsPage({ year: null, limit: 2000 });
 * ```
 */
export async function fetchShootingsPage(params: {
  year?: number | null;
  limit?: number;
  offset?: number;
}): Promise<ShootingsPage> {
  // Build query parameters
  const search = new URLSearchParams();
  if (params.year !== undefined && params.year !== null) {
    search.set("year", String(params.year));
  }
  if (params.limit !== undefined) {
    search.set("limit", String(params.limit));
  }
  if (params.offset !== undefined) {
    search.set("offset", String(params.offset));
  }

  // Fetch the data from the API
  const suffix = search.toString();
  return apiFetch<ShootingsPage>(`/shootings${suffix ? `?${suffix}` : ""}`);
}

/**
 * Fetches all shooting victims data by exhausting paginated API endpoints.
 *
 * This function automatically handles pagination by making multiple requests
 * until all data is retrieved. Use with caution for large datasets.
 *
 * @param params - Query parameters for filtering
 * @param params.year - Optional year to filter by (null for all years)
 * @param params.pageSize - Number of features to fetch per request (default: 2000)
 * @returns Promise resolving to complete GeoJSON FeatureCollection with all features
 * @throws Error if any API request fails
 *
 * @example
 * ```ts
 * // Fetch all shootings for 2024
 * const data2024 = await fetchShootingsAllPages({ year: 2024 });
 * console.log(`Total features: ${data2024.features.length}`);
 *
 * // Fetch all years with custom page size
 * const allData = await fetchShootingsAllPages({ year: null, pageSize: 5000 });
 * ```
 */
export async function fetchShootingsAllPages(params: {
  year?: number | null;
  pageSize?: number;
}): Promise<ShootingVictimsGeoJsonApi> {
  return fetchAllPages(
    (paginationParams) =>
      fetchShootingsPage({
        year: params.year,
        ...paginationParams,
      }),
    {},
    params.pageSize
  );
}
