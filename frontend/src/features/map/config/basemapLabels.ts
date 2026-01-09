import type { Map as MapLibreMap, ExpressionSpecification } from "maplibre-gl";

/**
 * Configuration for enhancing basemap label visibility.
 * Defines layer groups and their zoom-based text size scaling.
 */

interface LabelConfig {
  /** Layer IDs in the basemap style */
  layers: string[];
  /** Zoom-based text size expression */
  textSize: ExpressionSpecification;
  /** Optional: override minzoom to show labels earlier */
  minZoom?: number;
}

/**
 * Road and street label configuration.
 * Scales from 8px at zoom 11 to 20px at zoom 18.
 * Shows major roads earlier (zoom 11+) for mid-zoom context.
 */
const roadLabels: LabelConfig = {
  layers: [
    "Road/label/Local",
    "Road/label/Minor",
    "Road/label/Major",
    "Road/label/Major, alt name",
    "Road/label/Highway",
    "Road/label/Freeway Motorway",
    "Road/label/Freeway Motorway, alt name",
    "Road/label/Pedestrian",
    "Trail or path/label/Default",
  ],
  textSize: [
    "interpolate",
    ["linear"],
    ["zoom"],
    11,
    8,
    13,
    10,
    15,
    14,
    17,
    17,
    18,
    20,
  ],
};

/**
 * POI and facility label configuration.
 * Includes schools, parks, buildings, and other points of interest.
 * Scales from 11px at zoom 14 to 17px at zoom 18.
 */
const poiLabels: LabelConfig = {
  layers: [
    "Education/label/Default",
    "Building/label/Default",
    "Point of interest/General",
    "Point of interest/Bus station",
    "Point of interest/Rail station",
    "Point of interest/Park",
    "Park or farming/label/Default",
    "Openspace or forest/label/Default",
    "Cemetery/label/Default",
    "Zoo/label/Default",
    "Medical/label/Default",
    "Government/label/Default",
    "Transportation/label/Default",
    "Retail/label/Default",
    "Landmark/label/Default",
    "Industry/label/Default",
    "Military/label/Default",
    "Golf course/label/Default",
    "Beach/label/Default",
  ],
  textSize: ["interpolate", ["linear"], ["zoom"], 14, 11, 16, 14, 18, 17],
};

/**
 * Transit label configuration.
 * Includes railroads and ferries.
 * Scales from 10px at zoom 14 to 16px at zoom 18.
 */
const transitLabels: LabelConfig = {
  layers: ["Railroad/label/Default", "Ferry/label/Rail ferry"],
  textSize: ["interpolate", ["linear"], ["zoom"], 14, 10, 16, 13, 18, 16],
};

/** All label configurations */
const labelConfigs: LabelConfig[] = [roadLabels, poiLabels, transitLabels];

/**
 * Layer-specific minzoom overrides to show labels at mid-zoom levels.
 * Original basemap has these appearing much later.
 */
const minZoomOverrides: Record<string, number> = {
  // Major roads visible earlier
  "Road/label/Highway": 11,
  "Road/label/Freeway Motorway": 11,
  "Road/label/Freeway Motorway, alt name": 11,
  "Road/label/Major": 12,
  "Road/label/Major, alt name": 12,
  // Minor/local roads a bit earlier
  "Road/label/Minor": 13,
  "Road/label/Local": 14,
};

/**
 * Apply enhanced text sizes to basemap label layers.
 * Improves readability at higher zoom levels and shows labels earlier.
 *
 * @param map - MapLibre map instance
 */
export function enhanceBasemapLabels(map: MapLibreMap): void {
  for (const config of labelConfigs) {
    for (const layerId of config.layers) {
      if (map.getLayer(layerId)) {
        map.setLayoutProperty(layerId, "text-size", config.textSize);

        // Apply minzoom override if specified
        const minZoom = minZoomOverrides[layerId];
        if (minZoom !== undefined) {
          map.setLayerZoomRange(layerId, minZoom, 24);
        }
      }
    }
  }
}
