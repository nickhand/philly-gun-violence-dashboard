/**
 * Map instance composable.
 *
 * Handles MapLibre GL map initialization, lifecycle, and controls.
 * Provides reactive refs for map state and methods for map operations.
 *
 * @module useMapInstance
 */

import { ref, computed, onMounted, onBeforeUnmount, type Ref } from "vue";
import maplibregl, { type Map as MapLibreMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import mapStyle from "@/data/style.json";
import { enhanceBasemapLabels } from "../config/basemapLabels";

/**
 * Map configuration options.
 */
export interface MapOptions {
  /** Map center coordinates [lng, lat] */
  center?: [number, number];
  /** Initial zoom level */
  zoom?: number;
  /** Minimum zoom level */
  minZoom?: number;
  /** Maximum zoom level */
  maxZoom?: number;
}

/**
 * Default map configuration for Philadelphia.
 */
const DEFAULT_OPTIONS: Required<MapOptions> = {
  center: [-75.1652, 39.9526], // Philadelphia
  zoom: 11,
  minZoom: 9,
  maxZoom: 18,
};

/**
 * Composable for MapLibre GL map instance management.
 *
 * @param options - Optional map configuration
 * @returns Map instance refs and methods
 *
 * @example
 * ```typescript
 * const { mapContainer, mapInstance, mapLoaded, isLoading, onMapReady } = useMapInstance();
 *
 * // In template: <div ref="mapContainer" />
 * // Wait for map ready: onMapReady(() => { ... });
 * ```
 */
export function useMapInstance(options: MapOptions = {}) {
  const config = { ...DEFAULT_OPTIONS, ...options };

  // Refs
  const mapContainer = ref<HTMLDivElement | null>(null);
  const mapInstance: Ref<MapLibreMap | null> = ref(null);
  const isLoading = ref(true);
  const mapLoaded = ref(false);

  // Loading spinner state (matches legacy behavior)
  /** Whether map data is loading (from MapLibre dataloading/idle events) */
  const dataLoading = ref(false);
  /** Manual loader override - set by showLoader()/hideLoader() */
  const showLoaderManual = ref(false);

  /**
   * Whether to show the loading spinner.
   * True when either map data is loading OR showLoader() was called.
   */
  const showLoadingSpinner = computed(
    () => dataLoading.value || showLoaderManual.value
  );

  // Callbacks to run when map is ready
  const readyCallbacks: Array<() => void | Promise<void>> = [];

  /**
   * Register a callback to run when map is ready.
   * If map is already ready, callback runs immediately.
   *
   * @param callback - Function to run when map loads
   */
  function onMapReady(callback: () => void | Promise<void>): void {
    if (mapLoaded.value) {
      callback();
    } else {
      readyCallbacks.push(callback);
    }
  }

  /**
   * Force the loading spinner to show.
   * Used when adding layers or performing async operations.
   */
  function showLoader(): void {
    showLoaderManual.value = true;
  }

  /**
   * Force the loading spinner to hide.
   */
  function hideLoader(): void {
    showLoaderManual.value = false;
  }

  /**
   * Initialize the MapLibre GL map.
   * Creates map instance with controls and event listeners.
   */
  function initializeMap(): void {
    if (!mapContainer.value) return;

    mapInstance.value = new maplibregl.Map({
      container: mapContainer.value,
      style: mapStyle as maplibregl.StyleSpecification,
      center: config.center,
      zoom: config.zoom,
      minZoom: config.minZoom,
      maxZoom: config.maxZoom,
      dragRotate: false, // Disable 3D rotation
      pitchWithRotate: false, // Disable pitch/tilt
    });

    // Add navigation controls (zoom only, no compass - matches legacy app)
    mapInstance.value.addControl(
      new maplibregl.NavigationControl({ showCompass: false }),
      "top-right"
    );
    mapInstance.value.addControl(
      new maplibregl.ScaleControl({}),
      "bottom-left"
    );

    // Track data loading state (matches legacy behavior)
    mapInstance.value.on("dataloading", () => {
      dataLoading.value = true;
    });
    mapInstance.value.on("idle", () => {
      dataLoading.value = false;
    });

    // Handle map load event
    mapInstance.value.on("load", async () => {
      enhanceBasemapLabels(mapInstance.value!);
      isLoading.value = false;
      mapLoaded.value = true;

      // Run all registered callbacks
      for (const callback of readyCallbacks) {
        await callback();
      }
      readyCallbacks.length = 0; // Clear callbacks
    });
  }

  /**
   * Clean up map instance.
   * Removes map to prevent memory leaks.
   */
  function destroyMap(): void {
    if (mapInstance.value) {
      mapInstance.value.remove();
      mapInstance.value = null;
    }
  }

  /**
   * Get the map canvas element.
   *
   * @returns Canvas element or null
   */
  function getCanvas(): HTMLCanvasElement | null {
    return mapInstance.value?.getCanvas() ?? null;
  }

  /**
   * Set cursor style on map canvas.
   *
   * @param cursor - CSS cursor value
   */
  function setCursor(cursor: string): void {
    const canvas = getCanvas();
    if (canvas) {
      canvas.style.cursor = cursor;
    }
  }

  // Lifecycle
  onMounted(() => {
    initializeMap();
  });

  onBeforeUnmount(() => {
    destroyMap();
  });

  return {
    // Refs
    mapContainer,
    mapInstance,
    isLoading,
    mapLoaded,
    showLoadingSpinner,
    // Methods
    onMapReady,
    showLoader,
    hideLoader,
    getCanvas,
    setCursor,
    destroyMap,
  };
}
