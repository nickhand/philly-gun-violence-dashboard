/**
 * Map Types and Interfaces
 *
 * Defines TypeScript types for map sources, layers, filters, and configuration.
 * Based on MapLibre GL JS and GeoJSON specifications.
 */

import type {
  GeoJSONSourceSpecification,
  LayerSpecification,
  CircleLayerSpecification,
  LineLayerSpecification,
  FillLayerSpecification,
  HeatmapLayerSpecification,
} from "maplibre-gl";

/**
 * Configuration for a GeoJSON data source in MapLibre GL.
 *
 * @example
 * ```ts
 * const shootingsSource: SourceConfig = {
 *   id: 'shootings',
 *   type: 'geojson',
 *   data: { type: 'FeatureCollection', features: [] }
 * };
 * ```
 */
export interface SourceConfig {
  /** Unique identifier for the source */
  id: string;
  /** Source type (always 'geojson' for our use case) */
  type: "geojson";
  /** GeoJSON data specification */
  data: GeoJSONSourceSpecification["data"];
}

/**
 * Tooltip configuration for map layers.
 */
export interface TooltipConfig {
  /** When to show tooltip: 'mouseenter', 'click', or 'mousemove' */
  on: "mouseenter" | "click" | "mousemove";
  /** Function to format tooltip HTML from feature properties */
  formatter: (properties: Record<string, any>) => string;
}

/**
 * Legend configuration for aggregated layers with color scales.
 */
export interface LegendConfig {
  /** D3 color scheme name (e.g., 'Viridis', 'Plasma', 'Inferno') */
  colorScheme: string;
  /** Scale type for mapping values to colors */
  scaleName: "Linear" | "Log" | "Sqrt" | "Quantile";
  /** Range of color scheme to use [0-1], e.g., [0.5, 1] uses second half */
  colorRange?: [number, number];
}

/**
 * Configuration for a map layer that renders from a source.
 * Based on the Vue2 LayerConfig pattern with support for aggregated layers.
 *
 * @example
 * ```ts
 * // Simple point layer
 * const pointsLayer: LayerConfig = {
 *   name: 'Point locations',
 *   source: 'shootings',
 *   type: 'circle',
 *   aggregated: false,
 *   showOnStart: true,
 *   paint: {
 *     'circle-radius': 6,
 *     'circle-color': '#e74c3c'
 *   }
 * };
 *
 * // Aggregated choropleth layer
 * const policeDistrictLayer: LayerConfig = {
 *   name: 'Police District',
 *   source: 'police-district-geo',
 *   type: 'fill',
 *   aggregated: true,
 *   choropleth: true,
 *   column: 'police_district',
 *   geoid: 'police_district',
 *   tooltip: {
 *     formatter: (d) => `<div>District ${d.police_district}: ${d.count} incidents</div>`,
 *     on: 'mousemove'
 *   }
 * };
 * ```
 */
export interface LayerConfig {
  /** Display name for the layer (shown in legend/controls) */
  name: string;
  /** Source ID this layer renders from */
  source: string;
  /** MapLibre GL layer type */
  type: "circle" | "line" | "fill" | "heatmap";
  /** Whether this is an aggregated layer requiring data joins */
  aggregated: boolean;
  /** Paint properties for the layer */
  paint?:
    | CircleLayerSpecification["paint"]
    | LineLayerSpecification["paint"]
    | FillLayerSpecification["paint"]
    | HeatmapLayerSpecification["paint"];
  /** Layout properties for the layer */
  layout?: LayerSpecification["layout"];
  /** ID of layer to insert this layer before */
  beforeId?: string;
  /** Whether to show this layer when map loads */
  showOnStart?: boolean;
  /** Whether this is a choropleth layer (boundary fill for aggregation dropdown) */
  choropleth?: boolean;
  /** Whether this is a static layer (not affected by filters) */
  static?: boolean;
  /** Data column name for aggregation joins */
  column?: string;
  /** Geographic ID field for joining aggregated data */
  geoid?: string;
  /** Tooltip configuration */
  tooltip?: TooltipConfig;
  /** Legend configuration for choropleth layers */
  legend?: LegendConfig;
}

/**
 * Configuration for a map layer using full MapLibre LayerSpecification.
 * This is the simpler wrapper that just adds metadata to the spec.
 *
 * @deprecated Use LayerConfig for new code (Vue2 pattern)
 *
 * @example
 * ```ts
 * const shootingsLayer: LayerConfigSpec = {
 *   id: 'shootings-points',
 *   source: 'shootings',
 *   spec: {
 *     id: 'shootings-points',
 *     type: 'circle',
 *     source: 'shootings',
 *     paint: {
 *       'circle-radius': 6,
 *       'circle-color': '#e74c3c'
 *     }
 *   }
 * };
 * ```
 */
export interface LayerConfigSpec {
  /** Unique identifier matching the layer spec ID */
  id: string;
  /** Source ID this layer renders from */
  source: string;
  /** MapLibre GL layer specification */
  spec: LayerSpecification;
}

/**
 * Configuration for aggregated data layers (e.g., hex grids, choropleth).
 * Requires aggregation function to compute from filtered data.
 *
 * @deprecated Use LayerConfig with aggregated: true instead
 *
 * @example
 * ```ts
 * const hexGridLayer: AggregatedLayerConfig = {
 *   id: 'shootings-hex',
 *   source: 'shootings-hex',
 *   spec: { ... },
 *   aggregationFn: (features) => aggregateToHexGrid(features, 8)
 * };
 * ```
 */
export interface AggregatedLayerConfig extends LayerConfigSpec {
  /**
   * Function that aggregates filtered GeoJSON features into new GeoJSON.
   * Called whenever filters change to recompute aggregated geometry.
   *
   * @param features - Filtered GeoJSON features from Arquero
   * @returns GeoJSON FeatureCollection with aggregated geometries
   */
  aggregationFn: (features: GeoJSON.Feature[]) => GeoJSON.FeatureCollection;
}

/**
 * Filter dimension type definitions.
 * Determines UI control type and filter logic.
 */
export type FilterType =
  | "range" // Two-handle slider for numeric ranges
  | "slider" // Single range slider
  | "select" // Single-select dropdown
  | "multiselect" // Multi-select with chips
  | "checkbox" // Boolean checkbox or checkbox group
  | "switch" // Boolean toggle switch
  | "date-range"; // Date range picker

/**
 * Filter function type for applying filters to data values.
 *
 * @param value - The current filter value from UI
 * @param excludeMissing - Whether to exclude null/undefined values
 * @returns Filter predicate function or value range tuple
 */
export type FilterFunction = (
  value: any,
  excludeMissing?: boolean,
) => any | ((d: any) => boolean);

/**
 * Tooltip configuration for filter controls.
 */
export interface FilterTooltipConfig {
  /** Function to format the tooltip value */
  formatter: (value: any) => string;
}

/**
 * Checkbox category option for checkbox group filters.
 */
export interface CheckboxCategory {
  /** Value stored when selected */
  value: string | number;
  /** Display text shown to user */
  text: string;
}

/**
 * Configuration for a single filter dimension.
 * Controls how data is filtered and which UI control is shown.
 * Based on the Vue2 FilterConfig pattern.
 *
 * @example
 * ```ts
 * // Range slider filter
 * const yearFilter: FilterConfig = {
 *   name: 'year',
 *   label: 'Year',
 *   kind: 'slider',
 *   property: 'year',
 *   default: [2015, 2025],
 *   getFilter: (value) => [value[0], value[1] + 1],
 *   showHistogram: true,
 *   autoLimits: false
 * };
 *
 * // Checkbox group filter
 * const raceFilter: FilterConfig = {
 *   name: 'race',
 *   label: 'Race/Ethnicity',
 *   kind: 'checkbox',
 *   getFilter: (value) => (d) => value.indexOf(d) !== -1,
 *   categories: [
 *     { value: 'W', text: 'White (Non-Hispanic)' },
 *     { value: 'B', text: 'Black (Non-Hispanic)' }
 *   ],
 *   default: ['W', 'B'],
 *   ncol: 1
 * };
 *
 * // Switch filter
 * const fatalFilter: FilterConfig = {
 *   name: 'fatal',
 *   label: 'Fatal shootings only',
 *   kind: 'switch',
 *   getFilter: (value) => value ? true : null,
 *   default: false
 * };
 * ```
 */
export interface FilterConfig {
  /** Unique identifier for this filter dimension (property name in data) */
  name: string;
  /** Display label shown in UI */
  label: string;
  /** UI control type (kind instead of type to match Vue2) */
  kind: FilterType;
  /** Function that converts UI value to filter predicate or range */
  getFilter: FilterFunction;
  /** Default value for the filter */
  default?: any;

  // Range/Slider specific
  /** Whether to show histogram in slider */
  showHistogram?: boolean;
  /** Whether to automatically calculate min/max from data */
  autoLimits?: boolean;
  /** Whether to exclude null/undefined values */
  excludeMissing?: boolean;
  /** Tooltip configuration for slider values */
  tooltip?: FilterTooltipConfig;

  // Checkbox specific
  /** Available categories for checkbox group */
  categories?: CheckboxCategory[];
  /** Number of columns for checkbox layout */
  ncol?: number;
}

/**
 * Configuration for data download functionality.
 * Defines available download formats and transformation logic.
 *
 * @example
 * ```ts
 * const downloadConfig: DownloadConfig = {
 *   formats: ['geojson', 'csv'],
 *   filename: 'shootings-filtered',
 *   transformers: {
 *     csv: (features) => convertToCSV(features)
 *   }
 * };
 * ```
 */
export interface DownloadConfig {
  /** Supported export formats */
  formats: Array<"geojson" | "csv" | "json">;
  /** Base filename for downloads (extension added automatically) */
  filename: string;
  /** Optional format-specific transformation functions */
  transformers?: {
    [format: string]: (features: GeoJSON.Feature[]) => string | Blob;
  };
}

/**
 * Parameters passed to data download handler.
 * Contains filtered features and format selection.
 */
export interface DataDownloadParams {
  /** Filtered GeoJSON features to export */
  features: GeoJSON.Feature[];
  /** Selected export format */
  format: "geojson" | "csv" | "json";
  /** Output filename */
  filename: string;
}

/**
 * Histogram bin data for slider filter charts.
 * Represents a single bin in a histogram distribution.
 */
export interface HistogramBin {
  /** Bin start value (inclusive) */
  x0: number;
  /** Bin end value (exclusive) */
  x1: number;
  /** Count of values in this bin */
  length: number;
}
