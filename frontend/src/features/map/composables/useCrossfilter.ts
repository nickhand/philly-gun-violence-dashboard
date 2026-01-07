/**
 * Crossfilter Composable
 *
 * Manages multi-dimensional filtering of GeoJSON data using crossfilter2.
 * Provides reactive filter state and efficient dimension queries.
 *
 * @module useCrossfilter
 */

import { ref, type Ref } from "vue";
import crossfilter, { type Crossfilter, type Dimension } from "crossfilter2";
import type { FilterConfig } from "../types";

/**
 * Crossfilter composable return type.
 * Provides crossfilter instance, dimensions map, and filter operations.
 */
interface UseCrossfilterReturn {
  /** Crossfilter instance managing the dataset */
  crossfilterInstance: Ref<Crossfilter<GeoJSON.Feature> | null>;
  /** Map of dimension ID to crossfilter dimension */
  dimensions: Ref<Map<string, Dimension<GeoJSON.Feature, any>>>;
  /** Active filter values keyed by dimension ID */
  activeFilters: Ref<Map<string, any>>;
  /** Initialize crossfilter with GeoJSON features */
  initializeCrossfilter: (
    features: GeoJSON.Feature[],
    filterConfigs: FilterConfig[]
  ) => void;
  /** Apply filter to a dimension */
  applyFilter: (dimensionId: string, value: any) => void;
  /** Reset a specific dimension filter */
  resetFilter: (dimensionId: string) => void;
  /** Reset all dimension filters */
  resetAllFilters: () => void;
  /** Get all currently filtered features */
  getAllFiltered: () => GeoJSON.Feature[];
  /** Get summary statistics for a dimension */
  getDimensionStats: (dimensionId: string) => {
    count: number;
    extent?: [any, any];
  };
}

/**
 * Creates a crossfilter-based filtering system for GeoJSON data.
 *
 * Usage:
 * ```ts
 * const {
 *   crossfilterInstance,
 *   dimensions,
 *   activeFilters,
 *   initializeCrossfilter,
 *   applyFilter,
 *   resetAllFilters,
 *   getAllFiltered
 * } = useCrossfilter();
 *
 * // Initialize with data
 * initializeCrossfilter(shootingsFeatures, filterConfigs);
 *
 * // Apply filters
 * applyFilter('year', [2020, 2023]);
 * applyFilter('fatal', true);
 *
 * // Get filtered results
 * const filtered = getAllFiltered();
 * ```
 *
 * @returns {UseCrossfilterReturn} Crossfilter state and operations
 */
export function useCrossfilter(): UseCrossfilterReturn {
  const crossfilterInstance = ref<Crossfilter<GeoJSON.Feature> | null>(null);
  const dimensions = ref<Map<string, Dimension<GeoJSON.Feature, any>>>(
    new Map()
  );
  const activeFilters = ref<Map<string, any>>(new Map());

  /**
   * Initialize crossfilter with GeoJSON features and create dimensions.
   * Must be called before any filter operations.
   *
   * @param features - GeoJSON features to filter
   * @param filterConfigs - Filter configurations defining dimensions
   *
   * @example
   * ```ts
   * const filterConfigs: FilterConfig[] = [
   *   { id: 'year', property: 'year', type: 'range', min: 2015, max: 2025 },
   *   { id: 'fatal', property: 'fatal', type: 'checkbox' }
   * ];
   * initializeCrossfilter(features, filterConfigs);
   * ```
   */
  function initializeCrossfilter(
    features: GeoJSON.Feature[],
    filterConfigs: FilterConfig[]
  ): void {
    // Create new crossfilter instance with features
    crossfilterInstance.value = crossfilter(features);

    // Clear existing dimensions
    dimensions.value.clear();
    activeFilters.value.clear();

    // Create dimension for each filter configuration
    filterConfigs.forEach((config) => {
      const dimension = crossfilterInstance.value!.dimension(
        (d: GeoJSON.Feature) => {
          // Access property from feature.properties using config.name
          return d.properties?.[config.name];
        }
      );
      dimensions.value.set(config.name, dimension);
    });
  }

  /**
   * Apply filter to a specific dimension.
   * Updates active filters and filters the dimension.
   *
   * @param dimensionId - ID of the dimension to filter
   * @param value - Filter value (type depends on filter config)
   *                - Range: [min, max] tuple
   *                - Select: single value
   *                - Multiselect: array of values
   *                - Checkbox: boolean
   *
   * @example
   * ```ts
   * applyFilter('year', [2020, 2023]); // Range filter
   * applyFilter('district', 'Central'); // Select filter
   * applyFilter('fatal', true); // Checkbox filter
   * ```
   */
  function applyFilter(dimensionId: string, value: any): void {
    const dimension = dimensions.value.get(dimensionId);
    if (!dimension) {
      console.warn(`Dimension ${dimensionId} not found`);
      return;
    }

    // Store active filter value
    activeFilters.value.set(dimensionId, value);

    // Apply filter based on value type
    if (Array.isArray(value)) {
      // Range filter: [min, max]
      if (value.length === 2 && typeof value[0] === "number") {
        dimension.filterRange(value as [number, number]);
      }
      // Multiselect filter: array of values
      else {
        dimension.filterFunction((d) => value.includes(d));
      }
    } else if (typeof value === "boolean") {
      // Checkbox filter
      dimension.filterExact(value);
    } else if (value !== null && value !== undefined) {
      // Single value filter
      dimension.filterExact(value);
    } else {
      // Clear filter if value is null/undefined
      dimension.filterAll();
      activeFilters.value.delete(dimensionId);
    }
  }

  /**
   * Reset filter on a specific dimension.
   * Removes dimension from active filters and clears its filter.
   *
   * @param dimensionId - ID of the dimension to reset
   *
   * @example
   * ```ts
   * resetFilter('year'); // Clear year range filter
   * ```
   */
  function resetFilter(dimensionId: string): void {
    const dimension = dimensions.value.get(dimensionId);
    if (dimension) {
      dimension.filterAll();
      activeFilters.value.delete(dimensionId);
    }
  }

  /**
   * Reset all dimension filters.
   * Clears all active filters and returns to unfiltered state.
   *
   * @example
   * ```ts
   * resetAllFilters(); // Clear all filters
   * ```
   */
  function resetAllFilters(): void {
    dimensions.value.forEach((dimension) => {
      dimension.filterAll();
    });
    activeFilters.value.clear();
  }

  /**
   * Get all features that pass current filters.
   * Returns GeoJSON features array respecting all active dimension filters.
   *
   * @returns Array of filtered GeoJSON features
   *
   * @example
   * ```ts
   * const filteredFeatures = getAllFiltered();
   * console.log(`Showing ${filteredFeatures.length} results`);
   * ```
   */
  function getAllFiltered(): GeoJSON.Feature[] {
    if (!crossfilterInstance.value) return [];
    return crossfilterInstance.value.allFiltered();
  }

  /**
   * Get summary statistics for a dimension.
   * Returns count of filtered records and value extent (min/max).
   *
   * @param dimensionId - ID of the dimension to analyze
   * @returns Object with count and optional extent
   *
   * @example
   * ```ts
   * const stats = getDimensionStats('year');
   * console.log(`${stats.count} records from ${stats.extent[0]} to ${stats.extent[1]}`);
   * ```
   */
  function getDimensionStats(dimensionId: string): {
    count: number;
    extent?: [any, any];
  } {
    const dimension = dimensions.value.get(dimensionId);
    if (!dimension) {
      return { count: 0 };
    }

    const top = dimension.top(Infinity);
    const count = top.length;

    // Calculate extent for numeric dimensions
    if (count > 0) {
      const values = top
        .map((d) => dimension.accessor(d))
        .filter((v) => typeof v === "number");
      if (values.length > 0) {
        const min = Math.min(...values);
        const max = Math.max(...values);
        return { count, extent: [min, max] };
      }
    }

    return { count };
  }

  return {
    crossfilterInstance,
    dimensions,
    activeFilters,
    initializeCrossfilter,
    applyFilter,
    resetFilter,
    resetAllFilters,
    getAllFiltered,
    getDimensionStats,
  };
}
