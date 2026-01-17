/**
 * Shootings Data Store
 *
 * Manages loading and caching of shootings data using the versioned API endpoints.
 * Provides the base dataset for Arquero filtering.
 *
 * This store:
 * - Fetches metadata from /shootings/meta with ETag/304 support
 * - Loads row data from versioned NDJSON endpoint
 * - Caches data in memory with version tracking
 * - Provides the base dataset for Arquero filtering
 *
 * @module shootingsDataStore
 */

import { defineStore } from "pinia";
import { markRaw } from "vue";
import type { ShootingRow } from "@/shared/types/shootings";
import { fetchShootingsMeta, fetchShootingsRows } from "@/shared/api/shootings";

const STORAGE_KEY_VERSION = "shootings_data_version";
const STORAGE_KEY_GENERATED_AT = "shootings_data_generated_at";

const defaultLoadErrorMessage =
  "We couldn't load the shootings data right now. Please retry or try again later.";

interface ShootingsDataState {
  /** Current dataset version (content hash) */
  datasetVersion: string | null;
  /** ISO timestamp when dataset was generated */
  datasetGeneratedAt: string | null;
  /** Available years in the dataset */
  dataYears: number[];
  /** Total number of rows in dataset */
  totalRows: number;
  /** Raw row data (for Arquero table initialization) */
  rows: ShootingRow[] | null;
  /** True if currently loading data */
  isLoading: boolean;
  /** Error message if loading failed */
  loadError: string | null;
  /** True if there was an error fetching metadata */
  metaError: boolean;
  /** Whether to hold the overlay on the map */
  overlayHold: boolean;
  /** Currently selected year for UI (not data filtering) */
  selectedYear: number | null | undefined;
}

export const useShootingsDataStore = defineStore("shootingsData", {
  state: (): ShootingsDataState => ({
    datasetVersion: null,
    datasetGeneratedAt: null,
    dataYears: [],
    totalRows: 0,
    rows: null,
    isLoading: false,
    loadError: null,
    metaError: false,
    overlayHold: false,
    selectedYear: undefined,
  }),

  getters: {
    /** Whether the dataset is ready (loaded) */
    isReady: (state): boolean => state.rows !== null,

    /** Whether data is being fetched (for loading indicators) */
    isFetchingYears: (state): boolean => state.isLoading && state.rows === null,

    /** Sorted years in descending order for UI display */
    sortedYears: (state): number[] =>
      [...state.dataYears].sort((a, b) => b - a),
  },

  actions: {
    /**
     * Sets the selected year for filtering shootings data.
     *
     * @param year - Year number, null (for all years), or undefined
     */
    setSelectedYear(year: number | null | undefined) {
      this.selectedYear = year;
    },

    /**
     * Sets whether to hold the overlay on the map.
     *
     * @param value - True to hold the overlay, false to release it
     */
    setOverlayHold(value: boolean) {
      this.overlayHold = value;
    },

    /**
     * Load the last known version from localStorage.
     * Used for conditional requests on startup.
     */
    loadCachedVersion(): string | null {
      try {
        return localStorage.getItem(STORAGE_KEY_VERSION);
      } catch {
        return null;
      }
    },

    /**
     * Save the current version to localStorage.
     */
    saveCachedVersion(): void {
      try {
        if (this.datasetVersion) {
          localStorage.setItem(STORAGE_KEY_VERSION, this.datasetVersion);
        }
        if (this.datasetGeneratedAt) {
          localStorage.setItem(
            STORAGE_KEY_GENERATED_AT,
            this.datasetGeneratedAt
          );
        }
      } catch {
        // Ignore storage errors
      }
    },

    /**
     * Fetch metadata and load dataset if needed.
     * Uses conditional requests (ETag/304) to avoid unnecessary data transfers.
     *
     * @param forceReload - If true, skip version check and reload data
     * @returns Promise resolving to true if data was loaded/refreshed
     */
    async loadDatasetIfNeeded(forceReload: boolean = false): Promise<boolean> {
      this.isLoading = true;
      this.loadError = null;
      this.metaError = false;

      const startTime = performance.now();

      try {
        // Fetch metadata with conditional request
        const lastVersion = forceReload
          ? null
          : (this.datasetVersion ?? this.loadCachedVersion());
        let metaResult = await fetchShootingsMeta(lastVersion);

        const metaTime = performance.now();
        if (import.meta.env.DEV) {
          console.log(
            `[ShootingsData] Meta fetch: ${(metaTime - startTime).toFixed(1)}ms`
          );
        }

        // If not modified and we already have data, we're done
        if (!metaResult.modified && this.rows !== null) {
          if (import.meta.env.DEV) {
            console.log(
              `[ShootingsData] Data unchanged (304), using cached version`
            );
          }
          return false;
        }

        // Edge case: Got 304 but we don't have data in memory (e.g., stale localStorage version)
        // Retry without the version header to get fresh data
        if (!metaResult.modified && this.rows === null) {
          if (import.meta.env.DEV) {
            console.log(
              `[ShootingsData] Got 304 but no data in memory, refetching without version`
            );
          }
          metaResult = await fetchShootingsMeta(null);
        }

        // If modified or we don't have data, fetch the rows
        if (!metaResult.meta) {
          throw new Error("Meta endpoint returned no data");
        }

        const meta = metaResult.meta;

        // Update metadata state
        this.datasetVersion = meta.version;
        this.datasetGeneratedAt = meta.generated_at;
        this.dataYears = [...meta.years].sort((a, b) => b - a);
        this.totalRows = meta.rows;

        // If no year is selected yet, default to the most recent year
        if (this.dataYears.length && this.selectedYear === undefined) {
          this.selectedYear = this.dataYears[0];
        }

        // Fetch rows from versioned endpoint
        const rows = await fetchShootingsRows(meta.rows_url);

        const rowsTime = performance.now();
        if (import.meta.env.DEV) {
          console.log(
            `[ShootingsData] Rows fetch: ${(rowsTime - metaTime).toFixed(1)}ms (${rows.length} rows)`
          );
        }

        // Store rows (marked as raw to prevent Vue deep reactivity)
        // Cast through unknown since the API returns Record<string, unknown>[]
        this.rows = markRaw(rows as unknown as ShootingRow[]);

        // Save version to localStorage for future conditional requests
        this.saveCachedVersion();

        const totalTime = performance.now();
        if (import.meta.env.DEV) {
          console.log(
            `[ShootingsData] Total load time: ${(totalTime - startTime).toFixed(1)}ms`
          );
        }

        return true;
      } catch (error) {
        console.error("Failed to load shootings data", error);
        this.loadError = defaultLoadErrorMessage;
        this.metaError = true;
        return false;
      } finally {
        this.isLoading = false;
      }
    },

    /**
     * Force reload the dataset, ignoring cached version.
     *
     * @returns Promise resolving to true if data was loaded
     */
    async reloadDataset(): Promise<boolean> {
      return this.loadDatasetIfNeeded(true);
    },

    /**
     * Check for dataset updates without blocking.
     * Useful for periodic refresh checks.
     *
     * @returns Promise resolving to true if data was updated
     */
    async checkForUpdates(): Promise<boolean> {
      // Don't check if already loading
      if (this.isLoading) {
        return false;
      }

      return this.loadDatasetIfNeeded(false);
    },
  },
});
