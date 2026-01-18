<template>
  <div class="dashboard-header">
    <div class="header-message">Mapping Philadelphia's Gun Violence</div>

    <div>
      <v-overlay
        :model-value="showOverlay || isLoadingHomicides"
        :opacity="OVERLAY_OPACITY"
        :scrim="OVERLAY_COLOR"
      />

      <div style="position: relative">
        <v-overlay
          :model-value="showOverlay || isLoadingHomicides"
          :opacity="OVERLAY_OPACITY_INNER"
          :scrim="OVERLAY_COLOR"
          absolute
        />

        <!-- Homicide summary -->
        <div
          v-if="hasHomicideData"
          class="header-submessage"
          v-html="homicideMessage"
        />
        <div v-else class="header-submessage">
          Homicide totals are currently unavailable.
        </div>

        <!-- Shooting victims summary -->
        <div class="header-submessage" v-html="shootingMessage" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { format } from "d3-format";
import { useHomicidesStore } from "@/shared/stores/homicides";
import {
  OVERLAY_OPACITY,
  OVERLAY_OPACITY_INNER,
  OVERLAY_COLOR,
} from "@/shared/config/overlay";

const props = defineProps<{
  fatal?: number;
  nonfatal?: number;
  selectedYear: number | null | undefined;
  currentYear: number;
  minYear: number | null;
  showOverlay: boolean;
}>();

const homicidesStore = useHomicidesStore();

// Track loading state to prevent showing partial data
const isLoadingHomicides = ref(false);
// Counter to track which load operation is current (prevents race conditions)
let loadOperationId = 0;

/**
 * Format a number with comma separators and zero decimal places.
 */
function formatNumber(value: number | undefined): string {
  if (typeof value === "number") return format(",.0f")(value);
  return "0";
}

/**
 * Fetch and sum homicide totals across all years from minYear to currentYear.
 */
async function fetchAllYearsTotals(): Promise<number | null> {
  if (props.minYear === null) return null;

  let total = 0;
  try {
    for (let year = props.minYear; year <= props.currentYear; year++) {
      const totals = await homicidesStore.fetchTotals(year);
      if (totals) {
        // Use annual if available, otherwise YTD
        total += totals.annual ?? totals.ytd;
      }
    }
    return total;
  } catch (error) {
    console.error(
      "Failed to calculate total homicides across all years",
      error
    );
    return null;
  }
}

/**
 * Load homicide data when selectedYear changes.
 * Fetches both selected year and previous year before allowing render.
 * Uses operation ID to prevent race conditions from overlapping calls.
 */
async function loadHomicideData() {
  // Don't load if minYear isn't set yet (data not loaded)
  if (props.minYear === null) {
    if (import.meta.env.DEV) {
      console.log(
        "[DashboardHeader] loadHomicideData skipped - minYear is null"
      );
    }
    return;
  }

  const currentOperationId = ++loadOperationId;
  isLoadingHomicides.value = true;

  if (import.meta.env.DEV) {
    console.log(
      `[DashboardHeader] loadHomicideData started (op #${currentOperationId}, year=${props.selectedYear}, minYear=${props.minYear})`
    );
  }

  try {
    if (props.selectedYear === null || props.selectedYear === undefined) {
      // For "All Years", pre-fetch all years data
      await fetchAllYearsTotals();
    } else {
      // Fetch selected year and previous year in parallel to ensure change can be calculated
      const fetches: Promise<unknown>[] = [
        homicidesStore.fetchTotals(props.selectedYear),
      ];
      if (props.selectedYear > props.minYear) {
        fetches.push(homicidesStore.fetchTotals(props.selectedYear - 1));
      }

      // Wait for all fetches to complete
      const results = await Promise.all(fetches);

      if (import.meta.env.DEV) {
        console.log(
          `[DashboardHeader] fetched years - selected: ${results[0] ? "OK" : "FAILED"}, previous: ${results[1] !== undefined ? (results[1] ? "OK" : "FAILED") : "N/A"}`
        );
      }
    }
  } catch (error) {
    console.error("[DashboardHeader] Error loading homicide data:", error);
  } finally {
    // Only clear loading state if this is still the current operation
    if (currentOperationId === loadOperationId) {
      isLoadingHomicides.value = false;
      if (import.meta.env.DEV) {
        console.log(
          `[DashboardHeader] loadHomicideData completed (op #${currentOperationId}, year=${props.selectedYear})`
        );
      }
    } else {
      if (import.meta.env.DEV) {
        console.log(
          `[DashboardHeader] loadHomicideData STALE - ignoring (op #${currentOperationId}, current=#${loadOperationId})`
        );
      }
    }
  }
}

/**
 * Check if homicide data is available for the current selection.
 * For single year views, also checks that previous year data is loaded
 * to ensure the year-over-year change can be calculated.
 */
const hasHomicideData = computed(() => {
  // Don't show data while loading to prevent partial renders
  if (isLoadingHomicides.value) return false;

  // Don't show data if minYear isn't loaded yet
  if (props.minYear === null) return false;

  if (props.selectedYear === null || props.selectedYear === undefined) {
    return Object.keys(homicidesStore.totalsCache).length > 0;
  }

  // For single year, check that selected year is in cache
  const hasSelectedYear = props.selectedYear in homicidesStore.totalsCache;

  // For years after minYear, also check previous year is loaded (for change calculation)
  if (props.selectedYear > props.minYear) {
    const hasPreviousYear =
      props.selectedYear - 1 in homicidesStore.totalsCache;
    return hasSelectedYear && hasPreviousYear;
  }

  return hasSelectedYear;
});

/**
 * Get the numeric homicide total value for pluralization checks.
 */
const homicideTotalValue = computed((): number => {
  if (props.selectedYear === null || props.selectedYear === undefined) {
    // Sum across all years
    if (props.minYear === null) return 0;

    let total = 0;
    for (let year = props.minYear; year <= props.currentYear; year++) {
      const data = homicidesStore.totalsCache[year];
      if (data) {
        total += data.annual ?? data.ytd;
      }
    }
    return total;
  } else {
    const data = homicidesStore.totalsCache[props.selectedYear];
    if (!data) return 0;

    // Use YTD for current year, annual for past years
    const value =
      props.selectedYear === props.currentYear ? data.ytd : data.annual;
    return value ?? 0;
  }
});

/**
 * Get the formatted homicide total for the selected year or all years.
 */
const homicideTotal = computed((): string | null => {
  const value = homicideTotalValue.value;
  return value > 0 ? format(",.0f")(value) : null;
});

/**
 * Get the formatted year-over-year change in homicide count.
 */
const homicideChange = computed((): string | null => {
  if (!props.selectedYear || props.selectedYear === null) return null;

  const thisYearData = homicidesStore.totalsCache[props.selectedYear];
  const lastYearData = homicidesStore.totalsCache[props.selectedYear - 1];

  if (!thisYearData || !lastYearData) return null;

  // Use appropriate values based on current year
  // For current year: compare YTD to YTD (same time period)
  // For past years: compare annual to annual
  const thisYearValue =
    props.selectedYear === props.currentYear
      ? thisYearData.ytd
      : thisYearData.annual;
  const lastYearValue =
    props.selectedYear === props.currentYear
      ? lastYearData.ytd
      : lastYearData.annual;

  if (thisYearValue === null || lastYearValue === null) return null;
  if (lastYearValue === 0) return null;

  const percentChange = 100 * (thisYearValue / lastYearValue - 1);

  if (percentChange > 0) {
    return `a ${percentChange.toFixed(0)}% increase`;
  } else if (percentChange < 0) {
    return `a ${Math.abs(percentChange).toFixed(0)}% decrease`;
  } else {
    return "no change";
  }
});

/**
 * Build the homicide summary message HTML.
 */
const homicideMessage = computed((): string => {
  const total = homicideTotal.value;
  const count = homicideTotalValue.value;
  const change = homicideChange.value;
  const hasHave = count === 1 ? "has" : "have";
  const wasWere = count === 1 ? "was" : "were";
  const noun = count === 1 ? "homicide" : "homicides";

  const fatalSpan = `<span class="fatal">${total} ${noun}</span>`;
  const changeText = change
    ? `, ${change} from ${(props.selectedYear ?? props.currentYear) - 1}`
    : "";

  if (props.selectedYear === props.currentYear) {
    const dateSpan = `<span class="date-color">${props.currentYear}</span>`;
    return `There ${hasHave} been ${fatalSpan} in ${dateSpan}${changeText}.`;
  }

  if (props.selectedYear === null || props.selectedYear === undefined) {
    const dateSpan = `<span class="date-color">since ${props.minYear}</span>`;
    return `In total, there ${hasHave} been ${fatalSpan} ${dateSpan}.`;
  }

  const dateSpan = `<span class="date-color">${props.selectedYear}</span>`;
  return `In total, there ${wasWere} ${fatalSpan} in ${dateSpan}${changeText}.`;
});

/**
 * Build the shooting victims summary message HTML.
 */
const shootingMessage = computed((): string => {
  const nonfatalText = `<span class="nonfatal">${formatNumber(props.nonfatal)} nonfatal</span>`;
  const fatalText = `<span class="fatal">${formatNumber(props.fatal)} fatal</span>`;

  let dateText: string;
  if (props.selectedYear === props.currentYear) {
    dateText = `so far in <span class="date-color">${props.currentYear}.</span>`;
  } else if (props.selectedYear === null) {
    dateText = `since <span class="date-color">${props.minYear}.</span>`;
  } else {
    dateText = `in <span class="date-color">${props.selectedYear}.</span>`;
  }

  return `This map shows the victims of gun violence: ${nonfatalText} and ${fatalText} shooting victims ${dateText}`;
});

// Load initial homicide data on mount
onMounted(() => {
  loadHomicideData();
});

// Reload homicide data when selected year changes
watch(
  () => props.selectedYear,
  () => {
    loadHomicideData();
  }
);

// Reload homicide data when minYear changes (dataYears loaded)
// This handles the case where data loads after initial mount,
// and we need to fetch previous year data for year-over-year change
watch(
  () => props.minYear,
  (newMinYear, oldMinYear) => {
    // Reload if minYear changed and we now need previous year data
    // This happens when dataYears loads after initial mount
    if (newMinYear !== oldMinYear) {
      loadHomicideData();
    }
  }
);
</script>

<style scoped>
/* Use :deep() to style v-html content */
.header-submessage :deep(.nonfatal) {
  color: rgb(var(--v-theme-warning));
}

.header-submessage :deep(.fatal) {
  color: rgb(var(--v-theme-error));
}

.header-submessage :deep(.date-color) {
  color: rgb(var(--v-theme-secondary));
}

.dashboard-header {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  margin-top: 40px;
  margin-bottom: 60px;
  color: rgb(var(--v-theme-primary));
}

.header-message {
  font-size: 3rem;
  font-weight: 500;
  line-height: 1.1;
  font-family: var(--heading-font-family);
  text-align: center;
  padding: 0 0.5rem;
}

.header-submessage {
  font-size: 2rem;
  font-weight: 300;
  line-height: 1.2;
  font-family: var(--heading-font-family);
  margin-top: 30px;
  max-width: 700px;
  text-align: center;
  padding: 0 3rem;
}

.header-submessage:nth-child(3) {
  margin-top: 50px;
}

@media only screen and (max-width: 767px) {
  .header-submessage {
    font-size: 1.6rem;
    margin-top: 50px;
    text-align: center;
    line-height: 1.2;
    padding: 0 1.5rem;
  }

  .header-message {
    text-align: center;
    font-size: 2.7rem;
    padding: 0 1.25rem;
  }
}
</style>
