import Vue from "vue";
import Vuex, { StoreOptions } from "vuex";
import { githubFetch } from "@/utils/io";
import { timeParse } from "d3-time-format";
import { getMsSinceMidnight } from "@/utils/datetime";
import {
  ShootingVictimsGeoJson,
  ShootingVictimsProperties,
} from "@/types/ShootingsData";
import { Feature, Point } from "geojson";

Vue.use(Vuex);

export interface RootState {
  dataYears: number[];
  dataYearsError: boolean;
  selectedYear: number | null | undefined;
  isFetchingYears: boolean;
  dataCache: { [key: number]: ShootingVictimsGeoJson };
  currentData: ShootingVictimsGeoJson | null;
  isLoadingData: boolean;
  dataLoadError: string | null;
  overlayHold: boolean;
}

const defaultState: RootState = {
  dataYears: [],
  dataYearsError: false,
  selectedYear: undefined,
  isFetchingYears: false,
  dataCache: {},
  currentData: null,
  isLoadingData: false,
  dataLoadError: null,
  overlayHold: false,
};

const defaultLoadErrorMessage =
  "We couldn’t load the shootings data right now. Please retry or try again later.";

const storeOptions: StoreOptions<RootState> = {
  state: defaultState,
  mutations: {
    setDataYears(state, years: number[]) {
      state.dataYears = years;
      state.dataYearsError = false;
    },
    setDataYearsError(state, value: boolean) {
      state.dataYearsError = value;
    },
    setSelectedYear(state, year: number | null | undefined) {
      state.selectedYear = year;
    },
    setIsFetchingYears(state, value: boolean) {
      state.isFetchingYears = value;
    },
    setDataCacheEntry(
      state,
      payload: { year: number; data: ShootingVictimsGeoJson }
    ) {
      Vue.set(state.dataCache, payload.year, payload.data);
    },
    setCurrentData(state, data: ShootingVictimsGeoJson | null) {
      state.currentData = data;
    },
    setIsLoadingData(state, value: boolean) {
      state.isLoadingData = value;
    },
    setDataLoadError(state, value: string | null) {
      state.dataLoadError = value;
    },
    setOverlayHold(state, value: boolean) {
      state.overlayHold = value;
    },
  },
  actions: {
    async fetchDataYears({ commit, state }): Promise<number[] | null> {
      commit("setIsFetchingYears", true);
      commit("setDataLoadError", null);
      try {
        const dataYears: number[] = await githubFetch("data_years.json");
        commit("setDataYears", dataYears);
        // Only set selected year on first load; preserve current selection otherwise
        if (dataYears.length && state.selectedYear === undefined) {
          commit("setSelectedYear", dataYears[0]);
        }
        commit("setDataYearsError", false);
        return dataYears;
      } catch (error) {
        console.error("Failed to fetch data years from GitHub", error);
        commit("setDataYearsError", true);
        commit("setDataYears", []);
        commit("setDataLoadError", defaultLoadErrorMessage);
        return null;
      } finally {
        commit("setIsFetchingYears", false);
      }
    },
    setSelectedYear({ commit }, year: number | null | undefined) {
      commit("setSelectedYear", year);
    },

    async fetchShootingsData(
      { state, commit },
      year: number | null | undefined
    ): Promise<ShootingVictimsGeoJson | null> {
      commit("setIsLoadingData", true);
      commit("setDataLoadError", null);
      try {
        // Need data years to proceed for "all years"
        if (year === null && state.dataYears.length === 0) {
          throw new Error("No data years available");
        }

        // Single year
        if (year || year === 0) {
          const y = year as number;
        let data = state.dataCache[y];
        if (!data) {
          data = await fetchYearData(y);
          commit("setDataCacheEntry", { year: y, data });
        }
        commit("setCurrentData", data);
          return data;
        }

        // All years combined
        let combined: ShootingVictimsGeoJson | null = null;
        for (let i = 0; i < state.dataYears.length; i++) {
          const yr = state.dataYears[i];
          let data = state.dataCache[yr];
          if (!data) {
            data = await fetchYearData(yr);
            commit("setDataCacheEntry", { year: yr, data });
          }
          if (!combined) {
            combined = {
              ...data,
              features: [...data.features],
            };
          } else {
            combined.features = combined.features.concat(data.features);
          }
        }
        commit("setCurrentData", combined);
        return combined;
      } catch (error) {
        console.error("Failed to fetch shootings data", error);
        commit("setCurrentData", null);
        commit("setDataLoadError", defaultLoadErrorMessage);
        return null;
      } finally {
        commit("setIsLoadingData", false);
      }
    },
  },
  getters: {
    dataYears(state): number[] {
      return state.dataYears;
    },
    dataYearsError(state): boolean {
      return state.dataYearsError;
    },
    selectedYear(state): number | null | undefined {
      return state.selectedYear;
    },
    isFetchingYears(state): boolean {
      return state.isFetchingYears;
    },
    currentData(state): ShootingVictimsGeoJson | null {
      return state.currentData;
    },
    isLoadingData(state): boolean {
      return state.isLoadingData;
    },
    dataLoadError(state): string | null {
      return state.dataLoadError;
    },
    overlayHold(state): boolean {
      return state.overlayHold;
    },
  },
};

export default new Vuex.Store<RootState>(storeOptions);

/**
 * Fetch shootings data for a given year from S3 and add derived fields
 */
async function fetchYearData(year: number): Promise<ShootingVictimsGeoJson> {
  const url = "https://philly-gun-violence-map.s3.amazonaws.com/";
  const response = await fetch(url + `shootings_${year}.json`);
  if (!response.ok) {
    throw new Error(
      `Failed to fetch shootings data for ${year}: ${response.status} ${response.statusText}`
    );
  }
  const data = await response.json();

  // Format for the time
  const parseTime = timeParse("%Y/%m/%d %H:%M:%S");

  // Loop over features
  data.features.forEach(
    (d: Feature<Point | null, ShootingVictimsProperties>, i: number) => {
      // Parse the date
      const dt = parseTime(d.properties["date"]);

      // Add additional date properties
      if (dt) {
        const ms = dt.getTime();
        d.properties["dateInMs"] = ms;
        d.properties["timeInMs"] = getMsSinceMidnight(ms);
        d.properties["weekday"] = dt.getDay();
      }

      // Add the unique identifier
      d.properties["unique_id"] = i;
    }
  );

  return data;
}
