import type { LayerConfig } from "../types";
import { format } from "d3-format";

/**
 * Formatter function for aggregated layer tooltips.
 *
 * @param titleFunc - Function that returns the tooltip title from feature properties
 * @returns Function that generates HTML tooltip string
 */
export function createAggregatedLayerTooltip(
  titleFunc: (data: Record<string, any>) => string
): (data: Record<string, any>) => string {
  return (data) => {
    // Get the total count
    const count = data["count"];
    const formatted = format(",")(count);

    // The title
    const title = titleFunc(data);

    const text = `<div class='map-tooltip'>
                  <div class="map-tooltip__title">${title}</div>
                    <table class="w-100">
                      <tr class="map-tooltip__line">
                        <td>Total shooting victims:</td>
                        <td class="text-right">${formatted}</td>
                      </tr>
                    </table>
                  </div>`;
    return text;
  };
}

/**
 * Formatter function for the shootings points layer tooltip.
 *
 * @param data - Feature properties from the shooting victim
 * @returns HTML string for the tooltip
 */
export function createPointsLayerTooltip(data: Record<string, any>): string {
  const aliases: Record<string, string> = {
    W: "White (Non-Hispanic)",
    B: "Black (Non-Hispanic)",
    H: "Hispanic (Black or White)",
    M: "Male",
    F: "Female",
    A: "Asian",
  };

  const fatal = data.fatal ? "Fatal" : "Nonfatal";
  const arrest = data.has_court_case ? "Yes" : "No";

  let text = `<div class='map-tooltip'>
            <div class="map-tooltip__title">${fatal} Shooting</div>
            <table class="w-100">
              <tbody>
                <tr class="map-tooltip__line">
                  <td>Court case:</td>
                  <td class="text-right">${arrest}</td>
                </tr>
                <tr class="map-tooltip__line">
                  <td>Location:</td>
                  <td class="text-right">${data.location || "Unknown"}</td>
                </tr>
                <tr class="map-tooltip__line">
                  <td>Inside/Outside:</td>
                  <td class="text-right">${
                    data.inside ? "Inside" : "Outside"
                  }</td>
                </tr>
              </tbody>
            </table>
            <div class="map-tooltip__title mt-2">Victim Info</div>
            <table class="w-100">
              <tbody>`;

  if (data.age) {
    text += `<tr class="map-tooltip__line">
              <td>${data.age} years old</td>
            </tr>`;
  }

  if (data.race !== "Other/Unknown") {
    text += `<tr class="map-tooltip__line">
              <td>${aliases[data.race]}</td>
            </tr>`;
  }

  text += `<tr class="map-tooltip__line">
              <td>${aliases[data.sex]}</td>
            </tr>
          </tbody>
        </table>
        <div class="map-tooltip__title mt-2">Incident Info</div>
        <table class="w-100">
          <tbody>
            <tr class="map-tooltip__line">
              <td>Date/Time:</td>
              <td class="text-right">${data.date || "Unknown"}</td>
            </tr>
            <tr class="map-tooltip__line">
              <td>Officer Involved:</td>
              <td class="text-right">${
                data.officer_involved ? "Yes" : "No"
              }</td>
            </tr>
          </tbody>
        </table>
      </div>`;
  return text;
}

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
      name: "Police District",
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
      name: "Council District",
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
      name: "ZIP Code",
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
      name: "Neighborhood",
      source: "boundary-neighborhoods",
      type: "fill",
      aggregated: true,
      overlay: true,
      column: "neighborhood",
      geoid: "neighborhood",
      tooltip: {
        formatter: createAggregatedLayerTooltip((d) => d.neighborhood),
        on: "mousemove",
      },
    },
    {
      name: "PA House District",
      source: "boundary-house-districts",
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
      name: "PA Senate District",
      source: "boundary-senate-districts",
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
      name: "Elementary School Catchment",
      source: "boundary-elementary-schools",
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
      paint: { "line-width": 4, "line-color": "#fff" },
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
        formatter: createAggregatedLayerTooltip(
          (d) => `${d.block_number} ${d.street_name}`
        ),
        on: "mousemove",
      },
    },
  ];
}
