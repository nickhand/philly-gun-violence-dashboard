/**
 * Shootings Data Store
 *
 * Manages loading and caching of shootings data using the versioned API endpoints.
 * Provides the base dataset for Arquero filtering.
 *
 * This store:
 * - Fetches metadata from /shootings/meta with ETag/304 support
 * - Loads row data per-year for fast initial load
 * - Lazy-loads additional years on demand
 * - Caches data in memory with version tracking
 * - Provides the base dataset for Arquero filtering
 *
 * @module shootingsStore
 */

import { defineStore } from "pinia";
import { markRaw } from "vue";
import type { ShootingRow } from "@/shared/types/shootings";
import {
  fetchShootingsMeta,
  fetchShootingsRows,
  type ShootingsMeta,
} from "@/shared/api/shootings";

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
  /** Raw row data indexed by year (for Arquero table initialization) */
  rowsByYear: Record<number, ShootingRow[]>;
  /** Set of years that have been loaded */
  loadedYears: Set<number>;
  /** True if currently loading initial data */
  isLoading: boolean;
  /** True if currently loading additional year data */
  isLoadingYear: boolean;
  /** Error message if loading failed */
  loadError: string | null;
  /** True if there was an error fetching metadata */
  metaError: boolean;
  /** Currently selected year for UI (not data filtering) */
  selectedYear: number | null | undefined;
  /** Cached metadata for per-year URLs */
  meta: ShootingsMeta | null;
}

export const useShootingsStore = defineStore("shootings", {
  state: (): ShootingsDataState => ({
    datasetVersion: null,
    datasetGeneratedAt: null,
    dataYears: [],
    totalRows: 0,
    rowsByYear: {},
    loadedYears: new Set(),
    isLoading: false,
    isLoadingYear: false,
    loadError: null,
    metaError: false,
    selectedYear: undefined,
    meta: null,
  }),

  getters: {
    /** Sorted years in descending order for UI display */
    sortedYears: (state): number[] =>
      [...state.dataYears].sort((a, b) => b - a),

    /** Whether any year data has been loaded */
    hasData: (state): boolean => state.loadedYears.size > 0,
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
     * Load a specific year's data.
     *
     * @param year - The year to load
     * @param setLoadingState - Whether to manage isLoadingYear state (default true)
     * @returns Promise resolving to true if data was loaded
     */
    async loadYear(year: number, setLoadingState = true): Promise<boolean> {
      // Already loaded
      if (this.loadedYears.has(year)) {
        return true;
      }

      // Need metadata first
      if (!this.meta) {
        console.warn("[ShootingsData] Cannot load year without metadata");
        return false;
      }

      const yearMeta = this.meta.years_meta[year];
      if (!yearMeta) {
        console.warn(`[ShootingsData] No metadata for year ${year}`);
        return false;
      }

      if (setLoadingState) {
        this.isLoadingYear = true;
      }
      const startTime = performance.now();

      try {
        const rows = await fetchShootingsRows(yearMeta.rows_url);

        if (import.meta.env.DEV) {
          console.log(
            `[ShootingsData] Year ${year} fetch: ${(performance.now() - startTime).toFixed(1)}ms (${rows.length} rows)`
          );
        }

        // Store rows for this year
        this.rowsByYear[year] = markRaw(rows as unknown as ShootingRow[]);
        this.loadedYears.add(year);

        return true;
      } catch (error) {
        console.error(`Failed to load year ${year}`, error);
        return false;
      } finally {
        if (setLoadingState) {
          this.isLoadingYear = false;
        }
      }
    },

    /**
     * Load all years' data (for "All Years" view).
     * Loads years in parallel for efficiency.
     *
     * @returns Promise resolving to true if all data was loaded
     */
    async loadAllYears(): Promise<boolean> {
      if (!this.meta) {
        return false;
      }

      const yearsToLoad = this.dataYears.filter(
        (y) => !this.loadedYears.has(y)
      );
      if (yearsToLoad.length === 0) {
        return true;
      }

      this.isLoadingYear = true;
      if (import.meta.env.DEV) {
        console.log(
          `[ShootingsData] loadAllYears: setting isLoadingYear=true, yearsToLoad=${yearsToLoad.join(",")}`
        );
      }
      const startTime = performance.now();

      try {
        // Load all remaining years in parallel (don't let individual loads manage state)
        await Promise.all(
          yearsToLoad.map((year) => this.loadYear(year, false))
        );

        if (import.meta.env.DEV) {
          console.log(
            `[ShootingsData] All years fetch: ${(performance.now() - startTime).toFixed(1)}ms`
          );
        }

        return true;
      } finally {
        this.isLoadingYear = false;
        if (import.meta.env.DEV) {
          console.log(
            `[ShootingsData] loadAllYears: setting isLoadingYear=false`
          );
        }
      }
    },

    /**
     * Fetch metadata and load initial year's data.
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

      // DEV: Add ?fresh query param to force fresh data fetch for timing tests
      const urlParams = new URLSearchParams(window.location.search);
      const forceFresh = urlParams.has("fresh") || forceReload;

      if (import.meta.env.DEV && forceFresh) {
        console.log("[ShootingsData] Force fresh fetch (skipping cache)");
      }

      try {
        // Fetch metadata with conditional request
        const lastVersion = forceFresh
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
        if (!metaResult.modified && this.loadedYears.size > 0) {
          if (import.meta.env.DEV) {
            console.log(
              `[ShootingsData] Data unchanged (304), using cached version`
            );
          }
          return false;
        }

        // Edge case: Got 304 but we don't have data in memory
        if (!metaResult.modified && this.loadedYears.size === 0) {
          if (import.meta.env.DEV) {
            console.log(
              `[ShootingsData] Got 304 but no data in memory, refetching without version`
            );
          }
          metaResult = await fetchShootingsMeta(null);
        }

        if (!metaResult.meta) {
          throw new Error("Meta endpoint returned no data");
        }

        const meta = metaResult.meta;

        // Update metadata state
        this.meta = meta;
        this.datasetVersion = meta.version;
        this.datasetGeneratedAt = meta.generated_at;
        this.dataYears = [...meta.years].sort((a, b) => b - a);
        this.totalRows = meta.rows;

        // If no year is selected yet, default to the most recent year
        if (this.dataYears.length && this.selectedYear === undefined) {
          this.selectedYear = this.dataYears[0];
        }

        // Clear any previously loaded data on version change
        if (forceReload) {
          this.rowsByYear = {};
          this.loadedYears = new Set();
        }

        // Load only the selected year's data for fast initial load
        const yearToLoad = this.selectedYear ?? this.dataYears[0];
        if (yearToLoad) {
          await this.loadYear(yearToLoad);
        }

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
     * Ensure the selected year's data is loaded.
     * Call this when the user changes the selected year.
     *
     * @param year - The year to ensure is loaded, or null for all years
     * @returns Promise resolving to true if data is available
     */
    async ensureYearLoaded(year: number | null): Promise<boolean> {
      if (import.meta.env.DEV) {
        console.log(
          `[ShootingsData] ensureYearLoaded called (year=${year}, isLoadingYear before=${this.isLoadingYear})`
        );
      }
      if (year === null) {
        // "All Years" selected - load all
        return this.loadAllYears();
      }
      return this.loadYear(year);
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
