import { defineStore } from "pinia";
import { fetchBoundaries } from "@/shared/api/boundaries";

/**
 * GeoJSON Feature for boundary data.
 */
interface BoundaryFeature {
  type: "Feature";
  geometry: GeoJSON.Geometry;
  properties: Record<string, unknown>;
}

/**
 * GeoJSON FeatureCollection for boundary data.
 */
interface BoundaryFeatureCollection {
  type: "FeatureCollection";
  features: BoundaryFeature[];
}

/**
 * State interface for boundaries store.
 */
interface BoundariesState {
  /** Cache of boundary data by dataset name */
  dataCache: Record<string, BoundaryFeatureCollection>;
  /** True if currently loading boundary data */
  isLoading: Record<string, boolean>;
}

/**
 * Pinia store for managing boundary GeoJSON data.
 *
 * Handles fetching and caching of boundary datasets from the API,
 * including police districts, council districts, ZIP codes, neighborhoods,
 * legislative districts, and school catchments.
 *
 * @example
 * ```typescript
 * const boundariesStore = useBoundariesStore();
 * const policeDistricts = await boundariesStore.fetchBoundaryData('police-districts');
 * ```
 */
export const useBoundariesStore = defineStore("boundaries", {
  state: (): BoundariesState => ({
    dataCache: {},
    isLoading: {},
  }),

  actions: {
    /**
     * Fetches boundary GeoJSON data for a specific dataset.
     * Returns cached data if already loaded.
     *
     * @param dataset - Name of the boundary dataset (e.g., 'police-districts')
     * @param forceRefresh - If true, bypass cache and fetch fresh data
     * @returns Promise resolving to boundary FeatureCollection or null if fetch fails
     */
    async fetchBoundaryData(
      dataset: string,
      forceRefresh = false,
    ): Promise<BoundaryFeatureCollection | null> {
      // Return cached data if available and not forcing refresh
      if (!forceRefresh && this.dataCache[dataset]) {
        return this.dataCache[dataset];
      }

      // Avoid duplicate requests
      if (this.isLoading[dataset]) {
        // Wait for the existing request
        return new Promise((resolve) => {
          const checkInterval = setInterval(() => {
            if (!this.isLoading[dataset]) {
              clearInterval(checkInterval);
              resolve(this.dataCache[dataset] ?? null);
            }
          }, 100);
        });
      }

      this.isLoading[dataset] = true;

      try {
        const data = await fetchBoundaries(dataset);
        this.dataCache[dataset] = data;
        return data;
      } catch (error) {
        console.error(`Failed to fetch boundary data for ${dataset}`, error);
        return null;
      } finally {
        this.isLoading[dataset] = false;
      }
    },
  },
});
