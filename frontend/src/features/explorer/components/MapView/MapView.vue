<template>
  <div
    class="map-view"
    role="region"
    aria-label="Interactive map showing shooting locations in Philadelphia"
  >
    <map-canvas
      v-if="!isE2E"
      ref="mapCanvasRef"
      :filtered-features="filteredFeatures"
      :layer-configs="layerConfigs"
      :active-layers="activeLayers"
      @map-ready="handleMapReady"
    />
    <div v-else class="map-test-placeholder" aria-hidden="true" />

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
</template>

<script setup lang="ts">
/**
 * MapView Component
 *
 * Interactive map visualization combining MapCanvas with address search
 * and search marker overlays. This component handles:
 * - Map rendering via MapCanvas
 * - Address geocoding with fly-to animation
 * - Search marker display and positioning
 *
 * @component
 */

import { ref, computed, onMounted, defineAsyncComponent } from "vue";
import AddressSearch from "./AddressSearch.vue";
import SearchMarker from "./SearchMarker.vue";
import type { AddressResult } from "../../composables/useGeocoding";
import type { LayerConfig } from "../../types";

// Props
interface Props {
  /** Filtered GeoJSON features to display on the map */
  filteredFeatures: GeoJSON.Feature[];
  /** Layer configurations for the map */
  layerConfigs: LayerConfig[];
  /** Active layer names to render */
  activeLayers: string[];
}

const props = defineProps<Props>();
const isE2E = import.meta.env.VITE_E2E;
const loadMapCanvas = () => import("./MapCanvas.vue");
const MapCanvas = defineAsyncComponent(
  loadMapCanvas,
) as (typeof import("./MapCanvas.vue"))["default"];

// Start fetching the map code without making it block initial app startup.
if (!isE2E) {
  void loadMapCanvas();
}

// Emits
const emit = defineEmits<{
  /** Emitted when map is initialized and ready */
  "map-ready": [];
}>();

// Component refs
const mapCanvasRef = ref<InstanceType<typeof MapCanvas> | null>(null);
const addressSearchRef = ref<{ clear: () => void } | null>(null);

// Map instance accessor
const mapInstance = computed(() => mapCanvasRef.value?.mapInstance ?? null);

// Search marker state for address geocoding
const searchMarkerPosition = ref<{ x: number; y: number } | null>(null);
const searchMarkerLngLat = ref<{ lng: number; lat: number } | null>(null);

// ============================================================================
// Event Handlers
// ============================================================================

/**
 * Handle map ready event.
 * Sets up event listeners for marker positioning.
 */
function handleMapReady(): void {
  // Add listeners to update search marker position when map moves
  if (mapInstance.value) {
    mapInstance.value.on("move", updateMarkerPosition);
    mapInstance.value.on("zoom", updateMarkerPosition);
  }

  emit("map-ready");
}

onMounted(() => {
  if (isE2E) {
    emit("map-ready");
  }
});

/**
 * Handle address selection from the AddressSearch component.
 * Flies to the selected location and shows a marker.
 */
function handleAddressSelect(result: AddressResult): void {
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
function handleAddressClear(): void {
  searchMarkerPosition.value = null;
  searchMarkerLngLat.value = null;
}

/**
 * Update the search marker's screen position based on map projection.
 */
function updateMarkerPosition(): void {
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

/**
 * Hide the map legend.
 */
function hideLegend(): void {
  mapCanvasRef.value?.hideLegend();
}

/**
 * Set opacity for a layer.
 */
function setLayerOpacity(layerName: string, opacity: number): void {
  const map = mapCanvasRef.value?.mapInstance;
  if (map && map.getLayer) {
    const layerId = layerName.toLowerCase().replace(/\s+/g, "-");
    if (map.getLayer(layerId)) {
      map.setPaintProperty(layerId, "fill-opacity", opacity);
    }
  }
}

// Expose for parent component
defineExpose({
  mapInstance,
  hideLegend,
  setLayerOpacity,
});
</script>

<style scoped>
.map-view {
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

.map-test-placeholder {
  flex: 1;
  background: #1d2224;
}

@media screen and (max-width: 767.98px) {
  .map-view {
    height: 60vh !important;
  }

  .address-search-container {
    left: 5px;
    right: 5px;
    top: 5px;
  }
}
</style>
