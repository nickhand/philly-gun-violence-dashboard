/**
 * Composable for filter helper functions.
 *
 * Provides utilities for working with filter values, checking modifications,
 * and computing checkbox state changes.
 *
 * @module useFilterHelpers
 */

import type { FilterConfig } from "../types";

/**
 * Creates filter helper functions bound to the provided filters and active values.
 *
 * @param filters - Getter function for filter configurations
 * @param activeFilters - Getter function for active filter values map
 * @returns Object with filter helper functions
 *
 * @example
 * ```typescript
 * const filterHelpers = useFilterHelpers(
 *   () => props.filters,
 *   () => props.activeFilters
 * );
 *
 * const value = filterHelpers.getFilterValue('fatal');
 * const isModified = filterHelpers.isFilterModified('race');
 * ```
 */
export function useFilterHelpers(
  filters: () => FilterConfig[],
  activeFilters: () => Map<string, any>
) {
  /**
   * Get a filter config by ID.
   */
  function getFilter(filterId: string): FilterConfig | undefined {
    return filters().find((f) => f.name === filterId);
  }

  /**
   * Get the current value for a filter, falling back to default if not set.
   */
  function getFilterValue(filterId: string): any {
    const filter = getFilter(filterId);
    if (!filter) return undefined;

    const activeValue = activeFilters().get(filterId);
    if (activeValue === undefined || activeValue === null) {
      return filter.default;
    }
    return activeValue;
  }

  /**
   * Get slider value as a tuple, with fallback to filter default.
   */
  function getSliderValue(filter: FilterConfig): [number, number] {
    const value = activeFilters().get(filter.name);
    if (Array.isArray(value) && value.length === 2) {
      return value as [number, number];
    }
    return (filter.default as [number, number]) ?? [0, 100];
  }

  /**
   * Get slider min value from filter default.
   */
  function getSliderMin(filter: FilterConfig): number {
    if (Array.isArray(filter.default)) {
      return filter.default[0] as number;
    }
    return 0;
  }

  /**
   * Get slider max value from filter default.
   */
  function getSliderMax(filter: FilterConfig): number {
    if (Array.isArray(filter.default)) {
      return filter.default[1] as number;
    }
    return 100;
  }

  /**
   * Check if a filter has been modified from its default value.
   */
  function isFilterModified(filterId: string): boolean {
    const filter = getFilter(filterId);
    if (!filter) return false;

    const currentValue = activeFilters().get(filterId);
    if (currentValue === undefined || currentValue === null) return false;

    // For arrays, check if all default values are present
    if (Array.isArray(filter.default) && Array.isArray(currentValue)) {
      if (currentValue.length !== filter.default.length) return true;
      return !filter.default.every((v: any) => currentValue.includes(v));
    }

    return currentValue !== filter.default;
  }

  /**
   * Check if a specific checkbox value is selected.
   */
  function isCheckboxSelected(filterId: string, value: any): boolean {
    const filter = getFilter(filterId);
    const currentValue = activeFilters().get(filterId);

    // If no active filter, check against the default value
    if (currentValue === undefined || currentValue === null) {
      if (filter && Array.isArray(filter.default)) {
        return filter.default.includes(value);
      }
      return false;
    }

    if (!Array.isArray(currentValue)) return false;
    return currentValue.includes(value);
  }

  /**
   * Get the current checkbox values array for a filter.
   */
  function getCheckboxValues(filterId: string): any[] {
    const filter = getFilter(filterId);
    const activeValue = activeFilters().get(filterId);
    if (activeValue !== undefined) return activeValue;
    return (filter?.default as any[]) ?? [];
  }

  /**
   * Compute new checkbox array value when toggling a category.
   */
  function computeCheckboxChange(
    filterId: string,
    categoryValue: any,
    checked: boolean
  ): any[] {
    const currentValue = getCheckboxValues(filterId);

    if (checked) {
      return [...currentValue, categoryValue];
    } else {
      return currentValue.filter((v: any) => v !== categoryValue);
    }
  }

  /**
   * Check if any filters have been modified from defaults.
   */
  function hasAnyActiveFilters(): boolean {
    for (const filter of filters()) {
      if (isFilterModified(filter.name)) return true;
    }
    return false;
  }

  return {
    getFilter,
    getFilterValue,
    getSliderValue,
    getSliderMin,
    getSliderMax,
    isFilterModified,
    isCheckboxSelected,
    getCheckboxValues,
    computeCheckboxChange,
    hasAnyActiveFilters,
  };
}
