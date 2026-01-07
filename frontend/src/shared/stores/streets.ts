import { defineStore } from "pinia";
import { fetchStreetsAllPages, fetchStreetsPage } from "@/shared/api/streets";

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
 * GeoJSON FeatureCollection for street blocks.
 */
interface StreetFeatureCollection {
  type: "FeatureCollection";
  features: StreetFeature[];
}

/**
 * State interface for streets store.
 */
interface StreetsState {
  /** Cache of all street block features */
  allStreets: StreetFeatureCollection | null;
  /** True if currently loading street data */
  isLoading: boolean;
  /** Error message if loading failed */
  loadError: string | null;
  /** Timestamp of last successful load */
  lastLoaded: number | null;
}

const defaultLoadErrorMessage =
  "We couldn't load the street data right now. Please retry or try again later.";

/**
 * Pinia store for managing street block GeoJSON data.
 *
 * Handles fetching and caching street segment data from the API.
 * Street data is used for "hot spots by street block" choropleth layer.
 *
 * @example
 * ```typescript
 * const streetsStore = useStreetsStore();
 * await streetsStore.fetchAllStreets();
 * const filtered = streetsStore.getStreetsBySegmentIds(['123', '456']);
 * ```
 */
export const useStreetsStore = defineStore("streets", {
  state: (): StreetsState => ({
    allStreets: null,
    isLoading: false,
    loadError: null,
    lastLoaded: null,
  }),

  getters: {
    /**
     * Get the total number of street segments loaded.
     *
     * @param state - The store state
     * @returns Number of street features or 0 if not loaded
     */
    streetCount: (state) => {
      return state.allStreets?.features.length ?? 0;
    },

    /**
     * Check if street data has been successfully loaded.
     *
     * @param state - The store state
     * @returns True if data exists and no errors
     */
    hasData: (state) => {
      return state.allStreets !== null && state.loadError === null;
    },
  },

  actions: {
    /**
     * Fetches all street block data from the API.
     *
     * Streets data is paginated on the backend. This method fetches all pages
     * and combines them into a single FeatureCollection.
     *
     * @param forceRefresh - If true, bypass cache and fetch fresh data
     * @returns Promise resolving to street FeatureCollection or null if fetch fails
     */
    async fetchAllStreets(
      forceRefresh = false
    ): Promise<StreetFeatureCollection | null> {
      // Return cached data if available and not forcing refresh
      if (!forceRefresh && this.allStreets) {
        return this.allStreets;
      }

      // Avoid duplicate requests
      if (this.isLoading) {
        // Wait for the existing request
        return new Promise((resolve) => {
          const checkInterval = setInterval(() => {
            if (!this.isLoading) {
              clearInterval(checkInterval);
              resolve(this.allStreets);
            }
          }, 100);
        });
      }

      this.isLoading = true;
      this.loadError = null;

      try {
        const allFeatures: StreetFeature[] = [];
        let offset = 0;
        const limit = 2000; // Match API default batch size

        // Fetch all pages
        while (true) {
          const response = await fetchStreets({ limit, offset });

          allFeatures.push(...response.features);

          // Check if we've fetched all features
          if (!response.next_offset || response.next_offset >= response.total) {
            break;
          }

          offset = response.next_offset;
        }

        // Build the complete FeatureCollection
        this.allStreets = {
          type: "FeatureCollection",
          features: allFeatures,
        };

        this.lastLoaded = Date.now();
        return this.allStreets;
      } catch (error) {
        console.error("Failed to fetch street data from API", error);
        this.loadError = defaultLoadErrorMessage;
        return null;
      } finally {
        this.isLoading = false;
      }
    },

    /**
     * Fetches specific street blocks by segment IDs.
     *
     * More efficient than fetchAllStreets when you only need a subset.
     * Uses automatic pagination for the filtered results.
     *
     * @param segmentIds - Array of segment IDs to fetch
     * @returns Promise resolving to filtered FeatureCollection or null if fetch fails
     */
    async fetchStreetsBySegmentIds(
      segmentIds: string[]
    ): Promise<StreetFeatureCollection | null> {
      if (segmentIds.length === 0) {
        return { type: "FeatureCollection", features: [] };
      }

      this.isLoading = true;
      this.loadError = null;

      try {
        // Use the new fetchStreetsAllPages function with segment ID filter
        const data = await fetchStreetsAllPages({ segment_id: segmentIds });
        return data;
      } finally {
        this.isLoading = false;
      }
    },

    /**
     * Get streets by segment IDs from cache if available, otherwise fetch.
     *
     * @param segmentIds - Array of segment IDs to retrieve
     * @returns Filtered FeatureCollection or null
     */
    getStreetsBySegmentIds(
      segmentIds: string[]
    ): StreetFeatureCollection | null {
      if (!this.allStreets) {
        return null;
      }

      const filtered = this.allStreets.features.filter((feature) =>
        segmentIds.includes(feature.properties.segment_id)
      );

      return {
        type: "FeatureCollection",
        features: filtered,
      };
    },

    /**
     * Clears cached street data.
     */
    clearCache() {
      this.allStreets = null;
      this.loadError = null;
      this.lastLoaded = null;
    },
  },
});
