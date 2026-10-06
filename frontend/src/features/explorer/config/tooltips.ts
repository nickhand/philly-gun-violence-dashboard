/**
 * Map tooltip templates and formatters.
 *
 * Provides type-safe, well-styled tooltip builders for map layers.
 * Uses a template-based approach for consistent styling and maintainability.
 *
 * @module tooltips
 */

import { format } from "d3-format";
import { msToTimeString } from "@/shared/utils/datetime";

// ============================================================================
// Types
// ============================================================================

/**
 * Properties from shooting victim features.
 */
export interface ShootingProperties {
  dc_key: string;
  date: string;
  dateInMs: number;
  timeInMs: number;
  block_number: number;
  street_name: string;
  age: number | null;
  race: "W" | "B" | "H" | "A" | "Other/Unknown";
  sex: "M" | "F";
  fatal: boolean;
  has_court_case: boolean | null;
}

/**
 * Properties for aggregated features (choropleth layers).
 */
export interface AggregatedProperties {
  count: number;
  color?: string;
  [key: string]: unknown;
}

// ============================================================================
// Helper Functions
// ============================================================================

/**
 * Format date from milliseconds to readable date string.
 */
function formatDate(dateMs: number): string {
  return new Date(dateMs).toLocaleDateString("en-US", {
    weekday: "short",
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/**
 * Get full race label from abbreviation.
 */
function getRaceLabel(race: string): string {
  const labels: Record<string, string> = {
    W: "White (Non-Hispanic)",
    B: "Black (Non-Hispanic)",
    H: "Hispanic",
    A: "Asian",
    "Other/Unknown": "Other/Unknown",
  };
  return labels[race] ?? race;
}

/**
 * Get full gender label from abbreviation.
 */
function getGenderLabel(sex: string): string {
  const labels: Record<string, string> = {
    M: "Male",
    F: "Female",
  };
  return labels[sex] ?? sex;
}

// ============================================================================
// Tooltip Builder Classes
// ============================================================================

/**
 * Builds HTML for a styled tooltip.
 * Uses a fluent API for constructing tooltip content.
 */
class TooltipBuilder {
  private sections: string[] = [];

  /**
   * Add a header/title section.
   */
  title(text: string, className?: string): this {
    const cls = className ? ` ${className}` : "";
    this.sections.push(`<div class="tooltip-title${cls}">${text}</div>`);
    return this;
  }

  /**
   * Add a subtitle/secondary title.
   */
  subtitle(text: string): this {
    this.sections.push(`<div class="tooltip-subtitle">${text}</div>`);
    return this;
  }

  /**
   * Add a section header.
   */
  sectionHeader(text: string): this {
    this.sections.push(`<div class="tooltip-section-header">${text}</div>`);
    return this;
  }

  /**
   * Add a single row with label and value.
   */
  row(label: string, value: string | number | null | undefined): this {
    if (value === null || value === undefined || value === "") return this;
    this.sections.push(`
      <div class="tooltip-row">
        <span class="tooltip-label">${label}</span>
        <span class="tooltip-value">${value}</span>
      </div>
    `);
    return this;
  }

  /**
   * Add a single-column info row.
   */
  info(text: string): this {
    this.sections.push(`<div class="tooltip-info">${text}</div>`);
    return this;
  }

  /**
   * Add a highlighted stat (large number + label).
   */
  stat(value: number | string, label: string): this {
    const formatted = typeof value === "number" ? format(",")(value) : value;
    this.sections.push(`
      <div class="tooltip-stat">
        <span class="tooltip-stat-value">${formatted}</span>
        <span class="tooltip-stat-label">${label}</span>
      </div>
    `);
    return this;
  }

  /**
   * Add a divider line.
   */
  divider(): this {
    this.sections.push('<div class="tooltip-divider"></div>');
    return this;
  }

  /**
   * Add a badge (colored tag).
   */
  badge(text: string, type: "fatal" | "nonfatal" | "info" = "info"): this {
    this.sections.push(
      `<span class="tooltip-badge tooltip-badge--${type}">${text}</span>`,
    );
    return this;
  }

  /**
   * Build the final HTML string.
   */
  build(): string {
    return `<div class="map-tooltip">${this.sections.join("")}</div>`;
  }
}

/**
 * Create a new tooltip builder instance.
 */
function tooltip(): TooltipBuilder {
  return new TooltipBuilder();
}

// ============================================================================
// Tooltip Formatters
// ============================================================================

/**
 * Create tooltip formatter for shooting victim points.
 *
 * Shows detailed information about a single shooting incident including
 * date/time, location, victim demographics, and case information.
 */
export function createPointsLayerTooltip(
  data: Record<string, unknown>,
): string {
  const props = data as unknown as ShootingProperties;

  const fatalText = props.fatal ? "Fatal" : "Nonfatal";
  const fatalType = props.fatal ? "fatal" : "nonfatal";

  const builder = tooltip()
    .badge(fatalText, fatalType)
    .title("Shooting Incident");

  // Date and time
  if (props.dateInMs) {
    builder.row("Date", formatDate(props.dateInMs));
  }
  if (props.timeInMs !== undefined) {
    builder.row("Time", msToTimeString(props.timeInMs));
  }

  // Location
  if (props.block_number && props.street_name) {
    builder.row("Location", `${props.block_number} ${props.street_name}`);
  }

  builder.divider().sectionHeader("Victim Information");

  // Victim demographics
  if (props.age) {
    builder.row("Age", `${props.age} years old`);
  }
  if (props.race && props.race !== "Other/Unknown") {
    builder.row("Race/Ethnicity", getRaceLabel(props.race));
  }
  if (props.sex) {
    builder.row("Gender", getGenderLabel(props.sex));
  }

  builder.divider().sectionHeader("Case Information");

  // Case info
  builder.row("DC Number", props.dc_key);
  builder.row(
    "Court search result",
    typeof props.has_court_case !== "boolean"
      ? "Unknown"
      : props.has_court_case
        ? "Yes"
        : "No",
  );

  return builder.build();
}

/**
 * Create tooltip formatter for aggregated layers (choropleth).
 *
 * @param titleFunc - Function to generate title from feature properties
 * @returns Tooltip formatter function
 *
 * @example
 * ```ts
 * const formatter = createAggregatedLayerTooltip(
 *   (d) => `Police District #${d.police_district}`
 * );
 * ```
 */
export function createAggregatedLayerTooltip(
  titleFunc: (data: Record<string, unknown>) => string,
): (data: Record<string, unknown>) => string {
  return (data) => {
    const count = (data.count as number) ?? 0;
    const title = titleFunc(data);

    return tooltip().title(title).stat(count, "shooting victims").build();
  };
}

/**
 * Create tooltip formatter for street block hot spots.
 *
 * Shows the block address and count for street segment aggregations.
 */
export function createStreetBlockTooltip(
  data: Record<string, unknown>,
): string {
  const blockNumber = data.block_number as number;
  const streetName = data.street_name as string;
  const count = (data.count as number) ?? 0;

  const title =
    blockNumber && streetName ? `${blockNumber} ${streetName}` : "Street Block";

  return tooltip().title(title).stat(count, "shooting victims").build();
}

// ============================================================================
// CSS Styles (injected into document)
// ============================================================================

/**
 * Tooltip styles to be injected into the document.
 * Uses CSS custom properties for theming flexibility.
 */
export const TOOLTIP_STYLES = `
/* Map Tooltip Container */
.map-tooltip {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  font-size: 13px;
  line-height: 1.4;
  color: #ffffff;
  min-width: 180px;
  max-width: 280px;
}

/* MapLibre Popup Styling */
.map-tooltip-popup .maplibregl-popup-content {
  background: rgba(30, 30, 30, 0.95);
  border-radius: 8px;
  padding: 12px 14px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(8px);
  pointer-events: none; /* Don't capture mouse events for hover tooltips */
}

/* Pinned tooltip - enable interaction */
.map-tooltip-popup--pinned .maplibregl-popup-content {
  pointer-events: auto;
  user-select: text;
  cursor: text;
  border: 1px solid rgba(100, 149, 237, 0.5);
}

/* Enable text selection in pinned tooltips */
.map-tooltip-popup--pinned .map-tooltip,
.map-tooltip-popup--pinned .map-tooltip * {
  user-select: text;
  -webkit-user-select: text;
}

/* Close button styling */
.map-tooltip-popup--pinned .maplibregl-popup-close-button {
  color: rgba(255, 255, 255, 0.7);
  font-size: 20px;
  padding: 4px 8px;
  right: 2px;
  top: 2px;
  background: transparent;
  border: none;
  cursor: pointer;
  line-height: 1;
  transition: color 0.15s ease;
}

.map-tooltip-popup--pinned .maplibregl-popup-close-button:hover {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 4px;
}

/* Hint on hover tooltip to indicate click-to-pin */
.map-tooltip-popup:not(.map-tooltip-popup--pinned) .map-tooltip::after {
  content: 'Click to pin';
  font-size: 10px;
  color: rgba(255, 255, 255, 0.5);
  display: block;
  margin-top: 8px;
  padding-top: 6px;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  text-align: center;
}

.map-tooltip-popup .maplibregl-popup-tip {
  border-top-color: rgba(30, 30, 30, 0.95);
}

.map-tooltip-popup--pinned .maplibregl-popup-tip {
  border-top-color: rgba(30, 30, 30, 0.95);
}

/* Title */
.tooltip-title {
  font-size: 14px;
  font-weight: 600;
  color: #ffffff;
  margin-bottom: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.15);
}

/* Subtitle */
.tooltip-subtitle {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.7);
  margin-bottom: 8px;
}

/* Section Header */
.tooltip-section-header {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: rgba(255, 255, 255, 0.6);
  margin-top: 4px;
  margin-bottom: 6px;
}

/* Row (label + value) */
.tooltip-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 12px;
  padding: 3px 0;
}

.tooltip-label {
  color: rgba(255, 255, 255, 0.7);
  font-size: 12px;
  flex-shrink: 0;
}

.tooltip-value {
  color: #ffffff;
  font-size: 12px;
  font-weight: 500;
  text-align: right;
}

/* Single-column info text */
.tooltip-info {
  color: rgba(255, 255, 255, 0.85);
  padding: 2px 0;
}

/* Stat (large number display) */
.tooltip-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8px 0;
}

.tooltip-stat-value {
  font-size: 28px;
  font-weight: 700;
  color: #ffffff;
  line-height: 1;
}

.tooltip-stat-label {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.6);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-top: 4px;
}

/* Divider */
.tooltip-divider {
  height: 1px;
  background: rgba(255, 255, 255, 0.15);
  margin: 8px 0;
}

/* Badge */
.tooltip-badge {
  display: inline-block;
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 3px 8px;
  border-radius: 4px;
  margin-bottom: 6px;
}

.tooltip-badge--fatal {
  background: rgba(216, 69, 69, 0.9);
  color: #ffffff;
}

.tooltip-badge--nonfatal {
  background: rgba(229, 220, 142, 0.9);
  color: #333333;
}

.tooltip-badge--info {
  background: rgba(100, 149, 237, 0.9);
  color: #ffffff;
}
`;

/**
 * Inject tooltip styles into the document head.
 * Safe to call multiple times (checks for existing styles).
 */
export function injectTooltipStyles(): void {
  const styleId = "map-tooltip-styles";
  if (document.getElementById(styleId)) return;

  const style = document.createElement("style");
  style.id = styleId;
  style.textContent = TOOLTIP_STYLES;
  document.head.appendChild(style);
}
