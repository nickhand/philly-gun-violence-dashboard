import type { Feature, FeatureCollection, Geometry, Point } from "geojson";

import type { BoundaryMapLayerId } from "./mapLayers";
import {
  boundaryOverlayConfig,
  fetchOverlayFeatureCollection,
  joinBoundaryCounts,
} from "./mapOverlays";
import type { ShootingRow } from "./shootingRecords";

export interface ShootingDownloadOptions {
  aggregateBy: BoundaryMapLayerId | null;
  format: "csv" | "geojson";
  useFiltered: boolean;
}

export interface ShootingDownloadFile {
  content: string;
  filename: string;
  type: string;
}

interface ExportFeature extends Feature<Point | null, Record<string, unknown>> {}

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;

const EXCLUDED_EXPORT_FIELDS = new Set([
  "dateInMs",
  "lat",
  "lon",
  "timeInMs",
  "unique_id",
  "weekday",
  "year",
]);

export function rowsToExportFeatures(rows: ShootingRow[]): ExportFeature[] {
  return rows.map((row) => {
    const properties: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(row)) {
      if (!EXCLUDED_EXPORT_FIELDS.has(key)) properties[key] = value;
    }
    const { lat, lon } = row;
    const hasPoint =
      typeof lat === "number" &&
      typeof lon === "number" &&
      Number.isFinite(lat) &&
      Number.isFinite(lon) &&
      lat >= -90 &&
      lat <= 90 &&
      lon >= -180 &&
      lon <= 180;
    return {
      type: "Feature",
      geometry: hasPoint
        ? { type: "Point", coordinates: [lon, lat] }
        : null,
      properties,
    };
  });
}

function csvValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string" && /^[=+\-@\t\r]/.test(value)) {
    throw new Error(
      "This CSV contains a value that spreadsheet software could treat as a formula.",
    );
  }
  const text = String(value);
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function featuresToCsv(features: ExportFeature[]): string {
  if (features.length === 0) return "";
  const keys = new Set<string>();
  for (const feature of features) {
    Object.keys(feature.properties).forEach((key) => keys.add(key));
  }
  if (features.some((feature) => feature.geometry?.type === "Point")) {
    keys.add("latitude");
    keys.add("longitude");
  }
  const headers = [...keys];
  const lines = features.map((feature) =>
    headers
      .map((header) => {
        if (header === "latitude" && feature.geometry?.type === "Point") {
          return csvValue(feature.geometry.coordinates[1]);
        }
        if (header === "longitude" && feature.geometry?.type === "Point") {
          return csvValue(feature.geometry.coordinates[0]);
        }
        return csvValue(feature.properties[header]);
      })
      .join(","),
  );
  return [headers.join(","), ...lines].join("\n");
}

export function aggregateShootingRows(
  rows: ShootingRow[],
  aggregateBy: BoundaryMapLayerId,
): Array<Record<string, unknown>> {
  const config = boundaryOverlayConfig(aggregateBy);
  const groups = new Map<string, { fatal: number; nonfatal: number; total: number }>();
  for (const row of rows) {
    const raw = row[config.column];
    if (raw === null || raw === undefined || raw === "") continue;
    const key = String(raw);
    const count = groups.get(key) ?? { fatal: 0, nonfatal: 0, total: 0 };
    count.total += 1;
    if (row.fatal) count.fatal += 1;
    else count.nonfatal += 1;
    groups.set(key, count);
  }
  return [...groups.entries()]
    .map(([key, count]) => ({
      [config.column]: key,
      total_shootings: count.total,
      fatal: count.fatal,
      nonfatal: count.nonfatal,
    }))
    .sort(
      (left, right) =>
        Number(right.total_shootings) - Number(left.total_shootings),
    );
}

export function recordsToCsv(records: Array<Record<string, unknown>>): string {
  if (records.length === 0) return "";
  const headers = Object.keys(records[0]);
  return [
    headers.join(","),
    ...records.map((record) =>
      headers.map((header) => csvValue(record[header])).join(","),
    ),
  ].join("\n");
}

export async function createShootingDownload(
  apiBaseUrl: string,
  filteredRows: ShootingRow[],
  allRows: ShootingRow[],
  options: ShootingDownloadOptions,
  request: { fetcher?: Fetcher; signal?: AbortSignal; today?: string } = {},
): Promise<ShootingDownloadFile> {
  const rows = options.useFiltered ? filteredRows : allRows;
  const suffix = options.useFiltered ? "filtered" : "all";
  const today = request.today ?? new Date().toISOString().slice(0, 10);

  if (options.aggregateBy) {
    const config = boundaryOverlayConfig(options.aggregateBy);
    const aggregated = aggregateShootingRows(rows, options.aggregateBy);
    if (options.format === "csv") {
      return {
        content: recordsToCsv(aggregated),
        filename: `shootings-by-${options.aggregateBy}-${suffix}-${today}.csv`,
        type: "text/csv;charset=utf-8",
      };
    }

    const boundary = await fetchOverlayFeatureCollection(
      apiBaseUrl,
      `/boundaries/${config.dataset}`,
      request,
    );
    const joined = joinBoundaryCounts(boundary, rows, config);
    const collection: FeatureCollection<Geometry> = {
      type: "FeatureCollection",
      features: joined.features,
    };
    return {
      content: JSON.stringify(collection, null, 2),
      filename: `shootings-by-${options.aggregateBy}-${suffix}-${today}.geojson`,
      type: "application/geo+json",
    };
  }

  const features = rowsToExportFeatures(rows);
  if (options.format === "csv") {
    return {
      content: featuresToCsv(features),
      filename: `shootings-${suffix}-${today}.csv`,
      type: "text/csv;charset=utf-8",
    };
  }
  return {
    content: JSON.stringify({ type: "FeatureCollection", features }, null, 2),
    filename: `shootings-${suffix}-${today}.geojson`,
    type: "application/geo+json",
  };
}
