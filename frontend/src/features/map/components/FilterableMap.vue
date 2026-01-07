<template>
  <div ref="mapContainer" class="map-wrapper">
    <!-- Map renders here via MapLibre GL -->
    <div v-if="isLoading" class="map-loading">
      <v-progress-circular indeterminate color="primary" />
      <p class="mt-2">Loading map...</p>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * FilterableMap Component
 *
 * MapLibre GL map wrapper with reactive data source updates.
 * Handles map initialization, source/layer management, and filter application.
 *
 * @component
 */

import { ref, watch, onMounted, onBeforeUnmount } from "vue";
import maplibregl, { type Map as MapLibreMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import mapStyle from "@/data/style.json";

// Props
interface Props {
  /** Filtered GeoJSON features to display */
  filteredFeatures: GeoJSON.Feature[];
  /** Active layer IDs to render */
  activeLayers: string[];
}

const props = defineProps<Props>();

// Emits
const emit = defineEmits<{
  /** Emitted when map is initialized and ready */
  "map-ready": [];
}>();

// Refs
const mapContainer = ref<HTMLDivElement | null>(null);
const mapInstance = ref<MapLibreMap | null>(null);
const isLoading = ref(true);

/**
 * Initialize MapLibre GL map.
 * Creates map instance with Philadelphia center and Carto Positron basemap.
 */
function initializeMap(): void {
  if (!mapContainer.value) return;

  mapInstance.value = new maplibregl.Map({
    container: mapContainer.value,
    style: mapStyle as any,
    center: [-75.1652, 39.9526], // Philadelphia
    zoom: 11,
    minZoom: 9,
    maxZoom: 18,
  });

  // Add navigation controls
  mapInstance.value.addControl(
    new maplibregl.NavigationControl({}),
    "top-right"
  );
  mapInstance.value.addControl(new maplibregl.ScaleControl({}), "bottom-left");

  mapInstance.value.on("load", () => {
    addSources();
    addLayers();
    isLoading.value = false;
    emit("map-ready");
  });
}

/**
 * Add GeoJSON sources to the map.
 * Creates 'shootings' source for filtered features.
 */
function addSources(): void {
  if (!mapInstance.value) return;

  mapInstance.value.addSource("shootings", {
    type: "geojson",
    data: {
      type: "FeatureCollection",
      features: [],
    },
  });
}

/**
 * Add layers to the map.
 * Creates circle layer for shooting points.
 */
function addLayers(): void {
  if (!mapInstance.value) return;

  // Shootings points layer
  mapInstance.value.addLayer({
    id: "shootings-points",
    type: "circle",
    source: "shootings",
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 10, 4, 14, 8],
      "circle-color": [
        "case",
        ["get", "fatal"],
        "#dc2626", // Red for fatal
        "#f59e0b", // Amber for non-fatal
      ],
      "circle-opacity": 0.7,
      "circle-stroke-width": 1,
      "circle-stroke-color": "#ffffff",
    },
  });

  // Add hover effect
  mapInstance.value.on("mouseenter", "shootings-points", () => {
    if (mapInstance.value) {
      mapInstance.value.getCanvas().style.cursor = "pointer";
    }
  });

  mapInstance.value.on("mouseleave", "shootings-points", () => {
    if (mapInstance.value) {
      mapInstance.value.getCanvas().style.cursor = "";
    }
  });
}

/**
 * Update GeoJSON data source with filtered features.
 * Called when filteredFeatures prop changes.
 *
 * @param features - New GeoJSON features to display
 */
function updateDataSource(features: GeoJSON.Feature[]): void {
  if (!mapInstance.value) return;

  const source = mapInstance.value.getSource(
    "shootings"
  ) as maplibregl.GeoJSONSource;
  if (source) {
    source.setData({
      type: "FeatureCollection",
      features,
    });
  }
}

/**
 * Set active layers to display.
 * Shows/hides layers based on activeLayers prop.
 *
 * @param layerIds - Array of layer IDs to show (others hidden)
 */
function setActiveLayers(layerIds: string[]): void {
  if (!mapInstance.value) return;

  const allLayerIds = ["shootings-points"];
  allLayerIds.forEach((id) => {
    const visibility = layerIds.includes(id) ? "visible" : "none";
    mapInstance.value?.setLayoutProperty(id, "visibility", visibility);
  });
}

/**
 * Apply filter expression to a layer.
 * Uses MapLibre GL filter expressions to filter rendered features.
 *
 * @param layerId - Layer ID to filter
 * @param filter - MapLibre GL filter expression or null to clear
 */
function setFilter(layerId: string, filter: any[] | null): void {
  if (!mapInstance.value) return;

  mapInstance.value.setFilter(layerId, filter as any);
}

// Watchers
/**
 * Watch filtered features and update map source.
 * Triggers map re-render when data changes.
 */
watch(
  () => props.filteredFeatures,
  (newFeatures) => {
    updateDataSource(newFeatures);
  },
  { deep: true }
);

/**
 * Watch active layers and update visibility.
 * Shows/hides layers when selection changes.
 */
watch(
  () => props.activeLayers,
  (newLayers) => {
    setActiveLayers(newLayers);
  }
);

// Lifecycle hooks
/**
 * Initialize map on mount.
 * Sets up MapLibre GL instance and event listeners.
 */
onMounted(() => {
  initializeMap();
});

/**
 * Clean up map on unmount.
 * Removes map instance to prevent memory leaks.
 */
onBeforeUnmount(() => {
  if (mapInstance.value) {
    mapInstance.value.remove();
    mapInstance.value = null;
  }
});

// Expose methods for parent component access
defineExpose({
  mapInstance,
  updateDataSource,
  setActiveLayers,
  setFilter,
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

/* MapLibre GL styles will be applied here */
:deep(.maplibregl-map) {
  width: 100%;
  height: 100%;
}

:deep(.maplibregl-ctrl-attrib) {
  font-size: 10px;
  background-color: rgba(255, 255, 255, 0.8);
}
</style>
