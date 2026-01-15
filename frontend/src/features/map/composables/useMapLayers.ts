/**
 * Map layers composable.
 *
 * Handles adding, toggling, and managing map layers.
 * Supports lazy loading of layers and sources on-demand.
 *
 * @module useMapLayers
 */

import { type Ref } from "vue";
import type { Map as MapLibreMap, LayerSpecification } from "maplibre-gl";
import { layerNameToId } from "./mapUtils";
import { sourceIdToDataset, SOURCES } from "../config/sources";
import type { LayerConfig } from "../types";

/**
 * Composable for managing map layers.
 *
 * @param mapInstance - Reactive ref to map instance
 * @param mapLoaded - Reactive ref to map loaded state
 * @param setCursor - Function to set cursor style
 * @returns Layer management methods
 *
 * @example
 * ```typescript
 * const { addLayer, setActiveLayers, setFilter } =
 *   useMapLayers(mapInstance, mapLoaded, setCursor);
 * ```
 */
export function useMapLayers(
  mapInstance: Ref<MapLibreMap | null>,
  mapLoaded: Ref<boolean>,
  setCursor: (cursor: string) => void
) {
  /**
   * Check if a layer exists on the map.
   *
   * @param layerId - Layer ID to check
   * @returns True if layer exists
   */
  function hasLayer(layerId: string): boolean {
    return mapInstance.value?.getLayer(layerId) !== undefined;
  }

  /**
   * Get layer visibility.
   *
   * @param layerId - Layer ID
   * @returns Visibility value or null
   */
  function getVisibility(layerId: string): string | null {
    if (!mapInstance.value || !hasLayer(layerId)) return null;
    return mapInstance.value.getLayoutProperty(layerId, "visibility") as string;
  }

  /**
   * Set layer visibility.
   *
   * @param layerId - Layer ID
   * @param visible - Whether layer should be visible
   */
  function setVisibility(layerId: string, visible: boolean): void {
    if (!mapInstance.value || !hasLayer(layerId)) return;
    mapInstance.value.setLayoutProperty(
      layerId,
      "visibility",
      visible ? "visible" : "none"
    );
  }

  /**
   * Build paint object for a layer, handling aggregated and overlay layers.
   *
   * @param config - Layer configuration
   * @returns Paint object for MapLibre
   */
  function buildPaintObject(config: LayerConfig): Record<string, unknown> {
    const paint: Record<string, unknown> = { ...config.paint };

    // For aggregated layers, use color from feature properties
    if (config.aggregated) {
      const colorKey = `${config.type}-color`;
      paint[colorKey] = ["get", "color"];
    }

    // Add opacity for overlay fill layers
    if (config.overlay && config.type === "fill") {
      paint["fill-opacity"] = 0.5;
    }

    return paint;
  }

  /**
   * Add a layer to the map.
   *
   * @param config - Layer configuration
   * @param visible - Whether layer should be visible initially
   */
  function addLayer(config: LayerConfig, visible: boolean = true): void {
    if (!mapInstance.value) return;

    const layerId = layerNameToId(config.name);

    // Skip if layer already exists
    if (hasLayer(layerId)) return;

    // Skip if source doesn't exist
    if (!mapInstance.value.getSource(config.source)) {
      console.warn(
        `Cannot add layer ${layerId}: source ${config.source} not found`
      );
      return;
    }

    const visibility = visible ? "visible" : "none";
    const paint = buildPaintObject(config);

    // Add layer based on type
    // Using type assertion to satisfy MapLibre's strict layer type union
    mapInstance.value.addLayer({
      id: layerId,
      type: config.type,
      source: config.source,
      layout: { visibility },
      paint,
    } as LayerSpecification);

    // Add hover cursor for interactive point layers
    if (config.type === "circle") {
      mapInstance.value.on("mouseenter", layerId, () => setCursor("pointer"));
      mapInstance.value.on("mouseleave", layerId, () => setCursor(""));
    }
  }

  /**
   * Add initial layers for configs that should show on start.
   *
   * @param layerConfigs - All layer configurations
   */
  function addInitialLayers(layerConfigs: LayerConfig[]): void {
    if (!mapInstance.value) return;

    for (const config of layerConfigs) {
      if (!(config.showOnStart || config.static) || !config.paint) continue;
      addLayer(config, true);
    }
  }

  /**
   * Set active layers, lazy loading sources and layers as needed.
   *
   * @param layerNames - Array of layer names to show
   * @param layerConfigs - All layer configurations
   * @param addSourceForLayer - Function to add source for a layer
   * @param updateStreetsSource - Function to update streets source
   * @param updateBoundarySource - Function to update boundary source
   * @returns Whether any aggregated layer is visible
   */
  async function setActiveLayers(
    layerNames: string[],
    layerConfigs: LayerConfig[],
    addSourceForLayer: (config: LayerConfig) => Promise<void>,
    updateStreetsSource: (config: LayerConfig) => Promise<void>,
    updateBoundarySource: (config: LayerConfig) => Promise<void>
  ): Promise<boolean> {
    if (!mapInstance.value || !mapLoaded.value) {
      return false;
    }

    let anyAggregatedLayerVisible = false;

    for (const config of layerConfigs) {
      // Skip static layers - they're always visible
      if (config.static) continue;

      const layerId = layerNameToId(config.name);
      const shouldBeVisible = layerNames.includes(config.name);

      // Track if any aggregated layer is visible
      if (config.aggregated && shouldBeVisible) {
        anyAggregatedLayerVisible = true;
      }

      // If layer should be visible but doesn't exist, add it first
      if (shouldBeVisible && !hasLayer(layerId)) {
        // Add source if needed (loader is shown in addSourceForLayer)
        if (!mapInstance.value.getSource(config.source)) {
          await addSourceForLayer(config);
        }
        // Add the layer
        addLayer(config, true);
      }
      // If layer exists, toggle visibility and update if needed
      else if (hasLayer(layerId)) {
        setVisibility(layerId, shouldBeVisible);

        // Update aggregated source colors when layer becomes visible
        if (shouldBeVisible && config.aggregated) {
          if (config.source === SOURCES.STREETS) {
            await updateStreetsSource(config);
          } else if (sourceIdToDataset(config.source)) {
            await updateBoundarySource(config);
          }
        }
      }
    }

    return anyAggregatedLayerVisible;
  }

  /**
   * Update all visible aggregated boundary sources.
   *
   * @param layerConfigs - All layer configurations
   * @param updateBoundarySource - Function to update boundary source
   * @param activeLayers - Optional list of active layer names to filter by
   */
  async function updateVisibleAggregatedLayers(
    layerConfigs: LayerConfig[],
    updateBoundarySource: (config: LayerConfig) => Promise<void>,
    activeLayers?: string[]
  ): Promise<void> {
    if (!mapInstance.value || !mapLoaded.value) return;

    for (const config of layerConfigs) {
      if (!config.aggregated) continue;
      if (config.source === SOURCES.STREETS) continue;

      const layerId = layerNameToId(config.name);
      if (!hasLayer(layerId)) continue;

      // Check map visibility
      const visibility = getVisibility(layerId);
      if (visibility !== "visible") continue;

      // If activeLayers is provided, also check that the layer is in the list
      if (activeLayers && !activeLayers.includes(config.name)) continue;

      await updateBoundarySource(config);
    }
  }

  /**
   * Apply a MapLibre filter expression to a layer.
   *
   * @param layerId - Layer ID
   * @param filter - Filter expression or null to clear
   */
  function setFilter(layerId: string, filter: unknown[] | null): void {
    if (!mapInstance.value || !mapLoaded.value || !hasLayer(layerId)) return;
    mapInstance.value.setFilter(layerId, filter as any);
  }

  /**
   * Set a paint property on a layer.
   *
   * @param layerId - Layer ID
   * @param property - Paint property name
   * @param value - Property value
   */
  function setPaintProperty(
    layerId: string,
    property: string,
    value: unknown
  ): void {
    if (!mapInstance.value || !hasLayer(layerId)) return;
    mapInstance.value.setPaintProperty(layerId, property, value as any);
  }

  return {
    // Query methods
    hasLayer,
    getVisibility,
    // Mutation methods
    addLayer,
    addInitialLayers,
    setVisibility,
    setActiveLayers,
    updateVisibleAggregatedLayers,
    setFilter,
    setPaintProperty,
    // Helpers
    buildPaintObject,
  };
}
