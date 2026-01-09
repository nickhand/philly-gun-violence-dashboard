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
      ref="sidebarRef"
      :filters="filters"
      :active-filters="activeFilters"
      :feature-count="filteredFeatures.length"
      :total-count="totalFeatures"
      :points-on-map="pointsOnMap"
      :toggleable-layer-names="toggleableLayerNames"
      :overlay-layer-names="overlayLayerNames"
      :default-toggled-layer-names="defaultToggledLayerNames"
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
 * - Uses crossfilter for multi-dimensional filtering
 * - FilterableMap handles MapLibre GL rendering and layer management
 * - MapSidebar provides filter controls and statistics
 * - Filtered features flow: data → crossfilter → map/sidebar
 *
 * @component
 */

import { ref, computed, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute } from "vue-router";
import FilterableMap from "./FilterableMap.vue";
import MapSidebar from "./MapSidebar.vue";
import { useCrossfilter } from "../composables/useCrossfilter";
import { useMapConfig } from "../composables/useMapConfig";
import { useUrlState } from "../composables/useUrlState";
import { useShootingsStore } from "@/shared/stores/shootings";

// Access route for URL query params
const route = useRoute();

// Store access
const shootingsStore = useShootingsStore();
const { currentData, selectedYear } = storeToRefs(shootingsStore);

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

// Crossfilter composable for filtering
const {
  activeFilters,
  initializeCrossfilter,
  applyFilter,
  resetFilter,
  resetAllFilters,
  getAllFiltered,
} = useCrossfilter();

/**
 * Parse initial layers from URL query parameter.
 * Converts URL IDs (e.g., "point-locations") to layer names (e.g., "Point locations").
 */
function getInitialLayersFromUrl(): string[] {
  const layersParam = route.query.layers;
  if (layersParam && typeof layersParam === "string") {
    const layers = layersParam
      .split(",")
      .map((id) => id.trim())
      .filter(Boolean)
      .map((id) => {
        // Convert URL ID to layer name (e.g., "point-locations" → "Point locations")
        const withSpaces = id.replace(/-/g, " ");
        return withSpaces.charAt(0).toUpperCase() + withSpaces.slice(1);
      });
    if (layers.length > 0) {
      return layers;
    }
  }
  // Default to Point locations if no URL param
  return ["Point locations"];
}

// Active layers (names of layers to display on the map)
// Initialize from URL query param or default to Point locations
const activeLayers = ref<string[]>(getInitialLayersFromUrl());

// Map instance ref for URL state sync
const mapRef = ref<any>(null);
const sidebarRef = ref<InstanceType<typeof MapSidebar> | null>(null);
const mapInstance = computed(() => mapRef.value?.mapInstance ?? null);

// Sync state with URL (year, layers, map view)
useUrlState(normalizedYear, activeLayers, mapInstance);

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
function handleDownload(format: string): void {
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
  // Map is ready - no action needed currently
}

/**
 * Handle layer visibility change from sidebar.
 * Toggles layer visibility on the map.
 *
 * @param layerName - Layer name to toggle
 * @param visible - Whether layer should be visible
 */
function handleLayerChange(layerName: string, visible: boolean): void {
  if (visible) {
    if (!activeLayers.value.includes(layerName)) {
      activeLayers.value = [...activeLayers.value, layerName];
    }
  } else {
    activeLayers.value = activeLayers.value.filter((l) => l !== layerName);
  }
}

// Track currently selected overlay layer
const currentOverlay = ref<string | null>(null);

// Track saved toggleable layers (to restore when overlay is cleared)
const savedToggleableLayers = ref<string[]>([]);

/**
 * Handle overlay layer change from sidebar.
 * Shows/hides choropleth overlay layers.
 * Only one overlay can be visible at a time.
 * When an overlay is selected, toggleable layers are hidden and saved.
 * When overlay is cleared, toggleable layers are restored.
 *
 * @param layerName - Overlay layer name or null to clear
 */
function handleOverlayChange(layerName: string | null): void {
  // Remove current overlay from active layers (if any)
  if (currentOverlay.value) {
    activeLayers.value = activeLayers.value.filter(
      (l) => l !== currentOverlay.value
    );
  }

  if (layerName) {
    // Selecting an overlay - save current toggleable layers and remove them
    const currentToggleable = activeLayers.value.filter((l) =>
      toggleableLayerNames.value.includes(l)
    );
    if (currentToggleable.length > 0) {
      savedToggleableLayers.value = currentToggleable;
    }
    // Remove toggleable layers, add overlay
    activeLayers.value = [layerName];
  } else {
    // Clearing overlay - restore saved toggleable layers
    if (savedToggleableLayers.value.length > 0) {
      activeLayers.value = [...savedToggleableLayers.value];
      savedToggleableLayers.value = [];
    } else {
      // Fallback to defaults if nothing was saved
      activeLayers.value = [...defaultToggledLayerNames.value];
    }
  }

  // Update current overlay
  currentOverlay.value = layerName;
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
 * Reset active layers to defaults when year changes.
 * This matches the legacy behavior where changing years resets the layer selection.
 */
watch(selectedYear, () => {
  activeLayers.value = [...defaultToggledLayerNames.value];
  // Also clear any overlay selection
  currentOverlay.value = null;
  // Reset sidebar layer panel UI
  sidebarRef.value?.resetLayers();
  // Hide the legend
  mapRef.value?.hideLegend();
});

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
