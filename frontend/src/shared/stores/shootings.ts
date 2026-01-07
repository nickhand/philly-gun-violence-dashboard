import { defineStore } from "pinia";
import type {
  ShootingVictimsGeoJson,
  ShootingVictimsGeoJsonApi,
} from "@/shared/types/shootings";
import {
  fetchShootingsAllPages,
  fetchShootingsYears,
} from "@/shared/api/shootings";
import { getMsSinceMidnight, parseIncidentDate } from "@/shared/utils/datetime";

interface ShootingsState {
  /** List of years with available shootings data */
  dataYears: number[];
  /** True if there was an error fetching the years list */
  dataYearsError: boolean;
  /** Currently selected year for filtering shootings data; null for all years */
  selectedYear: number | null | undefined;
  /** True if currently fetching the years list */
  isFetchingYears: boolean;
  /** Cache of shootings data by year or "all" */
  dataCache: Record<string, ShootingVictimsGeoJson>;
  /** Currently loaded shootings data */
  currentData: ShootingVictimsGeoJson | null;
  /** True if currently loading shootings data */
  isLoadingData: boolean;
  /** Error message if loading data failed */
  dataLoadError: string | null;
  /** Whether to hold the overlay on the map */
  overlayHold: boolean;
}

const defaultLoadErrorMessage =
  "We couldn't load the shootings data right now. Please retry or try again later.";

export const useShootingsStore = defineStore("shootings", {
  state: (): ShootingsState => ({
    dataYears: [],
    dataYearsError: false,
    selectedYear: undefined,
    isFetchingYears: false,
    dataCache: {},
    currentData: null,
    isLoadingData: false,
    dataLoadError: null,
    overlayHold: false,
  }),
  actions: {
    /**
     * Fetches the list of years for which shootings data is available.
     * Sets the selected year to the most recent year if none is selected.
     *
     * @returns Promise resolving to array of years or null if fetch fails
     */
    async fetchDataYears(): Promise<number[] | null> {
      // We are fetching the years list.
      this.isFetchingYears = true;
      this.dataLoadError = null;

      try {
        // Fetch years from the API.
        const dataYears = await fetchShootingsYears();

        // Sort years in descending order for UI.
        this.dataYears = [...dataYears].sort((a, b) => b - a);
        this.dataYearsError = false;

        // If no year is selected yet, default to the most recent year.
        if (dataYears.length && this.selectedYear === undefined) {
          this.selectedYear = this.dataYears[0];
        }
        return dataYears;
        // Catch any errors during the fetch.
      } catch (error) {
        console.error("Failed to fetch data years from API", error);
        this.dataYearsError = true;
        this.dataYears = [];
        this.dataLoadError = defaultLoadErrorMessage;
        return null;
      } finally {
        this.isFetchingYears = false;
      }
    },
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
     * Fetches shootings data for a specific year or all years.
     * Caches individual years to avoid redundant API calls and reduce memory usage.
     * When fetching all years, individual years are cached and concatenated.
     *
     * @param year - Year to fetch data for (null or undefined for all years)
     * @returns Promise resolving to shootings data or null if fetch fails
     */
    async fetchShootingsData(
      year: number | null | undefined
    ): Promise<ShootingVictimsGeoJson | null> {
      this.isLoadingData = true;
      this.dataLoadError = null;

      try {
        let data: ShootingVictimsGeoJson;

        // If requesting all years, fetch each year individually and concatenate
        if (year === null || year === undefined) {
          const allFeatures: ShootingVictimsGeoJson["features"] = [];

          // Fetch each year (which will cache them individually)
          for (const yearNum of this.dataYears) {
            const cacheKey = String(yearNum);
            let yearData = this.dataCache[cacheKey];

            // If not cached, fetch from API and normalize
            if (!yearData) {
              const apiData: ShootingVictimsGeoJsonApi =
                await fetchShootingsAllPages({ year: yearNum });
              yearData = normalizeShootingsData(apiData);
              this.dataCache[cacheKey] = yearData;
            }

            // Concatenate features from this year
            allFeatures.push(...yearData.features);
          }

          // Return concatenated data without caching
          data = {
            type: "FeatureCollection",
            features: allFeatures,
          };
        } else {
          // Fetch specific year
          const cacheKey = String(year);
          let yearData = this.dataCache[cacheKey];

          // If not cached, fetch from API and normalize
          if (!yearData) {
            const apiData: ShootingVictimsGeoJsonApi =
              await fetchShootingsAllPages({ year });
            yearData = normalizeShootingsData(apiData);
            this.dataCache[cacheKey] = yearData;
          }

          data = yearData;
        }

        // Update current data
        this.currentData = data;
        return data;
      } catch (error) {
        console.error("Failed to fetch shootings data", error);
        this.currentData = null;
        this.dataLoadError = defaultLoadErrorMessage;
        return null;
      } finally {
        this.isLoadingData = false;
      }
    },
  },
});

/**
 * Normalizes shootings data from the API by adding derived time fields.
 *
 * Adds the following properties to each feature:
 * - `dateInMs`: Timestamp of the incident date
 * - `timeInMs`: Milliseconds since midnight of the incident date
 * - `weekday`: Day of the week (0=Sunday, 6=Saturday)
 * - `unique_id`: Unique identifier for each feature
 *
 * @param apiData - Raw shootings data from the API
 * @returns Normalized shootings data with derived time fields
 */
function normalizeShootingsData(
  apiData: ShootingVictimsGeoJsonApi
): ShootingVictimsGeoJson {
  // Add derived time fields to each feature.
  const features = apiData.features.map((feature, index) => {
    const dt = parseIncidentDate(feature.properties.date);
    const dateInMs = dt ? dt.getTime() : 0;
    const timeInMs = dt ? getMsSinceMidnight(dateInMs) : 0;
    const weekday = dt ? dt.getDay() : 0;

    return {
      ...feature,
      properties: {
        ...feature.properties,
        dateInMs,
        timeInMs,
        weekday,
        unique_id: index,
      },
    };
  });

  return {
    type: "FeatureCollection",
    features,
  };
}
