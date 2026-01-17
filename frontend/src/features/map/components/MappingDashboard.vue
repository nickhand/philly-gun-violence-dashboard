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

import { ref, computed, watch, onMounted } from "vue";
import { storeToRefs } from "pinia";
import { useRoute } from "vue-router";
import FilterableMap from "./FilterableMap.vue";
import MapSidebar from "./MapSidebar/MapSidebar.vue";
import AddressSearch from "./AddressSearch.vue";
import { useArquero } from "../composables/useArquero";
import { useHistograms } from "../composables/useHistograms";
import { useMapConfig } from "../composables/useMapConfig";
import { useUrlState } from "../composables/useUrlState";
import { useShootingsDataStore } from "@/shared/stores/shootingsData";
import { useBoundariesStore } from "@/shared/stores/boundaries";
import { sourceIdToDataset } from "../config/sources";
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

// Access route for URL query params
const route = useRoute();

// Store access - using new Arquero-based data store
const shootingsStore = useShootingsDataStore();
const boundariesStore = useBoundariesStore();
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

// Load data on mount
onMounted(async () => {
  await shootingsStore.loadDatasetIfNeeded();
});

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

/**
 * Parse initial layers from URL query parameter.
 * Converts URL IDs (e.g., "point-locations") to layer names (e.g., "Point locations").
 */
function getInitialLayersFromUrl(): string[] {
  const layersParam = route.query.layers;

  if (layersParam && typeof layersParam === "string") {
    // Get all known layer names (toggleable + overlay)
    const allLayerNames = [
      ...toggleableLayerNames.value,
      ...overlayLayerNames.value,
    ];

    const layers = layersParam
      .split(",")
      .map((id) => id.trim())
      .filter(Boolean)
      .map((id) => urlIdToLayerName(id, allLayerNames))
      .filter((name): name is string => name !== null);

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
 * Handle data download request.
 * Exports features in requested format based on dialog options.
 *
 * @param options - Download options from dialog
 */
async function handleDownload(options: {
  useFiltered: boolean;
  format: "csv" | "geojson";
  aggregateBy: string | null;
}): Promise<void> {
  // Get appropriate features based on selection
  // With Arquero, filteredFeatures is already the full filtered result
  const features = filteredFeatures.value;

  const timestamp = new Date().toISOString().split("T")[0];
  const suffix = options.useFiltered ? "filtered" : "all";

  // Handle aggregation if requested
  if (options.aggregateBy) {
    const aggregated = aggregateByBoundary(features, options.aggregateBy);
    const aggSlug = options.aggregateBy.toLowerCase().replace(/\s+/g, "-");

    if (options.format === "csv") {
      const csv = convertAggregatedToCSV(aggregated, options.aggregateBy);
      const blob = new Blob([csv], { type: "text/csv" });
      downloadBlob(blob, `shootings-by-${aggSlug}-${suffix}-${timestamp}.csv`);
    } else {
      // GeoJSON format - join with boundary geometries
      const geojson = await joinAggregatedWithBoundaries(
        aggregated,
        options.aggregateBy
      );
      const blob = new Blob([JSON.stringify(geojson, null, 2)], {
        type: "application/json",
      });
      downloadBlob(
        blob,
        `shootings-by-${aggSlug}-${suffix}-${timestamp}.geojson`
      );
    }
    return;
  }

  // No aggregation - export raw features
  if (options.format === "geojson") {
    const geojson = {
      type: "FeatureCollection",
      features,
    };
    const blob = new Blob([JSON.stringify(geojson, null, 2)], {
      type: "application/json",
    });
    downloadBlob(blob, `shootings-${suffix}-${timestamp}.geojson`);
  } else if (options.format === "csv") {
    const csv = convertToCSV(features);
    const blob = new Blob([csv], { type: "text/csv" });
    downloadBlob(blob, `shootings-${suffix}-${timestamp}.csv`);
  }
}

/**
 * Aggregate features by a boundary layer.
 * Groups shooting features by the boundary column and computes summary statistics.
 *
 * @param features - Array of shooting features
 * @param layerName - Name of the overlay layer to aggregate by
 * @returns Array of aggregated records
 */
function aggregateByBoundary(
  features: Feature[],
  layerName: string
): Array<Record<string, unknown>> {
  // Find the layer config to get the column name
  const layerConfig = layers.value.find((l) => l.name === layerName);
  if (!layerConfig || !layerConfig.column) {
    console.warn(`No column found for layer: ${layerName}`);
    return [];
  }

  const column = layerConfig.column;

  // Group by the boundary column
  const groups = new Map<
    string | number,
    { total: number; fatal: number; nonfatal: number }
  >();

  features.forEach((f) => {
    if (!f.properties) return;
    const key = f.properties[column];
    if (key === null || key === undefined) return;

    const keyStr = String(key);
    if (!groups.has(keyStr)) {
      groups.set(keyStr, { total: 0, fatal: 0, nonfatal: 0 });
    }

    const group = groups.get(keyStr)!;
    group.total += 1;
    if (f.properties.fatal === true) {
      group.fatal += 1;
    } else {
      group.nonfatal += 1;
    }
  });

  // Convert to array of records
  const results: Array<Record<string, unknown>> = [];
  groups.forEach((stats, key) => {
    results.push({
      [column]: key,
      total_shootings: stats.total,
      fatal: stats.fatal,
      nonfatal: stats.nonfatal,
    });
  });

  // Sort by total descending
  results.sort(
    (a, b) => (b.total_shootings as number) - (a.total_shootings as number)
  );

  return results;
}

/**
 * Convert aggregated data to CSV format.
 *
 * @param data - Array of aggregated records
 * @param _layerName - Name of the layer for header (unused, reserved for future use)
 * @returns CSV string
 */
function convertAggregatedToCSV(
  data: Array<Record<string, unknown>>,
  _layerName: string
): string {
  if (data.length === 0) return "";

  const headers = Object.keys(data[0]);
  const rows = data.map((row) =>
    headers.map((h) => {
      const value = row[h];
      if (value === null || value === undefined) return "";
      const str = String(value);
      if (str.includes(",") || str.includes('"')) {
        return `"${str.replace(/"/g, '""')}"`;
      }
      return str;
    })
  );

  return [headers.join(","), ...rows.map((row) => row.join(","))].join("\n");
}

/**
 * Join aggregated data with boundary GeoJSON features.
 * Fetches boundary data and merges shooting counts into feature properties.
 *
 * @param aggregated - Array of aggregated shooting counts
 * @param layerName - Name of the overlay layer
 * @returns GeoJSON FeatureCollection with shooting counts in properties
 */
async function joinAggregatedWithBoundaries(
  aggregated: Array<Record<string, unknown>>,
  layerName: string
): Promise<GeoJSON.FeatureCollection> {
  // Find the layer config to get source and geoid column
  const layerConfig = layers.value.find((l) => l.name === layerName);
  if (!layerConfig || !layerConfig.source || !layerConfig.geoid) {
    console.warn(`No source/geoid found for layer: ${layerName}`);
    return { type: "FeatureCollection", features: [] };
  }

  // Get dataset name from source ID (e.g., "boundary-police-districts" -> "police-districts")
  const dataset = sourceIdToDataset(layerConfig.source);
  if (!dataset) {
    console.warn(
      `Could not extract dataset from source: ${layerConfig.source}`
    );
    return { type: "FeatureCollection", features: [] };
  }

  // Fetch boundary data
  const boundaryData = await boundariesStore.fetchBoundaryData(dataset);
  if (!boundaryData) {
    console.warn(`Failed to fetch boundary data for: ${dataset}`);
    return { type: "FeatureCollection", features: [] };
  }

  // Create lookup map from aggregated data
  const column = layerConfig.column || layerConfig.geoid;
  const statsMap = new Map<string, Record<string, unknown>>();
  aggregated.forEach((row) => {
    const key = String(row[column]);
    statsMap.set(key, row);
  });

  // Join with boundary features
  const joinedFeatures = boundaryData.features.map((boundaryFeature) => {
    const geoid = String(boundaryFeature.properties[layerConfig.geoid!]);
    const stats = statsMap.get(geoid) || {
      total_shootings: 0,
      fatal: 0,
      nonfatal: 0,
    };

    return {
      type: "Feature" as const,
      geometry: boundaryFeature.geometry,
      properties: {
        ...boundaryFeature.properties,
        total_shootings: stats.total_shootings ?? 0,
        fatal: stats.fatal ?? 0,
        nonfatal: stats.nonfatal ?? 0,
      },
    };
  });

  return {
    type: "FeatureCollection",
    features: joinedFeatures,
  };
}

/**
 * Convert features to CSV format.
 * Extracts properties from each feature and formats as CSV.
 *
 * @param features - Array of GeoJSON features
 * @returns CSV string
 */
function convertToCSV(features: Feature[]): string {
  if (features.length === 0) return "";

  // Get all unique property keys from all features
  const allKeys = new Set<string>();
  features.forEach((f) => {
    if (f.properties) {
      Object.keys(f.properties).forEach((key) => allKeys.add(key));
    }
  });

  // Add lat/lng if geometry exists
  const hasGeometry = features.some((f) => f.geometry?.type === "Point");
  if (hasGeometry) {
    allKeys.add("latitude");
    allKeys.add("longitude");
  }

  const headers = Array.from(allKeys);

  // Build rows
  const rows = features.map((f) => {
    return headers.map((header) => {
      let value: unknown;

      if (header === "latitude" && f.geometry?.type === "Point") {
        value = (f.geometry as GeoJSON.Point).coordinates[1];
      } else if (header === "longitude" && f.geometry?.type === "Point") {
        value = (f.geometry as GeoJSON.Point).coordinates[0];
      } else {
        value = f.properties?.[header];
      }

      // Handle null/undefined
      if (value === null || value === undefined) return "";

      // Escape strings with commas or quotes
      const str = String(value);
      if (str.includes(",") || str.includes('"') || str.includes("\n")) {
        return `"${str.replace(/"/g, '""')}"`;
      }
      return str;
    });
  });

  // Combine headers and rows
  return [headers.join(","), ...rows.map((row) => row.join(","))].join("\n");
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
 * Handle layer visibility change from sidebar.
 * Toggles layer visibility on the map.
 * When overlay is active, updates savedToggleableLayers instead of activeLayers.
 *
 * @param layerName - Layer name to toggle
 * @param visible - Whether layer should be visible
 */
function handleLayerChange(layerName: string, visible: boolean): void {
  // When overlay is active, update savedToggleableLayers (what will restore when cleared)
  if (currentOverlay.value) {
    if (visible) {
      if (!savedToggleableLayers.value.includes(layerName)) {
        savedToggleableLayers.value = [
          ...savedToggleableLayers.value,
          layerName,
        ];
      }
    } else {
      savedToggleableLayers.value = savedToggleableLayers.value.filter(
        (l) => l !== layerName
      );
    }
    return;
  }

  // No overlay - update activeLayers directly
  if (visible) {
    if (!activeLayers.value.includes(layerName)) {
      activeLayers.value = [...activeLayers.value, layerName];
    }
  } else {
    activeLayers.value = activeLayers.value.filter((l) => l !== layerName);
  }
}

// Parse initial overlay from URL (if layers param contains an overlay layer)
function getInitialOverlayFromUrl(): string | null {
  const layersParam = route.query.layers;

  if (layersParam && typeof layersParam === "string") {
    const urlIds = layersParam
      .split(",")
      .map((id) => id.trim())
      .filter(Boolean);

    // Find the first URL ID that matches an overlay layer name
    for (const urlId of urlIds) {
      const matchedName = urlIdToLayerName(urlId, overlayLayerNames.value);
      if (matchedName) {
        return matchedName;
      }
    }
  }
  return null;
}

// Track currently selected overlay layer - initialize from URL if present
const currentOverlay = ref<string | null>(getInitialOverlayFromUrl());

// Track saved toggleable layers (to restore when overlay is cleared)
// If we're loading with an overlay from URL, save the default toggleable layers
const savedToggleableLayers = ref<string[]>(
  currentOverlay.value ? [...defaultToggledLayerNames.value] : []
);

// Compute the toggleable layers for checkbox state
// When overlay is active, show the saved layers; otherwise show active toggleable layers
const initialToggleableLayers = computed(() => {
  if (currentOverlay.value) {
    // Overlay is active - show saved toggleable layers (what will restore when cleared)
    return savedToggleableLayers.value.length > 0
      ? savedToggleableLayers.value
      : defaultToggledLayerNames.value;
  }
  // No overlay - filter activeLayers to only include toggleable layers
  return activeLayers.value.filter((l) =>
    toggleableLayerNames.value.includes(l)
  );
});

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
 * Initialize Arquero filtering when data loads or year changes.
 * Filters rows by selected year before initializing Arquero.
 */
watch(
  [rows, selectedYear],
  ([newRows, year]) => {
    if (newRows && newRows.length > 0) {
      // Filter rows by selected year (null = all years)
      const filteredRows =
        year === null || year === undefined
          ? newRows
          : newRows.filter((r) => r.year === year);

      // Initialize Arquero with filtered row data
      initializeArquero(filteredRows as ShootingRow[], filters.value);
      // Initialize histograms after Arquero is ready
      initializeHistograms(filters.value, getHistogramData);
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
