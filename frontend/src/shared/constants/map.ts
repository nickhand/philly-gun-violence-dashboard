/**
 * Map configuration constants.
 */

/** Map default configuration */
export const MAP_DEFAULTS = {
  /** Philadelphia center coordinates [lng, lat] */
  center: [-75.1652, 39.9526] as [number, number],
  /** Default zoom level */
  zoom: 11,
  /** Minimum zoom */
  minZoom: 9,
  /** Maximum zoom */
  maxZoom: 18,
} as const;
