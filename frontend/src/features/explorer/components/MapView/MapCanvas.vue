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
 * MapCanvas Component
 *
 * MapLibre GL map wrapper with reactive data source updates.
 * This is the core map rendering component used by MapExplorer.
 *
 * @component
 */

import { ref, watch, toRef, onMounted } from "vue";
import MapLegend from "./MapLegend.vue";
import { SOURCES } from "../../config/sources";
import { injectTooltipStyles } from "../../config/tooltips";
import {
  useMapInstance,
  useMapSources,
  useMapLayers,
  useMapTooltips,
  useAggregation,
} from "../../composables";
import type { LayerConfig } from "../../types";

// Props
interface Props {
  /** Filtered GeoJSON features to display */
  filteredFeatures: GeoJSON.Feature[];
  /** Layer configurations (reactive, changes with year) */
  layerConfigs: LayerConfig[];
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

// Convert props to refs for composables
const filteredFeaturesRef = toRef(props, "filteredFeatures");

// Refs
const mapLegendRef = ref<InstanceType<typeof MapLegend> | null>(null);

// Inject tooltip styles on mount
onMounted(() => {
  injectTooltipStyles();
});

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

// 3. Tooltip management
const { addTooltip } = useMapTooltips(mapInstance, setCursor);

// 4. Source management (depends on aggregation)
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
  hideLoader,
);

// 5. Layer management (depends on sources)
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
  { immediate: true },
);

// --- Map Initialization ---

onMapReady(async () => {
  // Add sources and layers
  await addInitialSources(props.layerConfigs);
  addInitialLayers(props.layerConfigs);

  // Add tooltips for layers that have tooltip config
  for (const config of props.layerConfigs) {
    if (config.tooltip) {
      addTooltip(config.name, config.tooltip);
    }
  }

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
    props.layerConfigs,
    addSourceForLayer,
    updateStreetsSource,
    updateBoundarySource,
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
      const streetsConfig = props.layerConfigs.find(
        (c) => c.source === SOURCES.STREETS,
      );
      if (streetsConfig) {
        await updateStreetsSource(streetsConfig);
        // Show legend if this is an aggregated layer that's active
        if (
          streetsConfig.aggregated &&
          props.activeLayers.includes(streetsConfig.name)
        ) {
          if (legendConfig.value && mapLegendRef.value) {
            mapLegendRef.value.show(legendConfig.value);
          }
        }
      }
    }

    // Update visible aggregated boundary sources
    // Only update layers that are both visible on the map AND in the activeLayers list
    await updateVisibleAggregatedLayers(
      props.layerConfigs,
      updateBoundarySource,
      props.activeLayers,
    );

    // Show legend if any aggregated boundary layer is active and legendConfig is set
    const hasActiveAggregatedBoundary = props.layerConfigs.some(
      (c) =>
        c.aggregated &&
        c.source !== SOURCES.STREETS &&
        props.activeLayers.includes(c.name),
    );
    if (
      hasActiveAggregatedBoundary &&
      legendConfig.value &&
      mapLegendRef.value
    ) {
      mapLegendRef.value.show(legendConfig.value);
    }
  },
  { deep: true },
);

/**
 * Watch active layers and update visibility.
 */
watch(
  () => props.activeLayers,
  async (newLayers) => {
    if (!mapLoaded.value) return;
    await setActiveLayers(newLayers);
  },
);

/**
 * Watch layer configs for circle radius changes (year changes).
 * Updates the Point locations layer paint property when selectedYear changes.
 */
watch(
  () => props.layerConfigs,
  (newConfigs) => {
    if (!mapLoaded.value || !mapInstance.value) {
      return;
    }

    // Find the Point locations layer config
    const pointsConfig = newConfigs.find((c) => c.name === "Point locations");
    const paint = pointsConfig?.paint as Record<string, unknown> | undefined;
    if (paint?.["circle-radius"]) {
      const map = mapInstance.value;
      // Layer ID is lowercase with hyphens (layerNameToId transforms "Point locations" → "point-locations")
      const layerId = "point-locations";
      if (map.getLayer(layerId)) {
        map.setPaintProperty(
          layerId,
          "circle-radius",
          paint["circle-radius"] as any,
        );
      }
    }
  },
  { deep: true },
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
  padding-top: 140px;
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

/* On mobile, start attribution collapsed (compact mode) */
@media screen and (max-width: 767.98px) {
  :deep(.maplibregl-ctrl-attrib.maplibregl-compact) {
    min-height: 20px;
    padding: 0;
    background-color: rgba(50, 50, 50, 0.8);
    border-radius: 4px;
  }

  :deep(
    .maplibregl-ctrl-attrib.maplibregl-compact:not(.maplibregl-compact-show)
      .maplibregl-ctrl-attrib-inner
  ) {
    display: none;
  }

  :deep(
    .maplibregl-ctrl-attrib.maplibregl-compact .maplibregl-ctrl-attrib-button
  ) {
    display: block;
  }
}

/* Scale control styling */
:deep(.maplibregl-ctrl-scale) {
  background-color: rgba(50, 50, 50, 0.8);
  color: #ffffff;
  border-color: #ffffff;
  font-size: 10px;
}

/* Home button styling - matches MapLibre nav controls */
:deep(.maplibregl-ctrl-home) {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 29px;
  height: 29px;
  padding: 0;
  border: none;
  border-radius: 4px;
  background: #fff;
  cursor: pointer;
  color: #333;
}

:deep(.maplibregl-ctrl-home:hover) {
  background: #f0f0f0;
}

:deep(.maplibregl-ctrl-home:focus) {
  outline: 2px solid #1e88e5;
  outline-offset: -2px;
}

:deep(.maplibregl-ctrl-home svg) {
  display: block;
}
</style>
