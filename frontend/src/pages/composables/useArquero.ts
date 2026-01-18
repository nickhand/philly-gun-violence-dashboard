/**
 * Arquero Composable
 *
 * Manages multi-dimensional filtering of tabular data using Arquero.
 * Provides reactive filter state and efficient dimension queries.
 *
 * @module useArquero
 */

import { ref, computed, type Ref, type ComputedRef, markRaw } from "vue";
import * as aq from "arquero";
import { bin } from "d3-array";
import type {
  FilterConfig,
  HistogramBin,
} from "@/features/filterableMap/types";
import type { ShootingRow } from "@/shared/types/shootings";
import {
  rowsToGeoJSON,
  type ShootingFeature,
} from "@/shared/utils/rowsToGeoJSON";

// Arquero table type - use any due to complex internal types
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ColumnTable = any;

/**
 * Filter values for the active filters map.
 */
export type FilterValue =
  | boolean
  | number
  | string
  | number[]
  | string[]
  | { value: number[]; excludeMissing: boolean };

/**
 * Arquero composable return type.
 * Provides table instance, filter operations, and derived data.
 */
interface UseArqueroReturn {
  /** Base Arquero table (unfiltered) */
  baseTable: Ref<ColumnTable | null>;
  /** Active filter values keyed by dimension name */
  activeFilters: Ref<Map<string, FilterValue>>;
  /** Data-driven slider limits for autoLimits filters */
  sliderLimits: Ref<Map<string, [number, number]>>;
  /** Filter configurations */
  filterConfigs: Ref<FilterConfig[]>;
  /** Filtered table (reactive, computed from base + filters) */
  filteredTable: ComputedRef<ColumnTable | null>;
  /** Filtered rows as array (reactive) */
  filteredRows: ComputedRef<ShootingRow[]>;
  /** Filtered features as GeoJSON (for map, reactive) */
  filteredFeatures: ComputedRef<ShootingFeature[]>;
  /** Initialize with row data and filter configs */
  initialize: (rows: ShootingRow[], configs: FilterConfig[]) => void;
  /** Apply filter to a dimension */
  applyFilter: (dimensionId: string, value: FilterValue) => void;
  /** Reset a specific dimension filter */
  resetFilter: (dimensionId: string) => void;
  /** Reset all dimension filters */
  resetAllFilters: () => void;
  /** Get histogram data for a dimension (excluding its own filter) */
  getHistogramData: (dimensionId: string, numBins?: number) => HistogramBin[];
  /** Get count of rows for each category value */
  getCategoryCounts: (dimensionId: string) => Map<string | number, number>;
}

/**
 * Creates an Arquero-based filtering system for tabular row data.
 *
 * Usage:
 * ```ts
 * const {
 *   baseTable,
 *   activeFilters,
 *   filteredFeatures,
 *   initialize,
 *   applyFilter,
 *   resetAllFilters,
 * } = useArquero();
 *
 * // Initialize with data
 * initialize(shootingsRows, filterConfigs);
 *
 * // Apply filters
 * applyFilter('fatal', true);
 * applyFilter('race', ['B', 'H']);
 *
 * // Get filtered results (reactive)
 * const features = filteredFeatures.value;
 * ```
 *
 * @returns {UseArqueroReturn} Arquero state and operations
 */
export function useArquero(): UseArqueroReturn {
  const baseTable = ref<ColumnTable | null>(null);
  const activeFilters = ref<Map<string, FilterValue>>(new Map());
  const sliderLimits = ref<Map<string, [number, number]>>(new Map());
  const filterConfigs = ref<FilterConfig[]>([]);

  // Store filter configs map for quick lookup
  const filterConfigsMap = ref<Map<string, FilterConfig>>(new Map());

  // Version counter to trigger reactivity when filters change
  const filterVersion = ref(0);

  /**
   * Initialize Arquero table with row data and create filter configurations.
   *
   * @param rows - Array of shooting row objects
   * @param configs - Filter configurations defining dimensions
   */
  function initialize(rows: ShootingRow[], configs: FilterConfig[]): void {
    const startTime = performance.now();

    // Create Arquero table from rows
    // Mark as raw to prevent Vue from making the table deeply reactive
    const tableStart = performance.now();
    baseTable.value = markRaw(aq.from(rows));
    if (import.meta.env.DEV) {
      console.log(
        `[Arquero] Table created from ${rows.length} rows in ${(performance.now() - tableStart).toFixed(1)}ms`,
      );
    }

    // Store filter configs
    filterConfigs.value = configs;
    filterConfigsMap.value.clear();
    activeFilters.value.clear();
    sliderLimits.value.clear();

    // Process each filter config
    configs.forEach((config) => {
      filterConfigsMap.value.set(config.name, config);

      // For autoLimits slider filters, compute min/max from data
      if (config.kind === "slider" && config.autoLimits && baseTable.value) {
        const stats = baseTable.value
          .rollup({
            min: aq.op.min(config.name),
            max: aq.op.max(config.name),
          })
          .object() as { min: number; max: number };

        if (
          typeof stats.min === "number" &&
          typeof stats.max === "number" &&
          !isNaN(stats.min) &&
          !isNaN(stats.max)
        ) {
          sliderLimits.value.set(config.name, [stats.min, stats.max]);
        }
      }
    });

    // Trigger reactivity
    filterVersion.value++;

    if (import.meta.env.DEV) {
      console.log(
        `[Arquero] Initialization complete in ${(performance.now() - startTime).toFixed(1)}ms`,
      );
    }
  }

  /**
   * Apply filter to a specific dimension.
   *
   * @param dimensionId - ID of the dimension to filter
   * @param value - Filter value
   */
  function applyFilter(dimensionId: string, value: FilterValue): void {
    activeFilters.value.set(dimensionId, value);
    // Trigger reactivity
    filterVersion.value++;
  }

  /**
   * Reset filter on a specific dimension.
   *
   * @param dimensionId - ID of the dimension to reset
   */
  function resetFilter(dimensionId: string): void {
    activeFilters.value.delete(dimensionId);
    // Trigger reactivity
    filterVersion.value++;
  }

  /**
   * Reset all dimension filters.
   */
  function resetAllFilters(): void {
    activeFilters.value.clear();
    // Trigger reactivity
    filterVersion.value++;
  }

  /**
   * Apply all active filters to the base table.
   * Returns the filtered table.
   */
  function applyAllFilters(
    table: ColumnTable,
    excludeDimension?: string,
  ): ColumnTable {
    let result = table;

    for (const [dimensionId, value] of activeFilters.value.entries()) {
      // Skip the excluded dimension (for histogram calculations)
      if (excludeDimension && dimensionId === excludeDimension) {
        continue;
      }

      const config = filterConfigsMap.value.get(dimensionId);
      if (!config) continue;

      // Handle object format with excludeMissing (from slider filters)
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

      // Transform the value using the filter's getFilter function if available
      const transformedValue = config.getFilter
        ? config.getFilter(filterValue, excludeMissing)
        : filterValue;

      // Skip null/undefined transformed values (means "no filter")
      if (transformedValue === null || transformedValue === undefined) {
        continue;
      }

      // Apply filter based on transformed value type
      if (typeof transformedValue === "function") {
        // Custom filter function - apply as predicate
        result = result.filter(
          aq.escape((d: Record<string, unknown>) =>
            transformedValue(d[dimensionId]),
          ),
        );
      } else if (Array.isArray(transformedValue)) {
        if (
          transformedValue.length === 2 &&
          typeof transformedValue[0] === "number" &&
          typeof transformedValue[1] === "number"
        ) {
          // Range filter: [min, max]
          const [min, max] = transformedValue;
          result = result.filter(
            aq.escape(
              (d: Record<string, unknown>) =>
                (d[dimensionId] as number) >= min &&
                (d[dimensionId] as number) <= max,
            ),
          );
        } else {
          // Multiselect filter: array of values
          const allowedValues = new Set(transformedValue);
          result = result.filter(
            aq.escape((d: Record<string, unknown>) =>
              allowedValues.has(d[dimensionId] as string | number),
            ),
          );
        }
      } else if (typeof transformedValue === "boolean") {
        // Boolean exact match
        result = result.filter(
          aq.escape(
            (d: Record<string, unknown>) => d[dimensionId] === transformedValue,
          ),
        );
      } else {
        // Single value exact match
        result = result.filter(
          aq.escape(
            (d: Record<string, unknown>) => d[dimensionId] === transformedValue,
          ),
        );
      }
    }

    return result;
  }

  /**
   * Computed filtered table - automatically updates when filters change.
   */
  const filteredTable = computed<ColumnTable | null>(() => {
    // Read filterVersion to establish reactive dependency
    // eslint-disable-next-line @typescript-eslint/no-unused-expressions
    filterVersion.value;

    if (!baseTable.value) {
      return null;
    }

    return applyAllFilters(baseTable.value);
  });

  /**
   * Computed filtered rows as array.
   */
  const filteredRows = computed<ShootingRow[]>(() => {
    if (!filteredTable.value) {
      return [];
    }
    return filteredTable.value.objects() as ShootingRow[];
  });

  /**
   * Convert filtered rows to GeoJSON features for map rendering.
   * Uses rowsToGeoJSON to include only the properties needed for tooltip/styling.
   */
  const filteredFeatures = computed<ShootingFeature[]>(() => {
    const rows = filteredRows.value;
    const fc = rowsToGeoJSON(rows);
    return fc.features;
  });

  /**
   * Get histogram data for a dimension, excluding its own filter.
   *
   * @param dimensionId - ID of the dimension to get histogram for
   * @param numBins - Number of bins for the histogram (default 30)
   * @returns Array of histogram bins
   */
  function getHistogramData(
    dimensionId: string,
    numBins: number = 30,
  ): HistogramBin[] {
    // Read filterVersion to establish reactive dependency
    // eslint-disable-next-line @typescript-eslint/no-unused-expressions
    filterVersion.value;

    if (!baseTable.value) {
      return [];
    }

    // Get all filtered data, but exclude this dimension's filter
    const filteredData = applyAllFilters(baseTable.value, dimensionId);

    // Extract numeric values for this dimension
    const column = filteredData.array(dimensionId) as (number | null)[];
    const values = column.filter(
      (v): v is number => typeof v === "number" && !isNaN(v),
    );

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

  /**
   * Get count of rows for each category value in a dimension.
   * Useful for showing counts in checkbox/multiselect filters.
   *
   * @param dimensionId - ID of the dimension to count
   * @returns Map of category value to count
   */
  function getCategoryCounts(
    dimensionId: string,
  ): Map<string | number, number> {
    // Read filterVersion to establish reactive dependency
    // eslint-disable-next-line @typescript-eslint/no-unused-expressions
    filterVersion.value;

    if (!filteredTable.value) {
      return new Map();
    }

    const grouped = filteredTable.value
      .groupby(dimensionId)
      .count()
      .objects() as Array<{ [key: string]: unknown; count: number }>;

    const counts = new Map<string | number, number>();
    for (const row of grouped) {
      const key = row[dimensionId] as string | number;
      counts.set(key, row.count);
    }
    return counts;
  }

  return {
    baseTable,
    activeFilters,
    sliderLimits,
    filterConfigs,
    filteredTable,
    filteredRows,
    filteredFeatures,
    initialize,
    applyFilter,
    resetFilter,
    resetAllFilters,
    getHistogramData,
    getCategoryCounts,
  };
}
