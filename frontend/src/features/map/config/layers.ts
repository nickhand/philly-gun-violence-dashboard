import type { LayerConfig } from "../types";
import {
  createAggregatedLayerTooltip,
  createPointsLayerTooltip,
  createStreetBlockTooltip,
} from "./tooltips";

/**
 * Get the circle radius style based on selected year.
 *
 * Uses smaller circles when showing all years to reduce visual clutter.
 *
 * @param selectedYear - Currently selected year (null = all years)
 * @returns MapLibre GL expression for circle-radius
 */
export function getCircleRadiusStyle(selectedYear: number | null): any[] {
  if (selectedYear === null) {
    return ["interpolate", ["exponential", 1.25], ["zoom"], 10, 1, 16, 9];
  } else {
    return ["interpolate", ["exponential", 1.25], ["zoom"], 10, 3.5, 16, 11];
  }
}

/**
 * Get layer configurations for the map.
 *
 * Returns an array of layer definitions including points, heatmaps, choropleth
 * overlays, and static boundaries.
 *
 * @param selectedYear - Currently selected year (affects point sizes)
 * @returns Array of layer configurations
 *
 * @example
 * ```typescript
 * const layers = getLayerConfigs(2024);
 * // Use in map initialization
 * ```
 */
export function getLayerConfigs(selectedYear: number | null): LayerConfig[] {
  return [
    {
      name: "Police Districts",
      source: "boundary-police-districts",
      type: "fill",
      aggregated: true,
      overlay: true,
      column: "police_district",
      geoid: "police_district",
      tooltip: {
        formatter: createAggregatedLayerTooltip(
          (d) => `Police District #${d.police_district}`
        ),
        on: "mousemove",
      },
    },
    {
      name: "Council Districts",
      source: "boundary-council-districts",
      type: "fill",
      aggregated: true,
      overlay: true,
      column: "council_district",
      geoid: "council_district",
      tooltip: {
        formatter: createAggregatedLayerTooltip(
          (d) => `Council District #${d.council_district}`
        ),
        on: "mousemove",
      },
    },
    {
      name: "ZIP Codes",
      source: "boundary-zip-codes",
      type: "fill",
      aggregated: true,
      overlay: true,
      column: "zip_code",
      geoid: "zip_code",
      tooltip: {
        formatter: createAggregatedLayerTooltip((d) => `${d.zip_code}`),
        on: "mousemove",
      },
    },
    {
      name: "Neighborhoods",
      source: "boundary-neighborhoods",
      type: "fill",
      aggregated: true,
      overlay: true,
      column: "neighborhood",
      geoid: "neighborhood",
      tooltip: {
        formatter: createAggregatedLayerTooltip(
          (d) => d.neighborhood as string
        ),
        on: "mousemove",
      },
    },
    {
      name: "PA House Districts",
      source: "boundary-pa-house-districts",
      type: "fill",
      aggregated: true,
      overlay: true,
      column: "house_district",
      geoid: "house_district",
      tooltip: {
        formatter: createAggregatedLayerTooltip(
          (d) => `House District #${d.house_district}`
        ),
        on: "mousemove",
      },
    },
    {
      name: "PA Senate Districts",
      source: "boundary-pa-senate-districts",
      type: "fill",
      aggregated: true,
      overlay: true,
      column: "senate_district",
      geoid: "senate_district",
      tooltip: {
        formatter: createAggregatedLayerTooltip(
          (d) => `Senate District #${d.senate_district}`
        ),
        on: "mousemove",
      },
    },
    {
      name: "School Catchments",
      source: "boundary-school-catchments",
      type: "fill",
      aggregated: true,
      overlay: true,
      column: "school_name",
      geoid: "school_name",
      tooltip: {
        formatter: createAggregatedLayerTooltip((d) => `${d.school_name}`),
        on: "mousemove",
      },
    },
    {
      name: "City Limits",
      source: "boundary-city-limits",
      type: "line",
      aggregated: false,
      static: true,
      paint: { "line-width": 4, "line-color": "#ffffff", "line-opacity": 1 },
      showOnStart: true,
    },
    {
      name: "Point locations",
      source: "shootings",
      type: "circle",
      aggregated: false,
      showOnStart: true,
      paint: {
        "circle-radius": getCircleRadiusStyle(selectedYear) as any,
        "circle-color": [
          "case",
          ["boolean", ["get", "fatal"], false],
          "#d84545",
          "#e5dc8e",
        ],
        "circle-stroke-width": 1,
        "circle-opacity": 0.7,
        "circle-stroke-color": [
          "case",
          ["boolean", ["get", "fatal"], false],
          "#af2828",
          "#d3c913",
        ],
      },
      tooltip: {
        on: "mouseenter",
        formatter: createPointsLayerTooltip,
      },
    },
    {
      name: "Heat map",
      source: "shootings",
      type: "heatmap",
      aggregated: false,
      beforeId: "Point locations",
      paint: {
        "heatmap-intensity": {
          stops: [
            [11, 1],
            [15, 5],
          ],
        } as any,
        "heatmap-color": [
          "interpolate",
          ["linear"],
          ["heatmap-density"],
          0,
          "rgba(0, 0, 0, 0)",
          0.1,
          "#120d31",
          0.2,
          "#331067",
          0.3,
          "#59157e",
          0.4,
          "#7e2482",
          0.5,
          "#a3307e",
          0.6,
          "#c83e73",
          0.7,
          "#e95462",
          0.8,
          "#fa7d5e",
          0.9,
          "#fea973",
          1.0,
          "#fed395",
        ],
        "heatmap-radius": [
          "interpolate",
          ["exponential", 1.5],
          ["zoom"],
          10,
          15,
          15,
          50,
        ] as any,
        "heatmap-opacity": {
          default: 0.9,
          stops: [
            [12, 0.9],
            [17, 0.5],
          ],
        } as any,
      },
    },
    {
      name: "Hot spots by street block",
      source: "street-blocks",
      type: "line",
      aggregated: true,
      column: "segment_id",
      geoid: "segment_id",
      legend: {
        colorScheme: "Plasma",
        scaleName: "Log",
        colorRange: [0.5, 1],
      },
      beforeId: "Point locations",
      paint: {
        "line-width": [
          "interpolate",
          ["linear"],
          ["zoom"],
          10,
          2,
          12,
          3,
          13,
          5,
        ],
      },
      tooltip: {
        formatter: createStreetBlockTooltip,
        on: "mousemove",
      },
    },
  ];
}
