/**
 * Shared color constants for the dashboard.
 * Centralized to ensure consistency across components.
 */

/**
 * Colorblind-safe chart palette based on Okabe-Ito (Nature journal standard).
 * Desaturated for solemn subject matter while preserving proven accessibility.
 * Original: https://jfly.uni-koeln.de/color/
 */
export const CHART_COLORS = {
  /** Muted terracotta (from Okabe-Ito vermillion) - Outcome chart */
  coral: "#906050",
  /** Muted steel blue (from Okabe-Ito sky blue) - Court Record chart */
  slate: "#6a90a5",
  /** Muted sage-teal (from Okabe-Ito bluish green) - Gender chart */
  sage: "#5a8575",
  /** Muted amber (from Okabe-Ito orange) - Race chart */
  teal: "#a08560",
  /** Muted mauve (from Okabe-Ito reddish purple) - Age chart */
  mauve: "#8a6880",
} as const;
