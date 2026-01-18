<template>
  <div class="mapping-dashboard-wrapper">
    <!-- Dashboard Header with stats -->
    <dashboard-header
      :fatal="fatalCount"
      :nonfatal="nonfatalCount"
      :current-year="currentYear"
      :min-year="minYear"
      :selected-year="selectedYear"
      :show-overlay="showOverlay"
    />

    <!-- Screen reader announcement for filter changes -->
    <div aria-live="polite" aria-atomic="true" class="sr-only" role="status">
      {{ filterAnnouncement }}
    </div>

    <!-- Map and sidebar container -->
    <div class="mapping-dashboard" v-if="dataReady">
      <!-- Screen reader description of map content -->
      <div class="sr-only" role="region" aria-label="Map data summary">
        <h2>Map Summary</h2>
        <p>{{ mapSummaryText }}</p>
      </div>

      <!-- Map container with sidebar -->
      <div
        class="map-container"
        role="application"
        aria-label="Interactive map showing shooting locations in Philadelphia"
      >
        <filterable-map
          ref="mapRef"
          :filtered-features="filteredFeatures"
          :layer-configs="layers"
          :active-layers="activeLayers"
          @map-ready="handleMapReady"
        />

        <!-- Address search overlay -->
        <div class="address-search-container">
          <address-search
            ref="addressSearchRef"
            @select="handleAddressSelect"
            @clear="handleAddressClear"
          />
        </div>

        <!-- Search marker (shows when address is selected) -->
        <search-marker
          v-if="searchMarkerPosition"
          :x="searchMarkerPosition.x"
          :y="searchMarkerPosition.y"
        />
      </div>

      <!-- Sidebar with filters -->
      <map-sidebar
        id="filters"
        ref="sidebarRef"
        :filters="filters"
        :active-filters="activeFilters"
        :slider-limits="sliderLimits"
        :feature-count="filteredFeatures.length"
        :total-count="totalFeatures"
        :points-on-map="pointsOnMap"
        :toggleable-layer-names="toggleableLayerNames"
        :overlay-layer-names="overlayLayerNames"
        :default-toggled-layer-names="defaultToggledLayerNames"
        :initial-active-layers="initialToggleableLayers"
        :initial-overlay="currentOverlay"
        :histograms="histograms"
        @filter-change="handleFilterChange"
        @filter-reset="handleFilterReset"
        @reset-all="handleResetAll"
        @download="handleDownload"
        @layer-change="handleLayerChange"
        @overlay-change="handleOverlayChange"
        @opacity-change="handleOpacityChange"
      />
    </div>

    <!-- Chart dashboard showing breakdowns by category -->
    <chart-dashboard id="charts" :features="filteredFeatures" />
  </div>
</template>

<script setup lang="ts">
/**
 * MappingDashboard Component
 *
 * Main container for the interactive map dashboard with header and charts.
 * Orchestrates map rendering, data filtering, sidebar controls, and statistics.
 *
 * Architecture:
 * - Uses Arquero for multi-dimensional filtering
 * - FilterableMap handles MapLibre GL rendering and layer management
 * - MapSidebar provides filter controls and statistics
 * - DashboardHeader displays fatal/nonfatal counts
 * - ChartDashboard shows breakdown charts
 * - Filtered features flow: store → Arquero → all components
 *
 * @component
 */

import { ref, computed, watch } from "vue";
import { storeToRefs } from "pinia";
import FilterableMap from "@/features/filterableMap/components/FilterableMap.vue";
import MapSidebar from "@/features/filterableMap/components/MapSidebar/MapSidebar.vue";
import AddressSearch from "@/features/filterableMap/components/AddressSearch.vue";
import SearchMarker from "@/features/filterableMap/components/SearchMarker.vue";
import DashboardHeader from "@/pages/components/DashboardHeader.vue";
import ChartDashboard from "@/features/charts/components/ChartDashboard.vue";
import { useArquero } from "@/pages/composables/useArquero";
import { useDownload } from "@/pages/composables/useDownload";
import { useHistograms } from "@/pages/composables/useHistograms";
import { useLoadingState } from "@/pages/composables/useLoadingState";
import { useMapConfig } from "@/features/filterableMap/composables/useMapConfig";
import { useOverlayState } from "@/features/filterableMap/composables/useOverlayState";
import { useUrlState } from "@/pages/composables/useUrlState";
import { useShootingsStore } from "@/shared/stores/shootings";
import type { AddressResult } from "@/features/filterableMap/composables/useGeocoding";
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

// Centralized loading state (includes mapReady check for overlay)
const { showOverlay, hasData: dataReady } = useLoadingState({
  componentReady: mapReady,
});

// Normalize selectedYear to exclude undefined
const normalizedYear = computed(() => selectedYear.value ?? null);

// Map configuration (filters and layers)
const {
  filters,
  layers,
  toggleableLayerNames,
  overlayLayerNames,
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

/**
 * Convert URL layer ID to actual layer name by matching against known layer names.
 * Does case-insensitive matching to handle "pa-senate-districts" → "PA Senate Districts".
 *
 * @param urlId - URL-friendly layer ID (e.g., "pa-senate-districts")
 * @param allLayerNames - Array of all known layer names to match against
 * @returns Matched layer name or null if no match found
 */
function urlIdToLayerName(
  urlId: string,
  allLayerNames: string[],
): string | null {
  // Convert URL ID to comparable format (lowercase, spaces instead of hyphens)
  const urlNormalized = urlId.toLowerCase().replace(/-/g, " ");

  // Find matching layer name (case-insensitive)
  return (
    allLayerNames.find(
      (name) => name.toLowerCase().replace(/\s+/g, " ") === urlNormalized,
    ) ?? null
  );
}

// Overlay state composable for managing layer visibility
const {
  activeLayers,
  currentOverlay,
  initialToggleableLayers,
  handleLayerChange,
  handleOverlayChange,
  resetLayers: resetOverlayState,
} = useOverlayState({
  toggleableLayerNames,
  overlayLayerNames,
  defaultToggledLayerNames,
  urlIdToLayerName,
});

// Map instance refs
const mapRef = ref<any>(null);
const sidebarRef = ref<InstanceType<typeof MapSidebar> | null>(null);
const addressSearchRef = ref<{ clear: () => void } | null>(null);
const mapInstance = computed(() => mapRef.value?.mapInstance ?? null);

// Search marker state for address geocoding
const searchMarkerPosition = ref<{ x: number; y: number } | null>(null);
const searchMarkerLngLat = ref<{ lng: number; lat: number } | null>(null);

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
 * Count fatal shooting victims from filtered features (for a11y summary).
 */
const filteredFatalCount = computed(() => {
  return filteredFeatures.value.filter((f) => f.properties?.fatal === true)
    .length;
});

/**
 * Count nonfatal shooting victims from filtered features (for a11y summary).
 */
const filteredNonfatalCount = computed(() => {
  return filteredFeatures.value.filter((f) => f.properties?.fatal !== true)
    .length;
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

// ============================================================================
// Address Search
// ============================================================================

/**
 * Handle address selection from the AddressSearch component.
 * Flies to the selected location and shows a marker.
 */
function handleAddressSelect(result: AddressResult) {
  if (!mapInstance.value) return;

  const lng = result.lon;
  const lat = result.lat;

  // Fly to the selected address
  mapInstance.value.flyTo({
    center: [lng, lat],
    zoom: 16,
    duration: 1500,
  });

  // Store the lng/lat for marker positioning
  searchMarkerLngLat.value = { lng, lat };

  // Update marker position on map move
  updateMarkerPosition();

  // Clear marker after 10 seconds
  setTimeout(() => {
    searchMarkerPosition.value = null;
    searchMarkerLngLat.value = null;
    // Also clear the search bar
    addressSearchRef.value?.clear();
  }, 10000);
}

/**
 * Handle clearing the address search.
 * Removes the marker from the map.
 */
function handleAddressClear() {
  searchMarkerPosition.value = null;
  searchMarkerLngLat.value = null;
}

/**
 * Update the search marker's screen position based on map projection.
 */
function updateMarkerPosition() {
  if (!mapInstance.value || !searchMarkerLngLat.value) {
    searchMarkerPosition.value = null;
    return;
  }

  const point = mapInstance.value.project([
    searchMarkerLngLat.value.lng,
    searchMarkerLngLat.value.lat,
  ]);
  searchMarkerPosition.value = { x: point.x, y: point.y };
}

// All known layer names for URL parsing
const allLayerNames = computed(() => [
  ...toggleableLayerNames.value,
  ...overlayLayerNames.value,
]);

// Sync state with URL (year, layers, map view)
useUrlState(normalizedYear, activeLayers, mapInstance, allLayerNames.value);

// ============================================================================
// Map Statistics
// ============================================================================

/**
 * Total feature count for current year.
 * Used for statistics display in sidebar.
 */
const totalFeatures = computed(() => {
  const year = selectedYear.value;
  if (year === null || year === undefined) {
    // All years: sum all loaded years
    return Object.values(rowsByYear.value).reduce(
      (sum, rows) => sum + rows.length,
      0,
    );
  }
  return rowsByYear.value[year]?.length ?? 0;
});

/**
 * Generate a text summary of map data for screen readers.
 * Provides key statistics about the displayed shooting data.
 */
const mapSummaryText = computed(() => {
  const total = filteredFeatures.value.length;
  const onMap = pointsOnMap.value;
  const fatal = filteredFatalCount.value;
  const nonfatal = filteredNonfatalCount.value;

  // Build year description
  const yearText =
    normalizedYear.value === null
      ? "all years"
      : `the year ${normalizedYear.value}`;

  // Build active filters description
  const activeFilterCount = activeFilters.value.size;
  const filterText =
    activeFilterCount > 0
      ? ` with ${activeFilterCount} filter${
          activeFilterCount > 1 ? "s" : ""
        } applied`
      : "";

  // Build active layer description
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

/**
 * Number of features with valid coordinates.
 * Used to show missing location note in sidebar.
 */
const pointsOnMap = computed(() => {
  return filteredFeatures.value.filter((f) => {
    const geom = f.geometry;
    if (!geom || geom.type !== "Point") return false;
    const coords = (geom as GeoJSON.Point).coordinates;
    return (
      coords &&
      coords.length >= 2 &&
      typeof coords[0] === "number" &&
      typeof coords[1] === "number" &&
      !isNaN(coords[0]) &&
      !isNaN(coords[1])
    );
  }).length;
});

// Event handlers
/**
 * Handle filter value change from sidebar controls.
 * Applies filter to Arquero table and triggers map update.
 *
 * @param dimensionId - Filter dimension ID
 * @param value - New filter value
 */
function handleFilterChange(dimensionId: string, value: any): void {
  applyFilter(dimensionId, value);
}

/**
 * Handle single filter reset.
 * Clears filter for specified dimension.
 *
 * @param dimensionId - Filter dimension ID to reset
 */
function handleFilterReset(dimensionId: string): void {
  resetFilter(dimensionId);
}

/**
 * Handle reset all filters.
 * Clears all active filters and returns to unfiltered state.
 */
function handleResetAll(): void {
  resetAllFilters();
}

/**
 * Handle map ready event.
 * Called when MapLibre GL map is initialized.
 */
function handleMapReady(): void {
  mapReady.value = true;

  // Add listeners to update search marker position when map moves
  if (mapInstance.value) {
    mapInstance.value.on("move", updateMarkerPosition);
    mapInstance.value.on("zoom", updateMarkerPosition);
  }
}

/**
 * Handle overlay opacity change from sidebar.
 *
 * @param layerName - Overlay layer name
 * @param opacity - Opacity value (0-1, already normalized by MapLayersPanel)
 */
function handleOpacityChange(layerName: string, opacity: number): void {
  const map = mapRef.value?.mapInstance;
  if (map && map.getLayer) {
    // Convert layer name to layer ID (matches FilterableMap's layerNameToId)
    const layerId = layerName.toLowerCase().replace(/\s+/g, "-");
    if (map.getLayer(layerId)) {
      map.setPaintProperty(layerId, "fill-opacity", opacity);
    }
  }
}

// Lifecycle hooks
/**
 * Reset active layers to defaults when year changes.
 * This matches the legacy behavior where changing years resets the layer selection.
 */
watch(selectedYear, () => {
  resetOverlayState();
  // Reset sidebar layer panel UI
  sidebarRef.value?.resetLayers();
  // Hide the legend
  mapRef.value?.hideLegend();
});

/**
 * Initialize Arquero filtering when data loads or year changes.
 * Loads year data on demand, then initializes Arquero.
 */
watch(
  [rowsByYear, selectedYear],
  async ([yearData, year]) => {
    // Ensure the required year(s) are loaded
    const loadStart = performance.now();
    await shootingsStore.ensureYearLoaded(year ?? null);

    // Get the rows for the selected year(s)
    let rowsToUse: ShootingRow[];
    if (year === null || year === undefined) {
      // "All Years" - combine all loaded years
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

      // Initialize Arquero with row data
      initializeArquero(rowsToUse, filters.value);
      // Initialize histograms after Arquero is ready
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
 * Histograms show distribution excluding their own filter.
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
.mapping-dashboard {
  position: relative;
  display: flex;
  margin-bottom: 20px;
  border: 5px solid #868b8e;
}

.map-container {
  flex: 1 1;
  display: flex;
  width: 100%;
  position: relative;
  height: 800px;
}

/* Address search positioned top-left above map controls */
.address-search-container {
  position: absolute;
  top: 10px;
  left: 10px;
  z-index: 10;
}

@media screen and (max-width: 767.98px) {
  .mapping-dashboard {
    flex-direction: column !important;
  }

  .map-container {
    height: 60vh !important;
  }

  .address-search-container {
    left: 5px;
    right: 5px;
    top: 5px;
  }
}
</style>
