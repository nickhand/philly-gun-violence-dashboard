<template>
  <div class="mapping-dashboard">
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
      <FilterableMap
        ref="mapRef"
        :filtered-features="filteredFeatures"
        :layer-configs="layers"
        :active-layers="activeLayers"
        @map-ready="handleMapReady"
      />

      <!-- Address search overlay -->
      <div class="address-search-container">
        <AddressSearch
          ref="addressSearchRef"
          @select="handleAddressSelect"
          @clear="handleAddressClear"
        />
      </div>

      <!-- Search marker (shows when address is selected) -->
      <div
        v-if="searchMarkerPosition"
        class="search-marker"
        :style="searchMarkerStyle"
        aria-label="Searched location marker"
      >
        <div class="marker-pin">
          <!-- Crosshair/target marker matching theme -->
          <svg viewBox="0 0 48 48" width="32" height="32">
            <!-- Outer ring with glow -->
            <circle
              cx="24"
              cy="24"
              r="18"
              fill="none"
              stroke="#7ab5e5"
              stroke-width="2"
              opacity="0.4"
            />
            <!-- Inner ring -->
            <circle
              cx="24"
              cy="24"
              r="12"
              fill="none"
              stroke="#7ab5e5"
              stroke-width="2.5"
            />
            <!-- Center dot -->
            <circle cx="24" cy="24" r="4" fill="#7ab5e5" />
            <!-- Crosshairs -->
            <line
              x1="24"
              y1="6"
              x2="24"
              y2="12"
              stroke="#7ab5e5"
              stroke-width="2"
              stroke-linecap="round"
            />
            <line
              x1="24"
              y1="36"
              x2="24"
              y2="42"
              stroke="#7ab5e5"
              stroke-width="2"
              stroke-linecap="round"
            />
            <line
              x1="6"
              y1="24"
              x2="12"
              y2="24"
              stroke="#7ab5e5"
              stroke-width="2"
              stroke-linecap="round"
            />
            <line
              x1="36"
              y1="24"
              x2="42"
              y2="24"
              stroke="#7ab5e5"
              stroke-width="2"
              stroke-linecap="round"
            />
          </svg>
        </div>
      </div>
    </div>

    <!-- Sidebar with filters -->
    <MapSidebar
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
</template>

<script setup lang="ts">
/**
 * MappingDashboard Component
 *
 * Main container for the interactive map dashboard.
 * Orchestrates map rendering, data filtering, and sidebar controls.
 *
 * Architecture:
 * - Uses Arquero for multi-dimensional filtering
 * - FilterableMap handles MapLibre GL rendering and layer management
 * - MapSidebar provides filter controls and statistics
 * - Filtered features flow: data → Arquero → map/sidebar
 *
 * @component
 */

import { ref, computed, watch } from "vue";
import { storeToRefs } from "pinia";
import FilterableMap from "./FilterableMap.vue";
import MapSidebar from "./MapSidebar/MapSidebar.vue";
import AddressSearch from "./AddressSearch.vue";
import { useArquero } from "../composables/useArquero";
import { useDownload } from "../composables/useDownload";
import { useHistograms } from "../composables/useHistograms";
import { useMapConfig } from "../composables/useMapConfig";
import { useOverlayState } from "../composables/useOverlayState";
import { useUrlState } from "../composables/useUrlState";
import { useShootingsDataStore } from "@/shared/stores/shootingsData";
import type { AddressResult } from "../composables/useGeocoding";
import type { ShootingRow } from "@/shared/types/shootings";

// Types
interface Feature {
  type: "Feature";
  properties: Record<string, unknown> | null;
  geometry: GeoJSON.Geometry | null;
}

// Emit events to parent
const emit = defineEmits<{
  "map-ready": [];
  "filtered-features": [features: Feature[]];
}>();

// Store access - using new Arquero-based data store
const shootingsStore = useShootingsDataStore();
const { rows, selectedYear } = storeToRefs(shootingsStore);

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
  allLayerNames: string[]
): string | null {
  // Convert URL ID to comparable format (lowercase, spaces instead of hyphens)
  const urlNormalized = urlId.toLowerCase().replace(/-/g, " ");

  // Find matching layer name (case-insensitive)
  return (
    allLayerNames.find(
      (name) => name.toLowerCase().replace(/\s+/g, " ") === urlNormalized
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

// Map instance ref for URL state sync
const mapRef = ref<any>(null);
const sidebarRef = ref<InstanceType<typeof MapSidebar> | null>(null);
const addressSearchRef = ref<{ clear: () => void } | null>(null);
const mapInstance = computed(() => mapRef.value?.mapInstance ?? null);

// Search marker state for address geocoding
const searchMarkerPosition = ref<{ x: number; y: number } | null>(null);
const searchMarkerLngLat = ref<{ lng: number; lat: number } | null>(null);

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

// Computed style for marker positioning (center the 32x32 crosshair on the point)
const searchMarkerStyle = computed(() => {
  if (!searchMarkerPosition.value) return {};
  return {
    transform: `translate(${searchMarkerPosition.value.x - 16}px, ${
      searchMarkerPosition.value.y - 16
    }px)`,
  };
});

// All known layer names for URL parsing
const allLayerNames = computed(() => [
  ...toggleableLayerNames.value,
  ...overlayLayerNames.value,
]);

// Sync state with URL (year, layers, map view)
useUrlState(normalizedYear, activeLayers, mapInstance, allLayerNames.value);

// Note: filteredFeatures is now a computed ref from useArquero, not a local computed

/**
 * Total feature count (unfiltered).
 * Used for statistics display in sidebar.
 */
const totalFeatures = computed(() => rows.value?.length ?? 0);

/**
 * Generate a text summary of map data for screen readers.
 * Provides key statistics about the displayed shooting data.
 */
const mapSummaryText = computed(() => {
  const total = filteredFeatures.value.length;
  const onMap = pointsOnMap.value;
  const fatal = filteredFeatures.value.filter(
    (f) => f.properties?.fatal === true
  ).length;
  const nonfatal = total - fatal;

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
 * Bubbles event up to parent for overlay control.
 */
function handleMapReady(): void {
  emit("map-ready");

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
 * Filters rows by selected year before initializing Arquero.
 */
watch(
  [rows, selectedYear],
  ([newRows, year]) => {
    if (newRows && newRows.length > 0) {
      const startTime = performance.now();

      // Filter rows by selected year (null = all years)
      const filterStart = performance.now();
      const filteredRows =
        year === null || year === undefined
          ? newRows
          : newRows.filter((r) => r.year === year);

      if (import.meta.env.DEV) {
        console.log(
          `[MappingDashboard] Filtered to ${filteredRows.length} rows (year=${year ?? "all"}) in ${(performance.now() - filterStart).toFixed(1)}ms`
        );
      }

      // Initialize Arquero with filtered row data
      initializeArquero(filteredRows as ShootingRow[], filters.value);
      // Initialize histograms after Arquero is ready
      initializeHistograms(filters.value, getHistogramData);

      if (import.meta.env.DEV) {
        console.log(
          `[MappingDashboard] Total data initialization in ${(performance.now() - startTime).toFixed(1)}ms`
        );
      }
    }
  },
  { immediate: true }
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
  { deep: true }
);

/**
 * Emit filtered features to parent for chart dashboard.
 * Triggered whenever the filtered features change.
 */
watch(
  filteredFeatures,
  (features) => {
    emit("filtered-features", features as Feature[]);
  },
  { immediate: true }
);
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

/* Address search positioned top-left above map controls */
.address-search-container {
  position: absolute;
  top: 10px;
  left: 10px;
  z-index: 10;
}

/* Search marker crosshair */
.search-marker {
  position: absolute;
  top: 0;
  left: 0;
  z-index: 5;
  pointer-events: none;
  filter: drop-shadow(0 0 8px rgba(122, 181, 229, 0.6));
}

.marker-pin {
  animation: pulse-in 0.4s ease-out forwards;
}

@keyframes pulse-in {
  0% {
    transform: scale(0.3);
    opacity: 0;
  }
  60% {
    transform: scale(1.1);
    opacity: 1;
  }
  100% {
    transform: scale(1);
    opacity: 1;
  }
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
