import type { AggregateLegendModel } from "./mapLegend";

export const MAP_PRINT_PAGE_WIDTH = 1450;
export const MAP_PRINT_PAGE_HEIGHT = 1800;

export interface MapPrintImageOptions {
  aggregateLegends: readonly AggregateLegendModel[];
  basemapAttribution: string;
  dataAttribution: string;
  fatalCount: number;
  mapImage: string;
  nonfatalCount: number;
  showHeatLegend: boolean;
  showPointLegend: boolean;
  status: string;
  title: string;
}

interface TextLineOptions {
  fill?: string;
  fontSize: number;
  fontWeight?: number;
  x: number;
  y: number;
}

interface LegendStop {
  color: string;
  offset: number;
}

const PAGE_INSET = 64;
const CONTENT_WIDTH = MAP_PRINT_PAGE_WIDTH - PAGE_INSET * 2;
const FOOTER_RULE_Y = 1652;
const FONT_FAMILY =
  "Arial, Helvetica, 'Public Sans', system-ui, sans-serif";

function escapeXml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function estimatedCharacterWidth(character: string): number {
  if (/\s/.test(character)) return 0.32;
  if (/[ilI1|.,:;'`!]/.test(character)) return 0.3;
  if (/[mwMW@#%&]/.test(character)) return 0.86;
  if (/[A-Z0-9]/.test(character)) return 0.62;
  if (/[-–—]/.test(character)) return 0.5;
  return 0.52;
}

function estimatedTextWidth(
  value: string,
  fontSize: number,
  fontWeight = 400,
): number {
  const weightAdjustment = fontWeight >= 600 ? 1.04 : 1;
  return (
    [...value].reduce(
      (width, character) => width + estimatedCharacterWidth(character),
      0,
    ) *
    fontSize *
    weightAdjustment
  );
}

function wrapText(
  value: string,
  maxWidth: number,
  fontSize: number,
  fontWeight = 400,
): string[] {
  const words = value.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return [];

  const lines: string[] = [];
  let line = words[0]!;
  for (const word of words.slice(1)) {
    const candidate = `${line} ${word}`;
    if (estimatedTextWidth(candidate, fontSize, fontWeight) <= maxWidth) {
      line = candidate;
    } else {
      lines.push(line);
      line = word;
    }
  }
  lines.push(line);
  return lines;
}

function textLine(value: string, options: TextLineOptions): string {
  const { fill = "#11181c", fontSize, fontWeight = 400, x, y } = options;
  return `<text x="${x}" y="${y}" fill="${fill}" font-family="${FONT_FAMILY}" font-size="${fontSize}" font-weight="${fontWeight}">${escapeXml(value)}</text>`;
}

function textBlock(
  lines: readonly string[],
  options: TextLineOptions & { lineHeight: number },
): string {
  return lines
    .map((line, index) =>
      textLine(line, {
        ...options,
        y: options.y + index * options.lineHeight,
      }),
    )
    .join("");
}

function legendStops(barStyle: string): LegendStop[] {
  const stops = [
    ...barStyle.matchAll(
      /(#[\da-f]{3,8}|rgba?\([^)]+\))\s+([\d.]+)%/gi,
    ),
  ].map((match) => ({
    color: match[1]!,
    offset: Math.min(100, Math.max(0, Number(match[2]))),
  }));
  if (stops.length > 0) return stops;

  const solid = barStyle.match(/(#[\da-f]{3,8}|rgba?\([^)]+\))/i)?.[1];
  return [
    { color: solid ?? "#565c65", offset: 0 },
    { color: solid ?? "#565c65", offset: 100 },
  ];
}

function aggregateLegendHeight(legend: AggregateLegendModel): number {
  return legend.singleValue ? 82 : 102;
}

function aggregateLegendSvg(
  legend: AggregateLegendModel,
  index: number,
  top: number,
): string {
  const zeroLabel = legend.zeroLabel ? `0 — ${legend.zeroLabel}` : "0";
  const zeroWidth = legend.zeroColor
    ? Math.ceil(22 + 12 + estimatedTextWidth(zeroLabel, 16) + 24)
    : 0;
  const barX = PAGE_INSET + zeroWidth;
  const barWidth = 650;
  const barY = top + 33;
  const gradientId = `map-print-gradient-${index}`;
  const stops = legendStops(legend.barStyle);
  const gradient = `<linearGradient id="${gradientId}" x1="0" y1="0" x2="1" y2="0">${stops
    .map(
      (stop) =>
        `<stop offset="${stop.offset}%" stop-color="${escapeXml(stop.color)}"/>`,
    )
    .join("")}</linearGradient>`;
  const zero = legend.zeroColor
    ? `<rect x="${PAGE_INSET}" y="${barY}" width="22" height="16" rx="2" fill="${escapeXml(legend.zeroColor)}" stroke="#565c65" stroke-width="1"/>${textLine(zeroLabel, {
        fill: "#3d4551",
        fontSize: 16,
        x: PAGE_INSET + 29,
        y: barY + 15,
      })}`
    : "";
  const ticks = legend.ticks
    .map((tick) => {
      const x = barX + tick.position * barWidth;
      const anchor =
        tick.position <= 0 ? "start" : tick.position >= 1 ? "end" : "middle";
      return `<line x1="${x}" y1="${barY + 18}" x2="${x}" y2="${barY + 24}" stroke="#565c65" stroke-width="1"/><text x="${x}" y="${barY + 43}" text-anchor="${anchor}" fill="#3d4551" font-family="${FONT_FAMILY}" font-size="16">${escapeXml(tick.label)}</text>`;
    })
    .join("");
  const scaleName = legend.scale === "log" ? "Logarithmic" : "Linear";
  const explanation = legend.singleValue
    ? `1 shooting victim. ${legend.note}`
    : `${legend.direction} ${scaleName} scale. ${legend.note}`;

  return `<g><defs>${gradient}</defs>${textLine(legend.title, {
    fontSize: 19,
    fontWeight: 700,
    x: PAGE_INSET,
    y: top + 18,
  })}${zero}<rect x="${barX}" y="${barY}" width="${barWidth}" height="16" rx="3" fill="url(#${gradientId})"/>${ticks}${textBlock(
    wrapText(explanation, CONTENT_WIDTH - barWidth - zeroWidth - 42, 17),
    {
      fill: "#3d4551",
      fontSize: 17,
      lineHeight: 22,
      x: barX + barWidth + 42,
      y: barY + 14,
    },
  )}</g>`;
}

function pointAndHeatLegendSvg(
  options: MapPrintImageOptions,
  top: number,
): string {
  const parts: string[] = [];
  let x = PAGE_INSET;
  const y = top + 18;

  if (options.showPointLegend) {
    parts.push(
      `<circle cx="${x + 9}" cy="${y - 6}" r="8" fill="#ff8a8a" stroke="#a23737" stroke-width="2"/>`,
      textLine(`Fatal — ${options.fatalCount.toLocaleString("en-US")}`, {
        fontSize: 18,
        x: x + 27,
        y,
      }),
    );
    x += 196;
    parts.push(
      `<circle cx="${x + 9}" cy="${y - 6}" r="8" fill="#e5dc8e" stroke="#817a12" stroke-width="2"/>`,
      textLine(`Nonfatal — ${options.nonfatalCount.toLocaleString("en-US")}`, {
        fontSize: 18,
        x: x + 27,
        y,
      }),
    );
    x += 230;
  }

  if (options.showHeatLegend) {
    parts.push(
      textLine(
        "Density: brighter areas indicate a greater concentration of mapped records.",
        {
          fill: "#3d4551",
          fontSize: 18,
          x,
          y,
        },
      ),
    );
  }
  return parts.join("");
}

export function createMapPrintDescription(
  options: MapPrintImageOptions,
): string {
  const legendDescriptions: string[] = [];
  if (options.showPointLegend) {
    legendDescriptions.push(
      `Fatal: ${options.fatalCount.toLocaleString("en-US")}. Nonfatal: ${options.nonfatalCount.toLocaleString("en-US")}.`,
    );
  }
  if (options.showHeatLegend) {
    legendDescriptions.push(
      "Density: brighter areas indicate a greater concentration of mapped records.",
    );
  }
  legendDescriptions.push(
    ...options.aggregateLegends.map((legend) => legend.accessibleLabel),
  );
  return [
    options.status,
    ...legendDescriptions,
    options.dataAttribution,
    options.basemapAttribution,
  ]
    .filter(Boolean)
    .join(" ");
}

/**
 * Compose every printable map element into one fixed-ratio SVG image. Keeping
 * the page atomic avoids WebKit paginating a map separately from its legends
 * or source notes, including in iOS Safari's native print preview.
 */
export function createMapPrintImage(options: MapPrintImageOptions): string {
  if (!options.mapImage.startsWith("data:image/png")) {
    throw new Error("The map image must be a PNG data URL.");
  }

  const statusLines = wrapText(options.status, CONTENT_WIDTH, 20);
  const statusY = 164;
  const statusBottom = statusY + Math.max(0, statusLines.length - 1) * 27;
  const hasInlineLegend = options.showPointLegend || options.showHeatLegend;
  const aggregateHeight = options.aggregateLegends.reduce(
    (height, legend) => height + aggregateLegendHeight(legend),
    0,
  );
  const inlineLegendHeight = hasInlineLegend ? 48 : 0;
  const legendsHeight = inlineLegendHeight + aggregateHeight;
  const legendsTop = FOOTER_RULE_Y - 24 - legendsHeight;
  const mapTop = statusBottom + 28;
  const mapBottom = legendsTop - (legendsHeight > 0 ? 20 : 0);
  if (mapBottom - mapTop < 620) {
    throw new Error("The print layout does not have enough room for the map.");
  }

  let legendY = legendsTop;
  const legendParts: string[] = [];
  if (hasInlineLegend) {
    legendParts.push(pointAndHeatLegendSvg(options, legendY));
    legendY += inlineLegendHeight;
  }
  options.aggregateLegends.forEach((legend, index) => {
    legendParts.push(aggregateLegendSvg(legend, index, legendY));
    legendY += aggregateLegendHeight(legend);
  });

  const dataAttributionLines = wrapText(
    options.dataAttribution,
    CONTENT_WIDTH,
    16,
  );
  const basemapAttributionLines = wrapText(
    options.basemapAttribution,
    CONTENT_WIDTH,
    16,
  );
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${MAP_PRINT_PAGE_WIDTH}" height="${MAP_PRINT_PAGE_HEIGHT}" viewBox="0 0 ${MAP_PRINT_PAGE_WIDTH} ${MAP_PRINT_PAGE_HEIGHT}" role="img" aria-labelledby="map-print-title map-print-description"><title id="map-print-title">${escapeXml(options.title)}</title><desc id="map-print-description">${escapeXml(createMapPrintDescription(options))}</desc><rect width="${MAP_PRINT_PAGE_WIDTH}" height="${MAP_PRINT_PAGE_HEIGHT}" fill="#ffffff"/>${textLine(
    "Philadelphia Gun Violence Dashboard",
    {
      fill: "#3d4551",
      fontSize: 20,
      fontWeight: 700,
      x: PAGE_INSET,
      y: 66,
    },
  )}${textLine(options.title, {
    fontSize: 38,
    fontWeight: 700,
    x: PAGE_INSET,
    y: 118,
  })}${textBlock(statusLines, {
    fill: "#3d4551",
    fontSize: 20,
    lineHeight: 27,
    x: PAGE_INSET,
    y: statusY,
  })}<rect x="${PAGE_INSET}" y="${mapTop}" width="${CONTENT_WIDTH}" height="${mapBottom - mapTop}" fill="#202a2f" stroke="#565c65" stroke-width="2"/><image href="${escapeXml(options.mapImage)}" x="${PAGE_INSET + 2}" y="${mapTop + 2}" width="${CONTENT_WIDTH - 4}" height="${mapBottom - mapTop - 4}" preserveAspectRatio="xMidYMid meet"/>${legendParts.join("")}<line x1="${PAGE_INSET}" y1="${FOOTER_RULE_Y}" x2="${MAP_PRINT_PAGE_WIDTH - PAGE_INSET}" y2="${FOOTER_RULE_Y}" stroke="#a9aeb1" stroke-width="2"/>${textBlock(
    dataAttributionLines,
    {
      fill: "#3d4551",
      fontSize: 16,
      lineHeight: 21,
      x: PAGE_INSET,
      y: FOOTER_RULE_Y + 30,
    },
  )}${textBlock(basemapAttributionLines, {
    fill: "#3d4551",
    fontSize: 16,
    lineHeight: 21,
    x: PAGE_INSET,
    y: FOOTER_RULE_Y + 30 + dataAttributionLines.length * 21,
  })}</svg>`;

  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}
