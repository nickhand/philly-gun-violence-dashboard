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
        <template v-if="hasHomicideData">
          <div v-if="selectedYear === currentYear" class="header-submessage">
            There {{ homicideTotalValue === 1 ? "has" : "have" }} been
            <span class="fatal"
              >{{ homicideTotal }}
              {{ homicideTotalValue === 1 ? "homicide" : "homicides" }}</span
            >
            in <span class="date-color">{{ currentYear }}</span
            ><template v-if="homicideChange"
              >, {{ homicideChange }} from {{ currentYear - 1 }}</template
            >.
          </div>
          <div
            v-else-if="selectedYear === null || selectedYear === undefined"
            class="header-submessage"
          >
            In total, there {{ homicideTotalValue === 1 ? "has" : "have" }} been
            <span class="fatal"
              >{{ homicideTotal }}
              {{ homicideTotalValue === 1 ? "homicide" : "homicides" }}</span
            ><span class="date-color"> since {{ minYear }}</span
            >.
          </div>
          <div v-else class="header-submessage">
            In total, there {{ homicideTotalValue === 1 ? "was" : "were" }}
            <span class="fatal"
              >{{ homicideTotal }}
              {{ homicideTotalValue === 1 ? "homicide" : "homicides" }}</span
            >
            in <span class="date-color">{{ selectedYear }}</span
            ><template v-if="homicideChange"
              >, {{ homicideChange }} from {{ selectedYear - 1 }}</template
            >.
          </div>
        </template>
        <div v-else class="header-submessage">
          Homicide totals are currently unavailable.
        </div>

        <!-- Shooting victims summary -->
        <div class="header-submessage">
          This app maps the victims of gun violence:
          <span class="nonfatal">{{ formatNumber(nonfatal) }} nonfatal</span>
          and
          <span class="fatal">{{ formatNumber(fatal) }} fatal</span>
          shooting victims
          <template v-if="selectedYear === currentYear">
            so far in <span class="date-color">{{ currentYear }}.</span>
          </template>
          <template v-else-if="selectedYear === null">
            since <span class="date-color">{{ minYear }}.</span>
          </template>
          <template v-else>
            in <span class="date-color">{{ selectedYear }}.</span>
          </template>
        </div>
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
const overlayColor = "#353d42";

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
.nonfatal {
  color: rgb(var(--v-theme-warning));
}

.fatal {
  color: rgb(var(--v-theme-error));
}

.date-color {
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
  }

  .header-message {
    text-align: center;
    font-size: 2.7rem;
  }
}
</style>
