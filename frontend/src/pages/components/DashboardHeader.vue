<template>
  <div class="dashboard-header">
    <div class="header-message">Mapping Philadelphia's Gun Violence</div>

    <div>
      <v-overlay
        :model-value="showOverlay"
        :opacity="overlayOpacity"
        :scrim="overlayColor"
      />

      <div style="position: relative">
        <v-overlay
          :model-value="showOverlay"
          :opacity="overlayOpacityInner"
          :scrim="overlayColor"
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
import { computed, onMounted, watch } from "vue";
import { format } from "d3-format";
import { useHomicidesStore } from "@/shared/stores/homicides";

const props = defineProps<{
  fatal?: number;
  nonfatal?: number;
  selectedYear: number | null | undefined;
  currentYear: number;
  minYear: number;
  latestDataDate?: Date | null;
  showOverlay: boolean;
}>();

const homicidesStore = useHomicidesStore();

// Overlay constants (matches Vue 2 legacy)
const overlayOpacity = 0.3;
const overlayOpacityInner = 0.9;
const overlayColor = "background"; // Uses Vuetify theme color

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
 */
async function loadHomicideData() {
  if (props.selectedYear === null || props.selectedYear === undefined) {
    // For "All Years", pre-fetch all years data
    await fetchAllYearsTotals();
  } else {
    // Fetch data for selected year
    await homicidesStore.fetchTotals(props.selectedYear);
    // Also fetch previous year for year-over-year change calculation
    if (props.selectedYear > props.minYear) {
      await homicidesStore.fetchTotals(props.selectedYear - 1);
    }
  }
}

/**
 * Check if homicide data is available for the current selection.
 */
const hasHomicideData = computed(() => {
  if (props.selectedYear === null || props.selectedYear === undefined) {
    return Object.keys(homicidesStore.totalsCache).length > 0;
  }
  return props.selectedYear in homicidesStore.totalsCache;
});

/**
 * Get the numeric homicide total value for pluralization checks.
 */
const homicideTotalValue = computed((): number => {
  if (props.selectedYear === null || props.selectedYear === undefined) {
    // Sum across all years
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
// This handles the case where "All Years" is selected before dataYears is populated
watch(
  () => props.minYear,
  () => {
    if (props.selectedYear === null || props.selectedYear === undefined) {
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
