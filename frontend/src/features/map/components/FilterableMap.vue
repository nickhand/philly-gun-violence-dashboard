<template>
  <div ref="mapContainer" class="map-wrapper">
    <!-- Map renders here via MapLibre GL -->
    <div v-if="isLoading" class="map-loading">
      <v-progress-circular indeterminate color="primary" />
      <p class="mt-2">Loading map...</p>
    </div>

    <!-- Loading spinner overlay (shows during data loading) -->
    <div class="map-overlay">
      <div class="map-overlay__inner" v-if="showLoadingSpinner">
        <v-progress-circular indeterminate size="32" color="white" />
      </div>
    </div>

    <!-- Map Legend for aggregated layers -->
    <MapLegend ref="mapLegendRef" />
  </div>
</template>

<script setup lang="ts">
/**
 * FilterableMap Component
 *
 * MapLibre GL map wrapper with reactive data source updates.
 * Refactored to use composables for better maintainability.
 *
 * @component
 */

import { ref, watch, toRef } from "vue";
import MapLegend from "./MapLegend.vue";
import { getLayerConfigs } from "../config/layers";
import { SOURCES } from "../config/sources";
import {
  useMapInstance,
  useMapSources,
  useMapLayers,
  useAggregation,
} from "../composables";

// Props
interface Props {
  /** Filtered GeoJSON features to display */
  filteredFeatures: GeoJSON.Feature[];
  /** Active layer names to render */
  activeLayers: string[];
}

const props = defineProps<Props>();

// Emits
const emit = defineEmits<{
  /** Emitted when map is initialized and ready */
  "map-ready": [];
  /** Emitted when loading spinner visibility changes */
  "show-overlay": [value: boolean];
}>();

// Layer configs - use a year value to get proper circle sizes
const layerConfigs = getLayerConfigs(2024);

// Refs
const mapLegendRef = ref<InstanceType<typeof MapLegend> | null>(null);

// Convert props to refs for composables
const filteredFeaturesRef = toRef(props, "filteredFeatures");

// --- Composables ---

// 1. Map instance management
const {
  mapContainer,
  mapInstance,
  isLoading,
  mapLoaded,
  showLoadingSpinner,
  onMapReady,
  showLoader,
  hideLoader,
  setCursor,
} = useMapInstance();

// 2. Aggregation and color scaling
const { applyAggregationColors, legendConfig, hideLegend } =
  useAggregation(filteredFeaturesRef);

// 3. Source management (depends on aggregation)
const {
  hasSource,
  addSourceForLayer,
  addInitialSources,
  updateShootingsSource,
  updateStreetsSource,
  updateBoundarySource,
} = useMapSources(
  mapInstance,
  mapLoaded,
  filteredFeaturesRef,
  applyAggregationColors,
  showLoader,
  hideLoader
);

// 4. Layer management (depends on sources)
const {
  addInitialLayers,
  setActiveLayers: setActiveLayersInternal,
  updateVisibleAggregatedLayers,
  setFilter,
} = useMapLayers(mapInstance, mapLoaded, setCursor);

// --- Loading Spinner ---

// Emit show-overlay event when loading spinner visibility changes
watch(
  showLoadingSpinner,
  (newVal) => {
    emit("show-overlay", newVal);
  },
  { immediate: true }
);

// --- Map Initialization ---

onMapReady(async () => {
  // Add sources and layers
  await addInitialSources(layerConfigs);
  addInitialLayers(layerConfigs);

  // Load initial data if available
  if (props.filteredFeatures.length > 0) {
    updateShootingsSource(props.filteredFeatures);
  }

  // Apply initial active layers from props (e.g., from URL)
  await setActiveLayers(props.activeLayers);

  emit("map-ready");
});

// --- Active Layers Handler ---

/**
 * Set active layers with legend management.
 */
async function setActiveLayers(layerNames: string[]): Promise<void> {
  const anyAggregatedVisible = await setActiveLayersInternal(
    layerNames,
    layerConfigs,
    addSourceForLayer,
    updateStreetsSource,
    updateBoundarySource
  );

  // Show/hide legend based on whether any aggregated layer is visible
  if (anyAggregatedVisible) {
    // Show the legend (legendConfig was already set by applyAggregationColors)
    if (legendConfig.value && mapLegendRef.value) {
      mapLegendRef.value.show(legendConfig.value);
    }
  } else {
    hideLegend();
    mapLegendRef.value?.hide();
  }
}

// --- Watchers ---

/**
 * Watch filtered features and update map sources.
 */
watch(
  () => props.filteredFeatures,
  async (newFeatures) => {
    if (!mapLoaded.value) return;

    // Update shootings source
    updateShootingsSource(newFeatures);

    // Update streets source if it exists
    if (hasSource(SOURCES.STREETS)) {
      const streetsConfig = layerConfigs.find(
        (c) => c.source === SOURCES.STREETS
      );
      if (streetsConfig) {
        await updateStreetsSource(streetsConfig);
      }
    }

    // Update visible aggregated boundary sources
    // Only update layers that are both visible on the map AND in the activeLayers list
    await updateVisibleAggregatedLayers(
      layerConfigs,
      updateBoundarySource,
      props.activeLayers
    );
  },
  { deep: true }
);

/**
 * Watch active layers and update visibility.
 */
watch(
  () => props.activeLayers,
  async (newLayers) => {
    if (!mapLoaded.value) return;
    await setActiveLayers(newLayers);
  }
);

// --- Expose for parent component ---

/**
 * Hide the legend directly on the MapLegend component.
 * This ensures the legend is hidden immediately without relying on watchers.
 */
function hideMapLegend(): void {
  hideLegend(); // Update reactive state
  mapLegendRef.value?.hide(); // Also directly hide the component
}

defineExpose({
  mapContainer,
  mapInstance,
  mapLoaded,
  updateDataSource: updateShootingsSource,
  setActiveLayers,
  setFilter,
  showLoader,
  hideLoader,
  hideLegend: hideMapLegend,
});
</script>

<style scoped>
.map-wrapper {
  width: 100%;
  height: 100%;
  position: relative;
}

.map-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  background-color: #f5f5f5;
}

/* Loading spinner overlay - positioned below nav control (top-right) */
.map-overlay {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  text-align: right;
  padding-top: 100px;
  pointer-events: none;
  z-index: 10;
}

.map-overlay__inner {
  padding: 10px;
  margin-bottom: 10px;
  display: inline-block;
}

/* MapLibre GL styles */
:deep(.maplibregl-map) {
  width: 100%;
  height: 100%;
}

/* Attribution text styling */
:deep(.maplibregl-ctrl-attrib) {
  font-size: 10px;
  background-color: rgba(50, 50, 50, 0.8);
  color: #ffffff;
}

:deep(.maplibregl-ctrl-attrib a) {
  color: #a0cfff;
}

/* Scale control styling */
:deep(.maplibregl-ctrl-scale) {
  background-color: rgba(50, 50, 50, 0.8);
  color: #ffffff;
  border-color: #ffffff;
  font-size: 10px;
}
</style>
