/**
 * URL State Synchronization Composable
 *
 * Syncs map state (year, layers, view) with URL query parameters.
 * Enables shareable links and browser back/forward navigation.
 *
 * URL format: ?year=2025&layers=point-locations,heat-map&map=12.76/39.97240/-75.14142
 *
 * @module useUrlState
 */

import { watch, onMounted, ref } from "vue";
import { useRouter, useRoute } from "vue-router";
import type { Ref } from "vue";
import type { Map as MapLibreMap } from "maplibre-gl";

interface MapViewState {
  zoom: number;
  center: [number, number]; // [lng, lat]
}

/**
 * Convert layer name to URL-friendly ID.
 * Uses lowercase with hyphens instead of spaces.
 *
 * @param name - Human-readable layer name (e.g., "Point locations")
 * @returns URL-friendly ID (e.g., "point-locations")
 */
function layerNameToUrlId(name: string): string {
  return name.toLowerCase().replace(/\s+/g, "-");
}

/**
 * Convert URL ID back to layer name.
 * Looks up the actual layer name from known layer names using case-insensitive matching.
 *
 * @param id - URL-friendly ID (e.g., "pa-senate-districts")
 * @param knownLayerNames - Array of known layer names to look up against
 * @returns Human-readable layer name (e.g., "PA Senate Districts") or fallback
 */
function urlIdToLayerName(id: string, knownLayerNames: string[]): string {
  // Convert ID to comparable form (lowercase with hyphens)
  const normalizedId = id.toLowerCase();

  // Look up actual layer name by matching URL IDs
  for (const layerName of knownLayerNames) {
    const layerUrlId = layerNameToUrlId(layerName);
    if (layerUrlId === normalizedId) {
      return layerName;
    }
  }

  // Fallback: convert hyphens to spaces and capitalize first letter
  const withSpaces = id.replace(/-/g, " ");
  return withSpaces.charAt(0).toUpperCase() + withSpaces.slice(1);
}

/**
 * Composable for syncing map state with URL query parameters.
 *
 * Reads initial state from URL on mount and updates URL when state changes.
 * Enables shareable links like: ?year=2025&layers=point-locations,heat-map&map=12.76/39.97240/-75.14142
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
  mapInstance: Ref<MapLibreMap | null>,
  knownLayerNames: string[] = []
) {
  const router = useRouter();
  const route = useRoute();

  // Track whether map is ready to avoid premature updates
  const mapReady = ref(false);

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
   * Handles comma-separated list of layer IDs (e.g., "point-locations,heat-map").
   * Converts IDs back to human-readable layer names.
   *
   * @param layersParam - Layers parameter string from URL
   * @returns Array of layer names
   */
  function parseLayersParam(layersParam: string): string[] {
    return layersParam
      .split(",")
      .map((l) => l.trim())
      .filter(Boolean)
      .map((id) => urlIdToLayerName(id, knownLayerNames));
  }

  /**
   * Format layers as URL parameter.
   * Converts layer names to URL-friendly IDs and joins with commas.
   *
   * @param layers - Array of active layer names
   * @returns Formatted layers parameter string (e.g., "point-locations,heat-map")
   */
  function formatLayersParam(layers: string[]): string {
    return layers.map(layerNameToUrlId).join(",");
  }

  /**
   * Read initial state from URL query parameters.
   * Applies year and layers from URL to application state.
   * Map view is applied separately when map instance becomes available.
   */
  function readUrlState(): void {
    const query = route.query;

    // Read year (handles both numeric years and "All Years")
    if (query.year && typeof query.year === "string") {
      if (query.year === "All Years") {
        selectedYear.value = null;
      } else {
        const year = parseInt(query.year, 10);
        if (!isNaN(year)) {
          selectedYear.value = year;
        }
      }
    }

    // Read layers
    if (query.layers && typeof query.layers === "string") {
      const layers = parseLayersParam(query.layers);
      if (layers.length > 0) {
        activeLayers.value = layers;
      }
    }

    // Note: Map view is applied in the mapInstance watcher
    // when the map becomes available and is fully loaded
  }

  /**
   * Update URL query parameters with current state.
   * Preserves other query params and uses replace to avoid history spam.
   */
  function updateUrl(): void {
    // Don't update URL until map is ready
    if (!mapReady.value) return;

    const query: Record<string, string> = {};
    // Preserve existing query params (filter out null/array values)
    for (const [key, value] of Object.entries(route.query)) {
      if (typeof value === "string") {
        query[key] = value;
      }
    }

    // Update year (use "All Years" for null to match Vue 2 behavior)
    if (selectedYear.value !== null) {
      query.year = selectedYear.value.toString();
    } else {
      query.year = "All Years";
    }

    // Update layers
    if (activeLayers.value.length > 0) {
      query.layers = formatLayersParam(activeLayers.value);
    } else {
      delete query.layers;
    }

    // Update map view (only if map is loaded)
    if (mapInstance.value && mapInstance.value.loaded()) {
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

    const map = mapInstance.value;

    const setupListeners = () => {
      // Debounce to avoid excessive URL updates
      let timeoutId: ReturnType<typeof setTimeout> | null = null;
      const debouncedUpdate = () => {
        if (timeoutId) clearTimeout(timeoutId);
        timeoutId = setTimeout(updateUrl, 500);
      };

      map.on("moveend", debouncedUpdate);
      map.on("zoomend", debouncedUpdate);
    };

    // Wait for map style to load before setting up listeners
    if (map.loaded()) {
      setupListeners();
    } else {
      map.once("load", setupListeners);
    }
  }

  // Watch for state changes and update URL (but only after map is ready)
  watch(selectedYear, () => {
    if (mapReady.value) updateUrl();
  });
  watch(
    activeLayers,
    () => {
      if (mapReady.value) updateUrl();
    },
    { deep: true }
  );

  // Watch for map instance initialization
  watch(mapInstance, (newMap) => {
    if (newMap) {
      // Apply URL state to new map instance after style loads
      const applyUrlState = () => {
        const query = route.query;
        if (query.map && typeof query.map === "string") {
          const mapView = parseMapParam(query.map);
          if (mapView) {
            // Use flyTo for smoother transition, works even if map is still loading
            newMap.jumpTo({
              center: mapView.center,
              zoom: mapView.zoom,
            });
          }
        }

        // Mark map as ready for URL updates
        mapReady.value = true;
      };

      // Wait for map style to load before applying URL state
      if (newMap.isStyleLoaded()) {
        applyUrlState();
      } else {
        newMap.once("style.load", applyUrlState);
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
