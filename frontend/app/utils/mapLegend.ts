import type { ExpressionSpecification } from "maplibre-gl";

export type AggregateLegendKind = "choropleth" | "street-hot-spots";
export type AggregateLegendScale = "linear" | "log";

export interface AggregateLegendTick {
  label: string;
  position: number;
  value: number;
}

export interface AggregateLegendModel {
  accessibleLabel: string;
  barStyle: string;
  context: string;
  direction: string;
  id: AggregateLegendKind;
  mapColor: string | ExpressionSpecification;
  maximum: number;
  minimum: number;
  note: string;
  scale: AggregateLegendScale;
  singleValue: boolean;
  ticks: AggregateLegendTick[];
  title: string;
  zeroColor: string | null;
  zeroLabel: string | null;
}

interface AggregatePalette {
  colors: readonly string[];
  scale: AggregateLegendScale;
}

export const AGGREGATE_ZERO_COLOR = "#687176";
export const AGGREGATE_ZERO_LABEL = "No matching victims";
export const AGGREGATE_LEGEND_NOTE = "Counts reflect the current filters.";

const LEGEND_INTERVALS = 10;
const MINIMUM_COUNT = 1;

// These are the exact 11 samples previously produced at runtime by D3's Reds
// interpolator over [0, 1] and Plasma over [0.5, 1]. Keeping the reviewed
// palette in this small utility avoids shipping a color-generation library in
// the map bundle and ensures the map, live legend, and print legend use the
// same stable colors.
const REDS_COLORS = [
  "rgb(255, 245, 240)",
  "rgb(254, 227, 214)",
  "rgb(253, 201, 180)",
  "rgb(252, 170, 142)",
  "rgb(252, 138, 107)",
  "rgb(249, 105, 76)",
  "rgb(239, 69, 51)",
  "rgb(217, 39, 35)",
  "rgb(187, 21, 26)",
  "rgb(151, 11, 19)",
  "rgb(103, 0, 13)",
] as const;

const PLASMA_COLORS = [
  "#cc4778",
  "#d6556d",
  "#e16462",
  "#ea7457",
  "#f2844b",
  "#f89540",
  "#fca636",
  "#feba2c",
  "#fcce25",
  "#f7e425",
  "#f0f921",
] as const;

const PALETTES: Record<AggregateLegendKind, AggregatePalette> = {
  choropleth: {
    colors: REDS_COLORS,
    scale: "linear",
  },
  "street-hot-spots": {
    colors: PLASMA_COLORS,
    scale: "log",
  },
};

function colorAt(palette: AggregatePalette, position: number): string {
  const index = Math.round(
    Math.min(1, Math.max(0, position)) * LEGEND_INTERVALS,
  );
  return palette.colors[index] ?? palette.colors[palette.colors.length - 1]!;
}

function scalePosition(
  scale: AggregateLegendScale,
  value: number,
  minimum: number,
  maximum: number,
): number {
  if (minimum === maximum) return 0.5;
  if (scale === "log") {
    return (
      (Math.log(value) - Math.log(minimum)) /
      (Math.log(maximum) - Math.log(minimum))
    );
  }
  return (value - minimum) / (maximum - minimum);
}

function scaleValue(
  scale: AggregateLegendScale,
  position: number,
  minimum: number,
  maximum: number,
): number {
  if (scale === "log") {
    return Math.exp(
      Math.log(minimum) +
        position * (Math.log(maximum) - Math.log(minimum)),
    );
  }
  return minimum + position * (maximum - minimum);
}

function createTicks(
  scale: AggregateLegendScale,
  minimum: number,
  maximum: number,
): AggregateLegendTick[] {
  if (minimum === maximum) {
    return [{ label: minimum.toLocaleString(), position: 0.5, value: minimum }];
  }

  const midpoint = Math.round(scaleValue(scale, 0.5, minimum, maximum));
  const values = [minimum];
  if (midpoint > minimum && midpoint < maximum) values.push(midpoint);
  values.push(maximum);

  return values.map((value) => ({
    label: value.toLocaleString(),
    position: scalePosition(scale, value, minimum, maximum),
    value,
  }));
}

function createBarStyle(
  palette: AggregatePalette,
  singleValue: boolean,
): string {
  if (singleValue) return `background: ${colorAt(palette, 0.5)};`;

  const stops = Array.from({ length: LEGEND_INTERVALS + 1 }, (_, index) => {
    const position = index / LEGEND_INTERVALS;
    return `${colorAt(palette, position)} ${position * 100}%`;
  });
  return `background: linear-gradient(90deg, ${stops.join(", ")});`;
}

function createMapColor(
  palette: AggregatePalette,
  minimum: number,
  maximum: number,
): string | ExpressionSpecification {
  if (minimum === maximum) return colorAt(palette, 0.5);

  const input: ExpressionSpecification =
    palette.scale === "log"
      ? (["ln", ["get", "total_shootings"]] as ExpressionSpecification)
      : (["get", "total_shootings"] as ExpressionSpecification);
  const stops = Array.from({ length: LEGEND_INTERVALS + 1 }, (_, index) => {
    const position = index / LEGEND_INTERVALS;
    const value = scaleValue(palette.scale, position, minimum, maximum);
    const transformedValue = palette.scale === "log" ? Math.log(value) : value;
    return [transformedValue, colorAt(palette, position)] as const;
  }).flat();

  return [
    "interpolate",
    ["linear"],
    input,
    ...stops,
  ] as ExpressionSpecification;
}

/**
 * Build the one quantitative encoding used by the map and both live and print
 * legends. Boundary fills use a sequential red, linear scale. Street-block
 * lines use the brighter half of Plasma on a log scale so the highly skewed
 * counts remain visible against the dark basemap.
 */
export function createAggregateLegend(
  kind: AggregateLegendKind,
  maximum: number,
  context: string,
): AggregateLegendModel | null {
  if (!Number.isFinite(maximum) || maximum < MINIMUM_COUNT) return null;

  const integerMaximum = Math.max(MINIMUM_COUNT, Math.floor(maximum));
  const palette = PALETTES[kind];
  const isBoundary = kind === "choropleth";
  const singleValue = integerMaximum === MINIMUM_COUNT;
  const title = isBoundary
    ? `Shooting victims by ${context}`
    : "Shooting victims per street block";
  const direction = isBoundary
    ? "Darker red means more victims."
    : "Brighter yellow means more victims.";
  const zeroDescription = isBoundary
    ? " Gray means no matching victims."
    : "";
  const accessibleLabel = singleValue
    ? `${title} map legend. 1 shooting victim.${zeroDescription} ${AGGREGATE_LEGEND_NOTE}`
    : `${title} map legend. ${direction}${zeroDescription} ${palette.scale === "log" ? "Logarithmic" : "Linear"} scale from ${MINIMUM_COUNT.toLocaleString()} to ${integerMaximum.toLocaleString()}. ${AGGREGATE_LEGEND_NOTE}`;

  return {
    accessibleLabel,
    barStyle: createBarStyle(palette, singleValue),
    context,
    direction,
    id: kind,
    mapColor: createMapColor(palette, MINIMUM_COUNT, integerMaximum),
    maximum: integerMaximum,
    minimum: MINIMUM_COUNT,
    note: AGGREGATE_LEGEND_NOTE,
    scale: palette.scale,
    singleValue,
    ticks: createTicks(palette.scale, MINIMUM_COUNT, integerMaximum),
    title,
    zeroColor: isBoundary ? AGGREGATE_ZERO_COLOR : null,
    zeroLabel: isBoundary ? AGGREGATE_ZERO_LABEL : null,
  };
}

export function boundaryMapColor(
  legend: AggregateLegendModel,
): ExpressionSpecification {
  return [
    "case",
    ["==", ["get", "total_shootings"], 0],
    AGGREGATE_ZERO_COLOR,
    legend.mapColor,
  ] as ExpressionSpecification;
}
