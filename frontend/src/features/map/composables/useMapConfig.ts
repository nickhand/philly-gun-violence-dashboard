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
 *   getBoundarySources,
 *   getDatasetForSource
 * } = useMapConfig(selectedYear);
 *
 * // Use in template or other composables
 * console.log(filters.value); // Array of FilterConfig
 * console.log(layers.value);  // Array of LayerConfig
 *
 * // Load boundary sources
 * const boundarySourceIds = await getBoundarySources();
 * // ['boundary-police-districts', 'boundary-council-districts', ...]
 *
 * // Convert source ID to dataset name for API calls
 * const dataset = getDatasetForSource('boundary-police-districts');
 * // 'police-districts'
 * ```
 */
export function useMapConfig(selectedYear: Ref<number | null>) {
  /**
   * Reactive filter configurations.
   * Recomputes when selectedYear changes (affects date tooltip formatting).
   */
  const filters = computed<FilterConfig[]>(() =>
    getFilterConfigs(selectedYear.value)
  );

  /**
   * Reactive layer configurations.
   * Recomputes when selectedYear changes (affects point sizes).
   */
  const layers = computed<LayerConfig[]>(() =>
    getLayerConfigs(selectedYear.value)
  );

  return {
    // Reactive configurations
    filters,
    layers,

    // Utility functions for boundary sources
    getBoundarySources,
    isBoundarySource,
    getDatasetForSource,
  };
}
