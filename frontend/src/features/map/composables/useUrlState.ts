/**
 * URL State Synchronization Composable
 *
 * Syncs map state (year, layers, view) with URL query parameters.
 * Enables shareable links and browser back/forward navigation.
 *
 * URL format: ?year=2025&layers=Point%20locations&map=12.76/39.97240/-75.14142
 *
 * @module useUrlState
 */

import { watch, onMounted } from "vue";
import { useRouter, useRoute } from "vue-router";
import type { Ref } from "vue";
import type { Map as MapLibreMap } from "maplibre-gl";

interface MapViewState {
  zoom: number;
  center: [number, number]; // [lng, lat]
}

/**
 * Composable for syncing map state with URL query parameters.
 *
 * Reads initial state from URL on mount and updates URL when state changes.
 * Enables shareable links like: ?year=2025&layers=Point%20locations&map=12.76/39.97240/-75.14142
 *
 * @param selectedYear - Reactive ref for selected year
 * @param activeLayers - Reactive ref for active layer names
 * @param mapInstance - Reactive ref for MapLibre map instance
 *
 * @example
 * ```typescript
 * const { selectedYear } = storeToRefs(shootingsStore);
 * const activeLayers = ref<string[]>(['Point locations']);
 * const mapInstance = ref<MapLibreMap | null>(null);
 *
 * useUrlState(selectedYear, activeLayers, mapInstance);
 * ```
 */
export function useUrlState(
  selectedYear: Ref<number | null>,
  activeLayers: Ref<string[]>,
  mapInstance: Ref<MapLibreMap | null>
) {
  const router = useRouter();
  const route = useRoute();

  /**
   * Parse map view from URL parameter.
   * Format: "zoom/lat/lng" (e.g., "12.76/39.97240/-75.14142")
   *
   * @param mapParam - Map parameter string from URL
   * @returns Parsed map view state or null if invalid
   */
  function parseMapParam(mapParam: string): MapViewState | null {
    const parts = mapParam.split("/");
    if (parts.length !== 3) return null;

    const zoom = parseFloat(parts[0]);
    const lat = parseFloat(parts[1]);
    const lng = parseFloat(parts[2]);

    if (isNaN(zoom) || isNaN(lat) || isNaN(lng)) return null;

    return {
      zoom,
      center: [lng, lat],
    };
  }

  /**
   * Format map view as URL parameter.
   * Format: "zoom/lat/lng" (e.g., "12.76/39.97240/-75.14142")
   *
   * @param zoom - Map zoom level
   * @param center - Map center [lng, lat]
   * @returns Formatted map parameter string
   */
  function formatMapParam(zoom: number, center: [number, number]): string {
    // Round to 5 decimal places (~1m precision)
    const lat = center[1].toFixed(5);
    const lng = center[0].toFixed(5);
    const z = zoom.toFixed(2);
    return `${z}/${lat}/${lng}`;
  }

  /**
   * Parse layers from URL parameter.
   * Handles comma-separated list of layer names.
   *
   * @param layersParam - Layers parameter string from URL
   * @returns Array of layer names
   */
  function parseLayersParam(layersParam: string): string[] {
    return layersParam
      .split(",")
      .map((l) => decodeURIComponent(l.trim()))
      .filter(Boolean);
  }

  /**
   * Format layers as URL parameter.
   * Joins layer names with commas.
   *
   * @param layers - Array of active layer names
   * @returns Formatted layers parameter string
   */
  function formatLayersParam(layers: string[]): string {
    return layers.map((l) => encodeURIComponent(l)).join(",");
  }

  /**
   * Read initial state from URL query parameters.
   * Applies year, layers, and map view from URL to application state.
   */
  function readUrlState(): void {
    const query = route.query;

    // Read year
    if (query.year && typeof query.year === "string") {
      const year = parseInt(query.year, 10);
      if (!isNaN(year)) {
        selectedYear.value = year;
      }
    }

    // Read layers
    if (query.layers && typeof query.layers === "string") {
      const layers = parseLayersParam(query.layers);
      if (layers.length > 0) {
        activeLayers.value = layers;
      }
    }

    // Read map view
    if (query.map && typeof query.map === "string" && mapInstance.value) {
      const mapView = parseMapParam(query.map);
      if (mapView) {
        mapInstance.value.jumpTo({
          center: mapView.center,
          zoom: mapView.zoom,
        });
      }
    }
  }

  /**
   * Update URL query parameters with current state.
   * Preserves other query params and uses replace to avoid history spam.
   */
  function updateUrl(): void {
    const query: Record<string, string> = { ...route.query };

    // Update year
    if (selectedYear.value !== null) {
      query.year = selectedYear.value.toString();
    } else {
      delete query.year;
    }

    // Update layers
    if (activeLayers.value.length > 0) {
      query.layers = formatLayersParam(activeLayers.value);
    } else {
      delete query.layers;
    }

    // Update map view
    if (mapInstance.value) {
      const center = mapInstance.value.getCenter();
      const zoom = mapInstance.value.getZoom();
      query.map = formatMapParam(zoom, [center.lng, center.lat]);
    }

    // Update URL without adding history entry
    router.replace({ query });
  }

  /**
   * Set up map event listeners for view changes.
   * Updates URL when user pans/zooms the map.
   */
  function setupMapListeners(): void {
    if (!mapInstance.value) return;

    // Debounce to avoid excessive URL updates
    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    const debouncedUpdate = () => {
      if (timeoutId) clearTimeout(timeoutId);
      timeoutId = setTimeout(updateUrl, 500);
    };

    mapInstance.value.on("moveend", debouncedUpdate);
    mapInstance.value.on("zoomend", debouncedUpdate);
  }

  // Watch for state changes and update URL
  watch(selectedYear, updateUrl);
  watch(activeLayers, updateUrl, { deep: true });

  // Watch for map instance initialization
  watch(mapInstance, (newMap) => {
    if (newMap) {
      // Apply URL state to new map instance
      const query = route.query;
      if (query.map && typeof query.map === "string") {
        const mapView = parseMapParam(query.map);
        if (mapView) {
          newMap.jumpTo({
            center: mapView.center,
            zoom: mapView.zoom,
          });
        }
      }

      // Set up listeners for future changes
      setupMapListeners();
    }
  });

  // Read URL state on mount
  onMounted(() => {
    readUrlState();
  });

  return {
    readUrlState,
    updateUrl,
  };
}
