import { computed, type Ref } from "vue";
import type { FilterConfig, LayerConfig } from "../types";
import { getFilterConfigs, getLayerConfigs } from "../config";
import {
  getBoundarySources,
  isBoundarySource,
  getDatasetForSource,
} from "../config/sources";

/**
 * Composable for map configuration (layers, filters, sources).
 *
 * Provides reactive map configuration that updates when selectedYear changes.
 * Wraps the configuration functions to integrate with Vue's reactivity system.
 *
 * Layer categories:
 * - **toggleableLayers**: User-toggleable layers (not choropleth, not static)
 * - **choroplethLayers**: Choropleth boundary layers (choropleth: true in config)
 * - **aggregatedLayers**: Layers requiring data aggregation/joins (aggregated: true)
 * - **staticLayers**: Fixed layers like city limits (static: true)
 * - **defaultLayers**: Layers shown on map load (showOnStart: true)
 *
 * @param selectedYear - Reactive reference to the currently selected year
 * @returns Reactive configuration and utility functions
 *
 * @example
 * ```typescript
 * const shootingsStore = useShootingsStore();
 * const { selectedYear } = storeToRefs(shootingsStore);
 *
 * const {
 *   filters,
 *   layers,
 *   toggleableLayers,
 *   choroplethLayers,
 *   defaultLayerNames,
 * } = useMapConfig(selectedYear);
 *
 * // Toggleable layers for sidebar controls
 * console.log(toggleableLayers.value.map(l => l.name));
 * // ['Point locations', 'Heat map', 'Hot spots by street block']
 *
 * // Choropleth layers for dropdown selector
 * console.log(choroplethLayers.value.map(l => l.name));
 * // ['Police District', 'Council District', ...]
 * ```
 */
export function useMapConfig(selectedYear: Ref<number | null>) {
  /**
   * Reactive filter configurations.
   * Recomputes when selectedYear changes (affects date tooltip formatting).
   */
  const filters = computed<FilterConfig[]>(() =>
    getFilterConfigs(selectedYear.value),
  );

  /**
   * Reactive layer configurations.
   * Recomputes when selectedYear changes (affects point sizes).
   */
  const layers = computed<LayerConfig[]>(() =>
    getLayerConfigs(selectedYear.value),
  );

  // ─────────────────────────────────────────────────────────────────────────────
  // Layer categories - derived from the main layers computed
  // ─────────────────────────────────────────────────────────────────────────────

  /**
   * Toggleable layers (not choropleth layers, not static).
   * These appear in the layer toggle UI in the sidebar.
   */
  const toggleableLayers = computed<LayerConfig[]>(() =>
    layers.value.filter((l) => !l.choropleth && !l.static),
  );

  /**
   * Names of toggleable layers.
   */
  const toggleableLayerNames = computed<string[]>(() =>
    toggleableLayers.value.map((l) => l.name),
  );

  /**
   * Choropleth layers (boundary fill layers for geographic aggregation).
   * These appear in the choropleth layer selector dropdown.
   */
  const choroplethLayers = computed<LayerConfig[]>(() =>
    layers.value.filter((l) => l.choropleth),
  );

  /**
   * Names of choropleth layers.
   */
  const choroplethLayerNames = computed<string[]>(() =>
    choroplethLayers.value.map((l) => l.name),
  );

  /**
   * Aggregated layers (require data aggregation/joins).
   * Used for download options and computing aggregate statistics.
   */
  const aggregatedLayers = computed<LayerConfig[]>(() =>
    layers.value.filter((l) => l.aggregated),
  );

  /**
   * Names of aggregated layers.
   */
  const aggregatedLayerNames = computed<string[]>(() =>
    aggregatedLayers.value.map((l) => l.name),
  );

  /**
   * Static layers (always shown, not affected by filters).
   * E.g., city limits boundary.
   */
  const staticLayers = computed<LayerConfig[]>(() =>
    layers.value.filter((l) => l.static),
  );

  /**
   * Layers shown by default on map load.
   * Includes both toggleable and static layers with showOnStart: true.
   */
  const defaultLayers = computed<LayerConfig[]>(() =>
    layers.value.filter((l) => l.showOnStart),
  );

  /**
   * Names of layers shown by default on map load.
   */
  const defaultLayerNames = computed<string[]>(() =>
    defaultLayers.value.map((l) => l.name),
  );

  /**
   * Names of toggleable layers shown by default.
   * Used for initializing the layer toggle UI state.
   */
  const defaultToggledLayerNames = computed<string[]>(() =>
    toggleableLayers.value.filter((l) => l.showOnStart).map((l) => l.name),
  );

  /**
   * Get a layer by name.
   * @throws Error if layer not found
   */
  function getLayerByName(name: string): LayerConfig {
    const layer = layers.value.find((l) => l.name === name);
    if (!layer) {
      throw new Error(`Layer not found: ${name}`);
    }
    return layer;
  }

  /**
   * Get a layer by source ID.
   */
  function getLayerBySource(sourceId: string): LayerConfig | undefined {
    return layers.value.find((l) => l.source === sourceId);
  }

  return {
    // Reactive configurations
    filters,
    layers,

    // Layer categories
    toggleableLayers,
    toggleableLayerNames,
    choroplethLayers,
    choroplethLayerNames,
    aggregatedLayers,
    aggregatedLayerNames,
    staticLayers,
    defaultLayers,
    defaultLayerNames,
    defaultToggledLayerNames,

    // Layer lookup helpers
    getLayerByName,
    getLayerBySource,

    // Utility functions for boundary sources
    getBoundarySources,
    isBoundarySource,
    getDatasetForSource,
  };
}
