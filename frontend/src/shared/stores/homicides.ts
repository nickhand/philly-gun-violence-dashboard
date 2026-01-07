import { defineStore } from "pinia";
import type { HomicideTotals } from "@/shared/api/homicides";
import { fetchHomicideTotals } from "@/shared/api/homicides";

interface HomicidesState {
  /** Cache of homicide totals by year */
  totalsCache: Record<number, HomicideTotals>;
  /** Currently selected year's totals */
  currentTotals: HomicideTotals | null;
  /** True if currently loading homicide totals */
  isLoadingTotals: boolean;
  /** Error message if loading totals failed */
  totalsLoadError: string | null;
}

const defaultLoadErrorMessage =
  "We couldn't load the homicide totals right now. Please retry or try again later.";

export const useHomicidesStore = defineStore("homicides", {
  state: (): HomicidesState => ({
    totalsCache: {},
    currentTotals: null,
    isLoadingTotals: false,
    totalsLoadError: null,
  }),
  actions: {
    /**
     * Fetches homicide totals for a specific year.
     * Caches data to avoid redundant API calls.
     *
     * @param year - The year to fetch totals for
     * @returns Promise resolving to homicide totals or null if fetch fails
     */
    async fetchTotals(year: number): Promise<HomicideTotals | null> {
      this.isLoadingTotals = true;
      this.totalsLoadError = null;

      try {
        // Check if data is already cached
        let totals = this.totalsCache[year];

        // If not cached, fetch from API
        if (!totals) {
          totals = await fetchHomicideTotals(year);
          this.totalsCache[year] = totals;
        }

        // Update current totals
        this.currentTotals = totals;
        return totals;
      } catch (error) {
        console.error(`Failed to fetch homicide totals for ${year}`, error);
        this.currentTotals = null;
        this.totalsLoadError = defaultLoadErrorMessage;
        return null;
      } finally {
        this.isLoadingTotals = false;
      }
    },
  },
});
