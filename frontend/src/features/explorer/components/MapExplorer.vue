<template>
  <div class="map-explorer">
    <!-- Map view with address search -->
    <map-view
      ref="mapViewRef"
      :filtered-features="filteredFeatures"
      :layer-configs="layerConfigs"
      :active-layers="activeLayers"
      @map-ready="handleMapReady"
    />

    <!-- Sidebar with filters -->
    <map-sidebar
      id="filters"
      ref="sidebarRef"
      :filters="filters"
      :active-filters="activeFilters"
      :slider-limits="sliderLimits"
      :feature-count="filteredCount"
      :total-count="totalCount"
      :points-on-map="pointsOnMap"
      :toggleable-layer-names="toggleableLayerNames"
      :choropleth-layer-names="choroplethLayerNames"
      :default-toggled-layer-names="defaultToggledLayerNames"
      :initial-active-layers="initialToggleableLayers"
      :selected-choropleth="selectedChoropleth"
      :histograms="histograms"
      @filter-change="
        (dimensionId, value) => $emit('filter-change', dimensionId, value)
      "
      @filter-reset="$emit('filter-reset', $event)"
      @reset-all="$emit('reset-all')"
      @download="$emit('download', $event)"
      @layer-change="handleLayerChange"
      @choropleth-change="handleChoroplethChange"
      @opacity-change="handleOpacityChange"
    />
  </div>
</template>

<script setup lang="ts">
/**
 * MapExplorer Component
 *
 * A self-contained interactive map with filtering sidebar.
 * Composes MapView and MapSidebar into a cohesive exploration interface.
 *
 * This component owns all layer visibility state:
 * - Uses useLayerState composable for layer management
 * - Parses initial layers from URL query params
 * - Handles toggle/aggregation layer interactions (save/restore)
 * - Exposes activeLayers for URL syncing by parent
 *
 * The parent component is responsible for:
 * - Data loading and Arquero filtering logic
 * - Providing filtered features and filter state
 * - Handling filter change events
 *
 * @component
 */

import { ref, computed } from "vue";
import type { ComputedRef } from "vue";
import MapView from "./MapView/MapView.vue";
import MapSidebar from "./MapSidebar/MapSidebar.vue";
import { useLayerState } from "../composables/useLayerState";
import type { FilterConfig, LayerConfig, HistogramBin } from "../types";

// Props
interface Props {
  /** Filtered GeoJSON features to display on the map */
  filteredFeatures: GeoJSON.Feature[];
  /** Filtered record count, including records without map coordinates */
  filteredCount: number;
  /** Layer configurations for the map */
  layerConfigs: LayerConfig[];
  /** Filter configurations for the sidebar */
  filters: FilterConfig[];
  /** Currently active filters (Map of dimension ID → filter value) */
  activeFilters: Map<string, any>;
  /** Slider limits computed from data */
  sliderLimits: Map<string, [number, number]>;
  /** Total feature count (before filtering) */
  totalCount: number;
  /** Layer names that can be toggled on/off */
  toggleableLayerNames: string[];
  /** Layer names available as choropleth layers */
  choroplethLayerNames: string[];
  /** Layer names toggled on by default */
  defaultToggledLayerNames: string[];
  /** Histogram data for slider filters */
  histograms?: Map<string, HistogramBin[]>;
}

const props = defineProps<Props>();

// Emits
const emit = defineEmits<{
  /** Emitted when map is initialized and ready */
  "map-ready": [];
  /** Emitted when a filter value changes */
  "filter-change": [dimensionId: string, value: any];
  /** Emitted when a single filter is reset */
  "filter-reset": [dimensionId: string];
  /** Emitted when all filters are reset */
  "reset-all": [];
  /** Emitted when download is requested */
  download: [options: any];
}>();

// Component refs
const mapViewRef = ref<InstanceType<typeof MapView> | null>(null);
const sidebarRef = ref<InstanceType<typeof MapSidebar> | null>(null);

// Map instance accessor
const mapInstance = computed(() => mapViewRef.value?.mapInstance ?? null);

// ============================================================================
// Layer State Management (via useLayerState)
// ============================================================================

/**
 * Convert URL layer ID to actual layer name by matching against known layer names.
 * Does case-insensitive matching to handle "pa-senate-districts" → "PA Senate Districts".
 */
function urlIdToLayerName(
  urlId: string,
  allLayerNames: string[],
): string | null {
  const urlNormalized = urlId.toLowerCase().replace(/-/g, " ");
  return (
    allLayerNames.find(
      (name) => name.toLowerCase().replace(/\s+/g, " ") === urlNormalized,
    ) ?? null
  );
}

// Wrap props in computed refs for useLayerState
const toggleableLayerNamesRef = computed(() => props.toggleableLayerNames);
const choroplethLayerNamesRef = computed(() => props.choroplethLayerNames);
const defaultToggledLayerNamesRef = computed(
  () => props.defaultToggledLayerNames,
);

// Layer state management composable
const {
  activeLayers,
  selectedChoropleth,
  initialToggleableLayers,
  handleLayerChange,
  handleChoroplethChange,
  resetLayers: resetLayerState,
} = useLayerState({
  toggleableLayerNames: toggleableLayerNamesRef as ComputedRef<string[]>,
  choroplethLayerNames: choroplethLayerNamesRef as ComputedRef<string[]>,
  defaultToggledLayerNames: defaultToggledLayerNamesRef as ComputedRef<
    string[]
  >,
  urlIdToLayerName,
});

// ============================================================================
// Computed Properties
// ============================================================================

/**
 * Number of features with valid coordinates.
 * Used to show missing location note in sidebar.
 */
const pointsOnMap = computed(() => {
  return props.filteredFeatures.filter((f) => {
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

// ============================================================================
// Event Handlers
// ============================================================================

/**
 * Handle map ready event.
 * Called when MapView signals the map is initialized.
 */
function handleMapReady(): void {
  emit("map-ready");
}

/**
 * Handle aggregation layer opacity change from sidebar.
 */
function handleOpacityChange(layerName: string, opacity: number): void {
  mapViewRef.value?.setLayerOpacity(layerName, opacity);
}

// ============================================================================
// Public Methods (exposed to parent)
// ============================================================================

/**
 * Reset layers to default state.
 * Called when year changes to reset layer selection.
 */
function resetLayers(): void {
  resetLayerState();
  sidebarRef.value?.resetLayers();
  mapViewRef.value?.hideLegend();
}

/**
 * Hide the map legend.
 */
function hideLegend(): void {
  mapViewRef.value?.hideLegend();
}

// Expose for parent component
defineExpose({
  mapInstance,
  activeLayers,
  pointsOnMap,
  resetLayers,
  hideLegend,
});
</script>

<style scoped>
.map-explorer {
  position: relative;
  display: flex;
  border: 5px solid #868b8e;
}

@media screen and (max-width: 767.98px) {
  .map-explorer {
    flex-direction: column !important;
  }
}
</style>
