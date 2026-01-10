/**
 * Shared color constants for the dashboard.
 * Centralized to ensure consistency across components.
 */

/** Main background color for dashboard sections */
export const BACKGROUND_DARK = "#353d42";

/** Border color for map/dashboard sections */
export const BORDER_GRAY = "#868b8e";

/**
 * Colorblind-safe chart palette (Wong/IBM based).
 * Muted/desaturated for solemn subject matter.
 */
export const CHART_COLORS = {
  /** Brown-gray - used for Outcome chart */
  coral: "#8a6d5c",
  /** Blue-gray - used for Court Record chart */
  slate: "#5a7a8f",
  /** Olive-gray - used for Gender chart */
  sage: "#7a7a6a",
  /** Dark teal - used for Race chart */
  teal: "#4a7080",
  /** Purple-gray - used for Age chart */
  mauve: "#6a5a7a",
} as const;

/** Slider histogram bar colors */
export const HISTOGRAM_COLORS = {
  /** Active/selected range */
  active: "#7ab5e5",
  /** Inactive/outside range */
  inactive: "#aaa",
} as const;

/** Focus ring color for accessibility */
export const FOCUS_RING_COLOR = "#1e88e5";

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
