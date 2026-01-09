/**
 * Map sources composable.
 *
 * Handles adding, updating, and managing GeoJSON sources on the map.
 * Integrates with aggregation for color-coded sources.
 *
 * @module useMapSources
 */

import { type Ref, type ComputedRef } from "vue";
import type { Map as MapLibreMap, GeoJSONSource } from "maplibre-gl";
import { apiFetch } from "@/shared/api/client";
import { fetchStreetsAllPages } from "@/shared/api/streets";
import { sourceIdToDataset, SOURCES } from "../config/sources";
import { getSegmentIdsFromFeatures, emptyFeatureCollection } from "./mapUtils";
import type { LayerConfig } from "../types";

/**
 * Composable for managing map GeoJSON sources.
 *
 * @param mapInstance - Reactive ref to map instance
 * @param mapLoaded - Reactive ref to map loaded state
 * @param filteredFeatures - Reactive ref to filtered features
 * @param applyAggregationColors - Function to apply aggregation colors
 * @param showLoader - Function to show loading spinner
 * @param hideLoader - Function to hide loading spinner
 * @returns Source management methods
 *
 * @example
 * ```typescript
 * const { addSource, updateShootingsSource, updateStreetsSource } =
 *   useMapSources(mapInstance, mapLoaded, filteredFeatures, applyAggregationColors, showLoader, hideLoader);
 * ```
 */
export function useMapSources(
  mapInstance: Ref<MapLibreMap | null>,
  mapLoaded: Ref<boolean>,
  filteredFeatures: Ref<GeoJSON.Feature[]> | ComputedRef<GeoJSON.Feature[]>,
  applyAggregationColors: (
    config: LayerConfig,
    features: GeoJSON.Feature[]
  ) => GeoJSON.Feature[],
  showLoader: () => void = () => {},
  hideLoader: () => void = () => {}
) {
  /**
   * Check if a source exists on the map.
   *
   * @param sourceId - Source ID to check
   * @returns True if source exists
   */
  function hasSource(sourceId: string): boolean {
    return mapInstance.value?.getSource(sourceId) !== undefined;
  }

  /**
   * Get a source from the map.
   *
   * @param sourceId - Source ID
   * @returns GeoJSON source or null
   */
  function getSource(sourceId: string): GeoJSONSource | null {
    return (mapInstance.value?.getSource(sourceId) as GeoJSONSource) ?? null;
  }

  /**
   * Add an empty GeoJSON source to the map.
   *
   * @param sourceId - Source ID
   */
  function addEmptySource(sourceId: string): void {
    if (!mapInstance.value || hasSource(sourceId)) return;

    mapInstance.value.addSource(sourceId, {
      type: "geojson",
      data: emptyFeatureCollection(),
    });
  }

  /**
   * Add a GeoJSON source with data to the map.
   *
   * @param sourceId - Source ID
   * @param data - GeoJSON data
   */
  function addSourceWithData(
    sourceId: string,
    data: GeoJSON.FeatureCollection
  ): void {
    if (!mapInstance.value || hasSource(sourceId)) return;

    mapInstance.value.addSource(sourceId, {
      type: "geojson",
      data,
    });
  }

  /**
   * Update an existing source's data.
   *
   * @param sourceId - Source ID
   * @param data - New GeoJSON data
   */
  function updateSourceData(
    sourceId: string,
    data: GeoJSON.FeatureCollection
  ): void {
    const source = getSource(sourceId);
    if (source) {
      source.setData(data);
    }
  }

  /**
   * Fetch boundary data from API.
   *
   * @param dataset - Dataset name (e.g., "police-districts")
   * @returns GeoJSON FeatureCollection
   */
  async function fetchBoundaryData(
    dataset: string
  ): Promise<GeoJSON.FeatureCollection> {
    const apiDataset = dataset.replace(/-/g, "_");
    return apiFetch<GeoJSON.FeatureCollection>(`/boundaries/${apiDataset}`);
  }

  /**
   * Add a source for a specific layer config.
   * Handles shootings, streets, and boundary sources differently.
   *
   * @param config - Layer configuration
   */
  async function addSourceForLayer(config: LayerConfig): Promise<void> {
    if (!mapInstance.value) return;

    const sourceId = config.source;

    // Skip if source already exists
    if (hasSource(sourceId)) return;

    // Shootings source - empty initially, no loader needed
    if (sourceId === SOURCES.SHOOTINGS) {
      addEmptySource(sourceId);
      return;
    }

    // Show loader while fetching data
    showLoader();

    try {
      // Street blocks source - fetch by segment IDs
      if (sourceId === SOURCES.STREETS) {
        await addStreetsSource(config);
        return;
      }

      // Boundary sources - fetch from API
      await addBoundarySource(config);
    } finally {
      // Always hide loader when done
      hideLoader();
    }
  }

  /**
   * Add streets source with filtered segment IDs.
   *
   * @param config - Layer configuration
   */
  async function addStreetsSource(config: LayerConfig): Promise<void> {
    if (!mapInstance.value) return;

    try {
      const segmentIds = getSegmentIdsFromFeatures(filteredFeatures.value);
      let data =
        segmentIds.length > 0
          ? await fetchStreetsAllPages({ segment_id: segmentIds })
          : emptyFeatureCollection();

      // Apply aggregation colors if needed
      if (config.aggregated && data.features.length > 0) {
        const coloredFeatures = applyAggregationColors(
          config,
          data.features as GeoJSON.Feature[]
        );
        data = {
          type: "FeatureCollection",
          features: coloredFeatures as typeof data.features,
        };
      }

      addSourceWithData(SOURCES.STREETS, data);
    } catch (error) {
      console.error("Failed to load street blocks:", error);
      addEmptySource(SOURCES.STREETS);
    }
  }

  /**
   * Add boundary source from API.
   *
   * @param config - Layer configuration
   */
  async function addBoundarySource(config: LayerConfig): Promise<void> {
    if (!mapInstance.value) return;

    const dataset = sourceIdToDataset(config.source);
    if (!dataset) return;

    try {
      const rawData = await fetchBoundaryData(dataset);
      let data = rawData;

      // Apply aggregation colors if needed
      if (config.aggregated && rawData.features.length > 0) {
        const coloredFeatures = applyAggregationColors(
          config,
          rawData.features as GeoJSON.Feature[]
        );
        data = {
          type: "FeatureCollection",
          features: coloredFeatures,
        };
      }

      addSourceWithData(config.source, data);
    } catch (error) {
      console.error(`Failed to load source ${config.source}:`, error);
    }
  }

  /**
   * Update shootings source with filtered features.
   *
   * @param features - Filtered shooting features
   */
  function updateShootingsSource(features: GeoJSON.Feature[]): void {
    if (!mapLoaded.value) return;

    updateSourceData(SOURCES.SHOOTINGS, {
      type: "FeatureCollection",
      features,
    });
  }

  /**
   * Update streets source with filtered segment IDs.
   *
   * @param config - Layer configuration
   */
  async function updateStreetsSource(config: LayerConfig): Promise<void> {
    if (!mapLoaded.value) return;

    const source = getSource(SOURCES.STREETS);
    if (!source) return;

    try {
      const segmentIds = getSegmentIdsFromFeatures(filteredFeatures.value);
      let data =
        segmentIds.length > 0
          ? await fetchStreetsAllPages({ segment_id: segmentIds })
          : emptyFeatureCollection();

      // Apply aggregation colors
      if (config.aggregated && data.features.length > 0) {
        const coloredFeatures = applyAggregationColors(
          config,
          data.features as GeoJSON.Feature[]
        );
        data = {
          type: "FeatureCollection",
          features: coloredFeatures as typeof data.features,
        };
      }

      source.setData(data);
    } catch (error) {
      console.error("Failed to update street blocks:", error);
    }
  }

  /**
   * Update boundary source with aggregation colors.
   *
   * @param config - Layer configuration
   */
  async function updateBoundarySource(config: LayerConfig): Promise<void> {
    if (!mapLoaded.value) return;

    const source = getSource(config.source);
    if (!source) return;

    const dataset = sourceIdToDataset(config.source);
    if (!dataset) return;

    try {
      const rawData = await fetchBoundaryData(dataset);
      let data = rawData;

      // Apply aggregation colors
      if (config.aggregated && rawData.features.length > 0) {
        const coloredFeatures = applyAggregationColors(
          config,
          rawData.features as GeoJSON.Feature[]
        );
        data = {
          type: "FeatureCollection",
          features: coloredFeatures,
        };
      }

      source.setData(data);
    } catch (error) {
      console.error(
        `Failed to update boundary source ${config.source}:`,
        error
      );
    }
  }

  /**
   * Add initial sources for layers that show on start.
   *
   * @param layerConfigs - All layer configurations
   */
  async function addInitialSources(layerConfigs: LayerConfig[]): Promise<void> {
    if (!mapInstance.value) return;

    // Only add sources for default layers (showOnStart or static) with paint
    for (const config of layerConfigs) {
      if (!(config.showOnStart || config.static) || !config.paint) continue;

      await addSourceForLayer(config);
    }
  }

  return {
    // Query methods
    hasSource,
    getSource,
    // Add methods
    addEmptySource,
    addSourceWithData,
    addSourceForLayer,
    addInitialSources,
    // Update methods
    updateSourceData,
    updateShootingsSource,
    updateStreetsSource,
    updateBoundarySource,
    // Fetch methods
    fetchBoundaryData,
  };
}
