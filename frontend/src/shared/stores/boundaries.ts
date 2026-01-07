import { defineStore } from "pinia";
import {
  fetchBoundaries,
  fetchBoundaryDatasets,
} from "@/shared/api/boundaries";

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
 * State interface for boundaries store.
 */
interface BoundariesState {
  /** List of available boundary dataset names */
  datasets: string[];
  /** True if there was an error fetching the datasets list */
  datasetsError: boolean;
  /** True if currently fetching the datasets list */
  isFetchingDatasets: boolean;
  /** Cache of boundary data by dataset name */
  dataCache: Record<string, BoundaryFeatureCollection>;
  /** True if currently loading boundary data */
  isLoading: Record<string, boolean>;
  /** Error messages by dataset name */
  loadErrors: Record<string, string | null>;
}

const defaultLoadErrorMessage =
  "We couldn't load the boundary data right now. Please retry or try again later.";

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
 * await boundariesStore.fetchDatasets();
 * const policeDistricts = await boundariesStore.fetchBoundaryData('police-districts');
 * ```
 */
export const useBoundariesStore = defineStore("boundaries", {
  state: (): BoundariesState => ({
    datasets: [],
    datasetsError: false,
    isFetchingDatasets: false,
    dataCache: {},
    isLoading: {},
    loadErrors: {},
  }),

  getters: {
    /**
     * Check if a specific dataset is currently loading.
     *
     * @param state - The store state
     * @returns Function that checks loading status for a dataset name
     */
    isDatasetLoading: (state) => (dataset: string) => {
      return state.isLoading[dataset] ?? false;
    },

    /**
     * Get cached boundary data for a specific dataset.
     *
     * @param state - The store state
     * @returns Function that retrieves cached data for a dataset name
     */
    getDataset: (state) => (dataset: string) => {
      return state.dataCache[dataset] ?? null;
    },

    /**
     * Check if a dataset has a load error.
     *
     * @param state - The store state
     * @returns Function that checks error status for a dataset name
     */
    hasError: (state) => (dataset: string) => {
      return (
        state.loadErrors[dataset] !== null &&
        state.loadErrors[dataset] !== undefined
      );
    },
  },

  actions: {
    /**
     * Fetches the list of available boundary datasets from the API.
     *
     * @returns Promise resolving to array of dataset names or null if fetch fails
     */
    async fetchDatasets(): Promise<string[] | null> {
      this.isFetchingDatasets = true;
      this.datasetsError = false;

      try {
        const response = await fetchBoundaryDatasets();
        this.datasets = response.datasets;
        return response.datasets;
      } catch (error) {
        console.error("Failed to fetch boundary datasets from API", error);
        this.datasetsError = true;
        this.datasets = [];
        return null;
      } finally {
        this.isFetchingDatasets = false;
      }
    },

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
      forceRefresh = false
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
      this.loadErrors[dataset] = null;

      try {
        const data = await fetchBoundaries(dataset);
        this.dataCache[dataset] = data;
        return data;
      } catch (error) {
        console.error(`Failed to fetch boundary data for ${dataset}`, error);
        this.loadErrors[dataset] = defaultLoadErrorMessage;
        return null;
      } finally {
        this.isLoading[dataset] = false;
      }
    },

    /**
     * Clears cached data for a specific dataset or all datasets.
     *
     * @param dataset - Name of dataset to clear, or undefined to clear all
     */
    clearCache(dataset?: string) {
      if (dataset) {
        delete this.dataCache[dataset];
        delete this.loadErrors[dataset];
      } else {
        this.dataCache = {};
        this.loadErrors = {};
      }
    },

    /**
     * Preloads multiple boundary datasets in parallel.
     * Useful for loading all required boundaries at app startup.
     *
     * @param datasets - Array of dataset names to preload
     * @returns Promise resolving when all datasets are loaded
     */
    async preloadDatasets(datasets: string[]): Promise<void> {
      await Promise.all(
        datasets.map((dataset) => this.fetchBoundaryData(dataset))
      );
    },
  },
});
