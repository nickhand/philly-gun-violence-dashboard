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
import { bin } from "d3-array";
import type { FilterConfig, HistogramBin } from "../types";

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
  /** Data-driven slider limits for autoLimits filters */
  sliderLimits: Ref<Map<string, [number, number]>>;
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
  /** Get histogram data for a dimension (excluding its own filter) */
  getHistogramData: (dimensionId: string, numBins?: number) => HistogramBin[];
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
  const sliderLimits = ref<Map<string, [number, number]>>(new Map());

  // Store filter configs to access getFilter transformations
  const filterConfigsMap = ref<Map<string, FilterConfig>>(new Map());

  // Version counter to trigger reactivity when filters change
  // Increment this whenever the crossfilter state changes to make computed properties update
  const filterVersion = ref(0);

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

    // Clear existing dimensions and configs
    dimensions.value.clear();
    activeFilters.value.clear();
    filterConfigsMap.value.clear();
    sliderLimits.value.clear();

    // Create dimension for each filter configuration
    filterConfigs.forEach((config) => {
      // Store the config for later use in getFilter transformation
      filterConfigsMap.value.set(config.name, config);
      const dimension = crossfilterInstance.value!.dimension(
        (d: GeoJSON.Feature) => {
          // Access property from feature.properties using config.name
          return d.properties?.[config.name];
        }
      );
      dimensions.value.set(config.name, dimension);

      // For autoLimits slider filters, compute min/max from data
      if (config.kind === "slider" && config.autoLimits) {
        const top = dimension.top(1);
        const bottom = dimension.bottom(1);
        if (top.length > 0 && bottom.length > 0) {
          const max = top[0].properties?.[config.name];
          const min = bottom[0].properties?.[config.name];
          if (typeof min === "number" && typeof max === "number") {
            sliderLimits.value.set(config.name, [min, max]);
          }
        }
      }
    });

    // Trigger reactivity
    filterVersion.value++;
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
   *                - Object with value and excludeMissing for slider filters
   *
   * @example
   * ```ts
   * applyFilter('year', [2020, 2023]); // Range filter
   * applyFilter('district', 'Central'); // Select filter
   * applyFilter('fatal', true); // Checkbox filter
   * applyFilter('age', { value: [0, 100], excludeMissing: true }); // Slider with excludeMissing
   * ```
   */
  function applyFilter(dimensionId: string, value: any): void {
    const dimension = dimensions.value.get(dimensionId);
    if (!dimension) {
      console.warn(`Dimension ${dimensionId} not found`);
      return;
    }

    // Get the filter config to use its getFilter transformation
    const filterConfig = filterConfigsMap.value.get(dimensionId);

    // Handle object format with excludeMissing (from slider filters)
    // Check for non-array object with excludeMissing property
    let filterValue = value;
    let excludeMissing = false;
    if (
      value &&
      typeof value === "object" &&
      !Array.isArray(value) &&
      "excludeMissing" in value
    ) {
      filterValue = value.value;
      excludeMissing = value.excludeMissing ?? false;
    }

    // Store the UI value (not the transformed value)
    activeFilters.value.set(dimensionId, filterValue);

    // Transform the value using the filter's getFilter function if available
    const transformedValue = filterConfig?.getFilter
      ? filterConfig.getFilter(filterValue, excludeMissing)
      : filterValue;

    // Apply filter based on transformed value
    if (transformedValue === null || transformedValue === undefined) {
      // Clear filter if transformed value is null/undefined
      dimension.filterAll();
      activeFilters.value.delete(dimensionId);
    } else if (typeof transformedValue === "function") {
      // Custom filter function returned by getFilter
      dimension.filterFunction(transformedValue);
    } else if (Array.isArray(transformedValue)) {
      // Range filter: [min, max]
      if (
        transformedValue.length === 2 &&
        typeof transformedValue[0] === "number"
      ) {
        dimension.filterRange(transformedValue as [number, number]);
      }
      // Multiselect filter: array of values
      else {
        dimension.filterFunction((d) => transformedValue.includes(d));
      }
    } else if (typeof transformedValue === "boolean") {
      // Checkbox filter
      dimension.filterExact(transformedValue);
    } else {
      // Single value filter
      dimension.filterExact(transformedValue);
    }

    // Trigger reactivity
    filterVersion.value++;
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
      // Trigger reactivity
      filterVersion.value++;
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
    // Trigger reactivity
    filterVersion.value++;
  }

  /**
   * Get all features that pass current filters.
   * Returns GeoJSON features array respecting all active dimension filters.
   *
   * Note: This function reads filterVersion.value to establish a reactive
   * dependency. When filters change, filterVersion increments, causing
   * computed properties that call this function to re-evaluate.
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
    // Read filterVersion to establish reactive dependency
    // eslint-disable-next-line @typescript-eslint/no-unused-expressions
    filterVersion.value;

    if (!crossfilterInstance.value) {
      return [];
    }
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

  /**
   * Get histogram data for a dimension, excluding its own filter.
   * This allows the histogram to show the full distribution regardless of
   * the current slider position.
   *
   * @param dimensionId - ID of the dimension to get histogram for
   * @param numBins - Number of bins for the histogram (default 30)
   * @returns Array of histogram bins with x0, x1, and length
   *
   * @example
   * ```ts
   * const bins = getHistogramData('age', 20);
   * // Returns: [{ x0: 0, x1: 5, length: 10 }, ...]
   * ```
   */
  function getHistogramData(
    dimensionId: string,
    numBins: number = 30
  ): HistogramBin[] {
    // Read filterVersion to establish reactive dependency
    // eslint-disable-next-line @typescript-eslint/no-unused-expressions
    filterVersion.value;

    if (!crossfilterInstance.value) {
      return [];
    }

    const dimension = dimensions.value.get(dimensionId);
    if (!dimension) {
      return [];
    }

    // Get all filtered data, but exclude this dimension's filter
    // This shows the full distribution for this dimension
    // @ts-expect-error crossfilter2 types don't include allFiltered with ignore param
    const filteredData = crossfilterInstance.value.allFiltered([dimension]);

    // Extract numeric values for this dimension
    const values = filteredData
      .map((d: GeoJSON.Feature) => d.properties?.[dimensionId])
      .filter((v): v is number => typeof v === "number" && !isNaN(v));

    if (values.length === 0) {
      return [];
    }

    // Use d3 bin to create histogram
    const histogram = bin<number>().thresholds(numBins);
    const bins = histogram(values);

    // Convert d3 bins to our HistogramBin format
    return bins.map((b) => ({
      x0: b.x0 ?? 0,
      x1: b.x1 ?? 0,
      length: b.length,
    }));
  }

  return {
    crossfilterInstance,
    dimensions,
    activeFilters,
    sliderLimits,
    initializeCrossfilter,
    applyFilter,
    resetFilter,
    resetAllFilters,
    getAllFiltered,
    getDimensionStats,
    getHistogramData,
  };
}
