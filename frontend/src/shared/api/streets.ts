import { apiFetch } from "./client";
import { fetchAllPages } from "@/shared/utils/pagination";
import type { PageMeta } from "@/shared/types/pagination";

/**
 * GeoJSON Feature for street block data.
 */
interface StreetFeature {
  type: "Feature";
  geometry: GeoJSON.Geometry;
  properties: {
    segment_id: string;
    street_name: string;
    block_number: string;
    [key: string]: any;
  };
}

/**
 * Paginated response from the /streets endpoint.
 */
interface StreetsResponse extends PageMeta {
  type: "FeatureCollection";
  features: StreetFeature[];
}

/**
 * Parameters for fetching street data.
 */
interface FetchStreetsParams {
  /** Array of segment IDs to filter by */
  segment_id?: string[];
  /** Maximum number of features to return (default: 2000) */
  limit?: number;
  /** Zero-based offset for pagination (default: 0) */
  offset?: number;
}

/**
 * Fetches a single page of street block GeoJSON data from the API.
 *
 * The API returns paginated results. Use the `next_offset` field in the response
 * to fetch subsequent pages, or use `fetchStreetsAllPages` to fetch all data automatically.
 *
 * @param params - Query parameters for filtering and pagination
 * @returns Promise resolving to paginated street FeatureCollection
 * @throws Error if request fails
 *
 * @example
 * ```typescript
 * // Fetch first page of all streets
 * const page1 = await fetchStreetsPage({ limit: 2000, offset: 0 });
 *
 * // Fetch specific segments
 * const filtered = await fetchStreetsPage({
 *   segment_id: ['123', '456'],
 *   limit: 100,
 * });
 * ```
 */
export async function fetchStreetsPage(
  params: FetchStreetsParams = {}
): Promise<StreetsResponse> {
  const queryParams = new URLSearchParams();

  if (params.segment_id) {
    params.segment_id.forEach((id) => queryParams.append("segment_id", id));
  }
  queryParams.append("limit", String(params.limit ?? 2000));
  queryParams.append("offset", String(params.offset ?? 0));

  const queryString = queryParams.toString();
  return await apiFetch<StreetsResponse>(`/streets?${queryString}`);
}

/**
 * Fetches all street block data by exhausting paginated API endpoints.
 *
 * This function automatically handles pagination by making multiple requests
 * until all data is retrieved. Use with caution for large datasets.
 *
 * @param params - Query parameters for filtering
 * @param params.segment_id - Optional array of segment IDs to filter by
 * @param params.pageSize - Number of features to fetch per request (default: 2000)
 * @returns Promise resolving to complete GeoJSON FeatureCollection with all street features
 * @throws Error if any API request fails
 *
 * @example
 * ```typescript
 * // Fetch all streets
 * const allStreets = await fetchStreetsAllPages();
 * console.log(`Total street segments: ${allStreets.features.length}`);
 *
 * // Fetch specific segments only
 * const filtered = await fetchStreetsAllPages({
 *   segment_id: ['123', '456', '789']
 * });
 *
 * // Fetch with custom page size
 * const allStreets = await fetchStreetsAllPages({ pageSize: 5000 });
 * ```
 */
export async function fetchStreetsAllPages(
  params: {
    segment_id?: string[];
    pageSize?: number;
  } = {}
): Promise<{ type: "FeatureCollection"; features: StreetFeature[] }> {
  return fetchAllPages(
    (paginationParams) =>
      fetchStreetsPage({
        segment_id: params.segment_id,
        ...paginationParams,
      }),
    {},
    params.pageSize
  );
}
