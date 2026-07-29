/**
 * Aggregation composable.
 *
 * Handles D3 color scale creation and applying aggregation colors
 * to GeoJSON features based on filtered data counts.
 *
 * @module useAggregation
 */

import { ref, type Ref } from "vue";
import { rollup, extent } from "d3-array";
import {
  scaleLinear,
  scaleLog,
  type ScaleLinear,
  type ScaleLogarithmic,
} from "d3-scale";
import { getColorInterpolator } from "../config/colorSchemes";
import type { LayerConfig } from "../types";

/**
 * Legend configuration for display.
 */
export interface LegendConfig {
  colorScheme: string;
  range: [number, number];
  domain: [number, number];
  title: string;
}

/**
 * Scale name to d3 scale function mapping.
 */
const SCALE_FUNCTIONS: Record<string, typeof scaleLinear> = {
  Log: scaleLog as typeof scaleLinear,
  Linear: scaleLinear,
  Sequential: scaleLinear,
};

/**
 * Color for boundaries with zero count (neutral gray).
 */
const ZERO_COUNT_COLOR = "#cccccc";

/**
 * Composable for aggregation and color scaling.
 *
 * @param filteredFeaturesRef - Reactive ref to filtered features
 * @returns Aggregation methods and legend state
 *
 * @example
 * ```typescript
 * const { applyAggregationColors, legendConfig, showLegend, hideLegend } =
 *   useAggregation(filteredFeatures);
 *
 * const coloredFeatures = applyAggregationColors(config, sourceFeatures);
 * ```
 */
export function useAggregation(filteredFeaturesRef: Ref<GeoJSON.Feature[]>) {
  // Legend state
  const legendConfig = ref<LegendConfig | null>(null);
  const legendVisible = ref(false);

  /**
   * Create a scale function for mapping counts to color range.
   *
   * @param scaleName - Scale type ("Log", "Linear", "Sequential")
   * @param domain - Data domain [min, max]
   * @param range - Output range [0, 1]
   * @returns Scale function
   */
  function createScale(
    scaleName: string,
    domain: [number, number],
    range: [number, number]
  ):
    | ScaleLinear<number, number>
    | ScaleLogarithmic<number, number> {
    const scaleFunction = SCALE_FUNCTIONS[scaleName] ?? scaleLinear;

    // For log scale, ensure domain doesn't include 0 (log(0) is undefined)
    const safeDomain: [number, number] =
      scaleName === "Log" ? [Math.max(1, domain[0]), domain[1]] : domain;

    return scaleFunction().domain(safeDomain).range(range).clamp(true);
  }

  /**
   * Aggregate filtered features by a column and get counts.
   *
   * @param column - Property name to aggregate by
   * @returns Map of column value to count
   */
  function aggregateByColumn(column: string): Map<unknown, number> {
    return rollup(
      filteredFeaturesRef.value.filter((d) => d.properties?.[column]),
      (v: GeoJSON.Feature[]) => v.length,
      (d: GeoJSON.Feature) => d.properties![column]
    );
  }

  /**
   * Apply aggregation colors to source features.
   *
   * Aggregates filtered data by the layer's column, computes counts,
   * and applies a d3 color scale to each feature.
   *
   * @param config - Layer configuration with aggregation settings
   * @param sourceFeatures - GeoJSON features for the source
   * @returns Updated features with color and count properties
   */
  function applyAggregationColors(
    config: LayerConfig,
    sourceFeatures: GeoJSON.Feature[]
  ): GeoJSON.Feature[] {
    const column = config.column;
    const geoid = config.geoid;
    const legend = config.legend;

    if (!column || !geoid) {
      console.warn("Layer config missing column or geoid for aggregation");
      return sourceFeatures;
    }

    // Aggregate filtered features by column
    const aggData = aggregateByColumn(column);

    // Get color scheme from legend config
    const colorScheme = legend?.colorScheme ?? "Reds";
    const colorRange = legend?.colorRange ?? [0, 1];
    const scaleName = legend?.scaleName ?? "Sequential";

    // Get the d3 color interpolator
    const colorInterpolator = getColorInterpolator(colorScheme);
    if (!colorInterpolator) {
      console.error(`Color scheme ${colorScheme} not found`);
      return sourceFeatures;
    }

    // Compute domain from aggregated counts
    const aggArray = Array.from(aggData, ([, count]) => count);
    const domain = extent(aggArray, (d: number) => d) as [number, number];
    if (domain[0] === undefined || domain[1] === undefined) {
      console.warn("Could not compute domain for aggregated layer");
      return sourceFeatures;
    }

    // Create the scale
    const scale = createScale(
      scaleName,
      domain,
      colorRange as [number, number]
    );

    // Helper to get color from count
    const getColor = (count: number): string =>
      colorInterpolator(scale(count) as number);

    // Update features with color and count properties
    const updatedFeatures = sourceFeatures.map((feature) => {
      const id = feature.properties?.[geoid];
      const count = aggData.get(id) ?? 0;
      const color = count > 0 ? getColor(count) : ZERO_COUNT_COLOR;

      return {
        ...feature,
        properties: {
          ...feature.properties,
          color,
          count,
        },
      };
    });

    // Update legend config (but don't auto-show - let caller control visibility)
    legendConfig.value = {
      colorScheme,
      range: colorRange as [number, number],
      domain,
      title: "Total Shooting Victims",
    };

    return updatedFeatures;
  }

  /**
   * Hide the legend.
   */
  function hideLegend(): void {
    legendVisible.value = false;
  }

  return {
    // State
    legendConfig,
    legendVisible,
    // Methods
    applyAggregationColors,
    aggregateByColumn,
    hideLegend,
  };
}
