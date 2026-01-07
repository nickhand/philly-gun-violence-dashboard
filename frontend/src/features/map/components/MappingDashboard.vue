<template>
  <div class="mapping-dashboard">
    <!-- Map container with sidebar -->
    <div class="map-container">
      <FilterableMap
        ref="mapRef"
        :filtered-features="filteredFeatures"
        :layer-configs="layers"
        :active-layers="activeLayers"
        @map-ready="handleMapReady"
      />
    </div>

    <!-- Sidebar with filters -->
    <MapSidebar
      :filters="filters"
      :active-filters="activeFilters"
      :feature-count="filteredFeatures.length"
      :total-count="totalFeatures"
      @filter-change="handleFilterChange"
      @filter-reset="handleFilterReset"
      @reset-all="handleResetAll"
      @download="handleDownload"
    />
  </div>
</template>

<script setup lang="ts">
/**
 * MappingDashboard Component
 *
 * Main container for the interactive map dashboard.
 * Orchestrates map rendering, data filtering, and sidebar controls.
 *
 * Architecture:
 * - Uses crossfilter for multi-dimensional filtering
 * - FilterableMap handles MapLibre GL rendering and layer management
 * - MapSidebar provides filter controls and statistics
 * - Filtered features flow: data → crossfilter → map/sidebar
 *
 * @component
 */

import { ref, computed, onMounted, watch } from "vue";
import { storeToRefs } from "pinia";
import FilterableMap from "./FilterableMap.vue";
import MapSidebar from "./MapSidebar.vue";
import { useCrossfilter } from "../composables/useCrossfilter";
import { useMapConfig } from "../composables/useMapConfig";
import { useUrlState } from "../composables/useUrlState";
import { useShootingsStore } from "@/shared/stores/shootings";

// Store access
const shootingsStore = useShootingsStore();
const { currentData, selectedYear } = storeToRefs(shootingsStore);

// Normalize selectedYear to exclude undefined
const normalizedYear = computed(() => selectedYear.value ?? null);

// Map configuration (filters and layers)
const { filters, layers } = useMapConfig(normalizedYear);

// Crossfilter composable for filtering
const {
  activeFilters,
  initializeCrossfilter,
  applyFilter,
  resetFilter,
  resetAllFilters,
  getAllFiltered,
} = useCrossfilter();

// Active layers (names of layers to display on the map)
// TODO: Make this user-controllable via layer toggle UI
const activeLayers = ref<string[]>(["Point locations"]);

// Map instance ref for URL state sync
const mapRef = ref<any>(null);
const mapInstance = computed(() => mapRef.value?.mapInstance ?? null);

// Sync state with URL (year, layers, map view)
useUrlState(selectedYear, activeLayers, mapInstance);

// Computed properties
/**
 * Filtered GeoJSON features from crossfilter.
 * Updates reactively when filters change.
 */
const filteredFeatures = computed(() => getAllFiltered());

/**
 * Total feature count (unfiltered).
 * Used for statistics display in sidebar.
 */
const totalFeatures = computed(() => currentData.value?.features.length ?? 0);

// Event handlers
/**
 * Handle filter value change from sidebar controls.
 * Applies filter to crossfilter and triggers map update.
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
 * Handle data download request.
 * Exports filtered features in requested format.
 *
 * @param format - Export format ('geojson' | 'csv' | 'json')
 */
function handleDownload(format: "geojson" | "csv" | "json"): void {
  const features = filteredFeatures.value;

  if (format === "geojson") {
    const geojson = {
      type: "FeatureCollection",
      features,
    };
    const blob = new Blob([JSON.stringify(geojson, null, 2)], {
      type: "application/json",
    });
    downloadBlob(blob, "shootings-filtered.geojson");
  } else if (format === "csv") {
    // TODO: Implement CSV conversion
    console.warn("CSV export not yet implemented");
  } else if (format === "json") {
    const json = features.map((f) => f.properties);
    const blob = new Blob([JSON.stringify(json, null, 2)], {
      type: "application/json",
    });
    downloadBlob(blob, "shootings-filtered.json");
  }
}

/**
 * Handle map ready event.
 * Called when MapLibre GL map is initialized.
 */
function handleMapReady(): void {
  console.log("Map initialized and ready");
}

/**
 * Download blob as file.
 * Creates temporary anchor element and triggers download.
 *
 * @param blob - Data blob to download
 * @param filename - Output filename
 */
function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// Lifecycle hooks
/**
 * Initialize crossfilter when data loads.
 * Watches currentData from store and reinitializes on change.
 */
watch(
  currentData,
  (newData) => {
    if (newData && newData.features.length > 0) {
      initializeCrossfilter(
        newData.features as any as GeoJSON.Feature[],
        filters.value
      );
    }
  },
  { immediate: true }
);

/**
 * Fetch shootings data on mount.
 * Loads initial dataset from API using the selected year from the store.
 */
onMounted(async () => {
  if (!currentData.value || currentData.value.features.length === 0) {
    await shootingsStore.fetchShootingsData(selectedYear.value);
  }
});
</script>

<style scoped>
.mapping-dashboard {
  position: relative;
  display: flex;
  margin-top: 100px;
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

@media screen and (max-width: 767.98px) {
  .mapping-dashboard {
    flex-direction: column !important;
  }

  .map-container {
    height: 60vh !important;
  }
}
</style>
