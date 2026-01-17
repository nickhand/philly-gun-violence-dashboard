import type { PageMeta } from "@/shared/types/pagination";

/**
 * Paginated response with features array.
 * Generic type for any paginated GeoJSON endpoint.
 */
export interface PaginatedFeatureResponse<TFeature> extends PageMeta {
  type: "FeatureCollection";
  features: TFeature[];
}

/**
 * Parameters for pagination control.
 */
export interface PaginationParams {
  /** Maximum number of features to return per page */
  limit?: number;
  /** Zero-based offset for pagination */
  offset?: number;
}

/**
 * Fetches all pages from a paginated API endpoint and combines features into a single collection.
 *
 * This utility handles the pagination loop logic, making multiple requests until all data
 * is retrieved. The pagination is determined by the `next_offset` field in the API response.
 *
 * @template TFeature - Type of the GeoJSON feature in the response
 * @template TParams - Type of the parameters object for the fetch function
 * @param fetchPageFn - Async function that fetches a single page
 * @param params - Parameters to pass to the fetch function
 * @param pageSize - Number of features to fetch per request (default: 2000)
 * @returns Promise resolving to complete GeoJSON FeatureCollection with all features
 * @throws Error if any API request fails
 *
 * @example
 * ```typescript
 * // Fetch all streets with filters
 * const allStreets = await fetchAllPages(
 *   (params) => fetchStreetsPage({ segment_ids: ['123', '456'], ...params }),
 *   {}
 * );
 * ```
 */
export async function fetchAllPages<
  TFeature,
  TParams extends PaginationParams = PaginationParams,
>(
  fetchPageFn: (params: TParams) => Promise<PaginatedFeatureResponse<TFeature>>,
  params: Omit<TParams, "limit" | "offset">,
  pageSize: number = 2000
): Promise<{ type: "FeatureCollection"; features: TFeature[] }> {
  // Set up pagination variables
  let offset = 0;
  let nextOffset: number | null = 0;
  const features: TFeature[] = [];

  // Exhaust the paginated API for a full FeatureCollection.
  // nextOffset being null indicates no more pages.
  while (nextOffset !== null) {
    const page = await fetchPageFn({
      ...params,
      limit: pageSize,
      offset,
    } as TParams);

    features.push(...page.features);
    nextOffset = page.next_offset;

    if (nextOffset !== null) {
      offset = nextOffset;
    }
  }

  // Return the complete FeatureCollection
  return {
    type: "FeatureCollection",
    features,
  };
}
