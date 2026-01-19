<template>
  <div class="mapping-dashboard-wrapper">
    <!-- Dashboard Header with stats -->
    <dashboard-header
      :fatal="fatalCount"
      :nonfatal="nonfatalCount"
      :current-year="currentYear"
      :min-year="minYear"
      :selected-year="selectedYear"
      :show-loading="showLoading"
    />

    <!-- Screen reader announcement for filter changes -->
    <div aria-live="polite" aria-atomic="true" class="sr-only" role="status">
      {{ filterAnnouncement }}
    </div>

    <!-- Map Explorer (map + sidebar + address search) -->
    <template v-if="dataReady">
      <!-- Screen reader description of map content -->
      <div class="sr-only" role="region" aria-label="Map data summary">
        <h2>Map Summary</h2>
        <p>{{ mapSummaryText }}</p>
      </div>

      <map-explorer
        ref="mapExplorerRef"
        :filtered-features="filteredFeatures"
        :layer-configs="layers"
        :filters="filters"
        :active-filters="activeFilters"
        :slider-limits="sliderLimits"
        :total-count="totalFeatures"
        :toggleable-layer-names="toggleableLayerNames"
        :choropleth-layer-names="choroplethLayerNames"
        :default-toggled-layer-names="defaultToggledLayerNames"
        :histograms="histograms"
        @map-ready="handleMapReady"
        @filter-change="handleFilterChange"
        @filter-reset="handleFilterReset"
        @reset-all="handleResetAll"
        @download="handleDownload"
      />
    </template>

    <!-- Chart dashboard showing breakdowns by category -->
    <chart-dashboard id="charts" :features="filteredFeatures" />
  </div>
</template>

<script setup lang="ts">
/**
 * MappingDashboard Component
 *
 * Main container for the interactive map dashboard with header and charts.
 * Orchestrates data filtering and passes filtered data to child components.
 *
 * Architecture:
 * - Uses Arquero for multi-dimensional filtering
 * - MapExplorer handles map + sidebar + address search as a unit
 *   (including all layer visibility state)
 * - DashboardHeader displays fatal/nonfatal counts
 * - ChartDashboard shows breakdown charts
 * - Filtered features flow: store → Arquero → all components
 *
 * @component
 */

import { ref, computed, watch } from "vue";
import { storeToRefs } from "pinia";
import MapExplorer from "@/features/explorer/components/MapExplorer.vue";
import DashboardHeader from "@/pages/components/DashboardHeader.vue";
import ChartDashboard from "@/features/charts/components/ChartDashboard.vue";
import { useArquero } from "@/pages/composables/useArquero";
import { useDownload } from "@/pages/composables/useDownload";
import { useHistograms } from "@/pages/composables/useHistograms";
import { useLoadingState } from "@/pages/composables/useLoadingState";
import { useMapConfig } from "@/features/explorer/composables/useMapConfig";
import { useUrlState } from "@/pages/composables/useUrlState";
import { useShootingsStore } from "@/shared/stores/shootings";
import type { ShootingRow } from "@/shared/types/shootings";

// Store access
const shootingsStore = useShootingsStore();
const {
  selectedYear,
  rowsByYear,
  sortedYears: dataYears,
  fatalCount,
  nonfatalCount,
} = storeToRefs(shootingsStore);

// Track whether the map component is ready
const mapReady = ref(false);

// Centralized loading state
const { showLoading, hasData: dataReady } = useLoadingState({
  componentReady: mapReady,
});

// Normalize selectedYear to exclude undefined
const normalizedYear = computed(() => selectedYear.value ?? null);

// Map configuration (filters and layers)
const {
  filters,
  layers,
  toggleableLayerNames,
  choroplethLayerNames,
  defaultToggledLayerNames,
} = useMapConfig(normalizedYear);

// Arquero composable for filtering
const {
  activeFilters,
  sliderLimits,
  filteredFeatures,
  initialize: initializeArquero,
  applyFilter,
  resetFilter,
  resetAllFilters,
  getHistogramData,
} = useArquero();

// Histograms composable for slider filter charts
const { histograms, initializeHistograms, updateHistograms } = useHistograms();

// Download composable for export functionality
const { handleDownload } = useDownload({ filteredFeatures, layers });

// Map Explorer ref (layer state is managed internally by MapExplorer)
const mapExplorerRef = ref<InstanceType<typeof MapExplorer> | null>(null);
const mapInstance = computed(() => mapExplorerRef.value?.mapInstance ?? null);

// Get active layers from MapExplorer for URL syncing
const activeLayers = computed(() => mapExplorerRef.value?.activeLayers ?? []);

// Previous count for announcement comparison
const previousFilteredCount = ref<number | null>(null);

// ============================================================================
// Header Statistics
// ============================================================================

const currentYear = computed(() => new Date().getFullYear());

const minYear = computed(() =>
  dataYears.value.length > 0
    ? dataYears.value[dataYears.value.length - 1]
    : null,
);

/**
 * Combined fatal/nonfatal counts for screen reader summary.
 * Single pass over filteredFeatures for efficiency.
 */
const filteredCounts = computed(() => {
  let fatal = 0;
  let nonfatal = 0;
  for (const f of filteredFeatures.value) {
    if (f.properties?.fatal === true) {
      fatal++;
    } else {
      nonfatal++;
    }
  }
  return { fatal, nonfatal };
});

/**
 * Announcement text for screen readers when filters change.
 */
const filterAnnouncement = computed(() => {
  const count = filteredFeatures.value.length;
  if (
    previousFilteredCount.value !== null &&
    previousFilteredCount.value !== count
  ) {
    return `Showing ${count.toLocaleString()} shooting victim${
      count !== 1 ? "s" : ""
    }`;
  }
  return "";
});

// Update previous count when filtered features change
watch(
  () => filteredFeatures.value.length,
  (_, oldCount) => {
    previousFilteredCount.value = oldCount;
  },
);

// Sync state with URL (year, layers, map view)
useUrlState(normalizedYear, activeLayers, mapInstance, [
  ...toggleableLayerNames.value,
  ...choroplethLayerNames.value,
]);

// ============================================================================
// Map Statistics
// ============================================================================

/**
 * Total feature count for current year.
 */
const totalFeatures = computed(() => {
  const year = selectedYear.value;
  if (year === null || year === undefined) {
    return Object.values(rowsByYear.value).reduce(
      (sum, rows) => sum + rows.length,
      0,
    );
  }
  return rowsByYear.value[year]?.length ?? 0;
});

/**
 * Number of features with valid coordinates.
 * Retrieved from MapExplorer to avoid duplicate computation.
 */
const pointsOnMap = computed(() => mapExplorerRef.value?.pointsOnMap ?? 0);

/**
 * Generate a text summary of map data for screen readers.
 */
const mapSummaryText = computed(() => {
  const total = filteredFeatures.value.length;
  const onMap = pointsOnMap.value;
  const { fatal, nonfatal } = filteredCounts.value;

  const yearText =
    normalizedYear.value === null
      ? "all years"
      : `the year ${normalizedYear.value}`;

  const activeFilterCount = activeFilters.value.size;
  const filterText =
    activeFilterCount > 0
      ? ` with ${activeFilterCount} filter${activeFilterCount > 1 ? "s" : ""} applied`
      : "";

  const layerText =
    activeLayers.value.length > 0
      ? ` Currently showing: ${activeLayers.value.join(", ")}.`
      : "";

  return `This interactive map displays ${total.toLocaleString()} shooting victim${
    total !== 1 ? "s" : ""
  } in Philadelphia for ${yearText}${filterText}. Of these, ${fatal.toLocaleString()} ${
    fatal === 1 ? "was" : "were"
  } fatal and ${nonfatal.toLocaleString()} ${
    nonfatal === 1 ? "was" : "were"
  } nonfatal. ${onMap.toLocaleString()} location${onMap !== 1 ? "s" : ""} ${
    onMap === 1 ? "is" : "are"
  } shown on the map.${layerText} Use the filters in the sidebar to narrow the data by date, outcome, demographics, and other criteria.`;
});

// ============================================================================
// Event Handlers
// ============================================================================

function handleFilterChange(dimensionId: string, value: any): void {
  applyFilter(dimensionId, value);
}

function handleFilterReset(dimensionId: string): void {
  resetFilter(dimensionId);
}

function handleResetAll(): void {
  resetAllFilters();
}

function handleMapReady(): void {
  mapReady.value = true;
}

// ============================================================================
// Lifecycle Hooks
// ============================================================================

/**
 * Reset active layers to defaults when year changes.
 * MapExplorer handles the internal state reset via resetLayers().
 */
watch(selectedYear, () => {
  mapExplorerRef.value?.resetLayers();
});

/**
 * Initialize Arquero filtering when data loads or year changes.
 */
watch(
  [rowsByYear, selectedYear],
  async ([yearData, year]) => {
    const loadStart = performance.now();
    await shootingsStore.ensureYearLoaded(year ?? null);

    let rowsToUse: ShootingRow[];
    if (year === null || year === undefined) {
      rowsToUse = Object.values(yearData).flat() as ShootingRow[];
    } else {
      rowsToUse = (yearData[year] as ShootingRow[]) ?? [];
    }

    if (rowsToUse.length > 0) {
      const startTime = performance.now();

      if (import.meta.env.DEV) {
        console.log(
          `[MappingDashboard] Using ${rowsToUse.length} rows (year=${year ?? "all"}, load=${(startTime - loadStart).toFixed(1)}ms)`,
        );
      }

      initializeArquero(rowsToUse, filters.value);
      initializeHistograms(filters.value, getHistogramData);

      if (import.meta.env.DEV) {
        console.log(
          `[MappingDashboard] Total data initialization in ${(performance.now() - startTime).toFixed(1)}ms`,
        );
      }
    }
  },
  { immediate: true },
);

/**
 * Update histograms when filters change.
 */
watch(
  activeFilters,
  () => {
    updateHistograms(getHistogramData);
  },
  { deep: true },
);
</script>

<style scoped>
/* MapExplorer now handles its own styling */
</style>
