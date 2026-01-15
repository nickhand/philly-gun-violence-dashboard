/**
 * Shared color constants for the dashboard.
 * Centralized to ensure consistency across components.
 */

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
