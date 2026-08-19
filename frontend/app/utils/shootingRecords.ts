import type { FeatureCollection, Point } from "geojson";

export interface ShootingRow {
  age?: unknown;
  age_group?: unknown;
  block_number?: unknown;
  council_district?: unknown;
  date?: unknown;
  dateInMs?: unknown;
  dc_key?: unknown;
  fatal: boolean;
  has_court_case: boolean | null;
  house_district?: unknown;
  lat: number | null;
  lon: number | null;
  neighborhood?: unknown;
  police_district?: unknown;
  race?: unknown;
  school_name?: unknown;
  segment_id?: unknown;
  senate_district?: unknown;
  sex?: unknown;
  street_name?: unknown;
  timeInMs?: unknown;
  weekday?: unknown;
  year?: unknown;
  zip_code?: unknown;
}

interface YearMeta {
  rows: number;
  rows_url: string;
}

interface ShootingsMeta {
  years_meta: Record<string, YearMeta>;
}

export interface ShootingPointProperties {
  age: number | null;
  date: string | null;
  dcKey: string | null;
  fatal: boolean;
  hasCourtCase: boolean | null;
  race: string | null;
  sex: string | null;
  streetBlock: string | null;
  timeInMs: number | null;
}

export type ShootingPointCollection = FeatureCollection<
  Point,
  ShootingPointProperties
>;

export interface ShootingRecordResult {
  fatalRecordCount: number;
  nonfatalRecordCount: number;
  points: ShootingPointCollection;
  recordCount: number;
  rows: ShootingRow[];
}

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;

function isShootingRow(value: unknown): value is ShootingRow {
  if (!value || typeof value !== "object") return false;
  const row = value as Record<string, unknown>;
  const validCoordinate = (coordinate: unknown) =>
    coordinate === null || typeof coordinate === "number";

  return (
    typeof row.fatal === "boolean" &&
    (typeof row.has_court_case === "boolean" || row.has_court_case === null) &&
    validCoordinate(row.lat) &&
    validCoordinate(row.lon)
  );
}

export function parseShootingRows(source: string): ShootingRow[] {
  const rows: ShootingRow[] = [];

  for (const [index, line] of source.split(/\r?\n/).entries()) {
    if (!line.trim()) continue;

    let value: unknown;
    try {
      value = JSON.parse(line);
    } catch {
      throw new Error(`Invalid shooting record on line ${index + 1}.`);
    }

    if (!isShootingRow(value)) {
      throw new Error(`Invalid shooting record on line ${index + 1}.`);
    }
    rows.push(value);
  }

  return rows;
}

function readRecordDate(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const date = value.slice(0, 10);
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  if (!match) return null;

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return parsed.getUTCFullYear() === year &&
    parsed.getUTCMonth() === month - 1 &&
    parsed.getUTCDate() === day
    ? date
    : null;
}

function readStreetBlock(row: ShootingRow): string | null {
  const street =
    typeof row.street_name === "string" ? row.street_name.trim() : "";
  const block = row.block_number;
  if (!street || typeof block !== "number" || !Number.isFinite(block)) {
    return null;
  }
  return `${Math.trunc(block)} block of ${street}`;
}

function readFiniteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function readText(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const text = value.trim();
  return text || null;
}

export function rowsToShootingPoints(
  rows: ShootingRow[],
): ShootingPointCollection {
  return {
    type: "FeatureCollection",
    features: rows.flatMap((row) => {
      const { lat, lon } = row;
      if (
        lat === null ||
        lon === null ||
        !Number.isFinite(lat) ||
        !Number.isFinite(lon) ||
        lat < -90 ||
        lat > 90 ||
        lon < -180 ||
        lon > 180
      ) {
        return [];
      }

      return [
        {
          type: "Feature" as const,
          geometry: {
            type: "Point" as const,
            coordinates: [lon, lat],
          },
          properties: {
            age: readFiniteNumber(row.age),
            date: readRecordDate(row.date),
            dcKey: readText(row.dc_key),
            fatal: row.fatal,
            hasCourtCase: row.has_court_case,
            race: readText(row.race),
            sex: readText(row.sex),
            streetBlock: readStreetBlock(row),
            timeInMs: readFiniteNumber(row.timeInMs),
          },
        },
      ];
    }),
  };
}

export function summarizeShootingRecords(
  rows: ShootingRow[],
): ShootingRecordResult {
  const fatalRecordCount = rows.reduce(
    (count, row) => (row.fatal ? count + 1 : count),
    0,
  );

  return {
    fatalRecordCount,
    nonfatalRecordCount: rows.length - fatalRecordCount,
    points: rowsToShootingPoints(rows),
    recordCount: rows.length,
    rows,
  };
}

function readMeta(value: unknown): ShootingsMeta {
  if (!value || typeof value !== "object") {
    throw new Error("Invalid shooting metadata.");
  }
  const meta = value as Record<string, unknown>;
  if (
    !meta.years_meta ||
    typeof meta.years_meta !== "object"
  ) {
    throw new Error("Invalid shooting metadata.");
  }
  return meta as unknown as ShootingsMeta;
}

function readYearMeta(meta: ShootingsMeta, year: number): YearMeta {
  const value = meta.years_meta[String(year)] as unknown;
  if (!value || typeof value !== "object") {
    throw new Error(`Shooting records are not available for ${year}.`);
  }
  const yearMeta = value as Record<string, unknown>;
  if (
    typeof yearMeta.rows !== "number" ||
    !Number.isInteger(yearMeta.rows) ||
    yearMeta.rows < 0 ||
    typeof yearMeta.rows_url !== "string" ||
    !yearMeta.rows_url.startsWith("/")
  ) {
    throw new Error(`Invalid shooting metadata for ${year}.`);
  }
  return yearMeta as unknown as YearMeta;
}

function apiUrl(apiBaseUrl: string, path: string): string {
  const base = new URL(apiBaseUrl.endsWith("/") ? apiBaseUrl : `${apiBaseUrl}/`);
  const url = new URL(path.replace(/^\/+/, ""), base);
  if (url.origin !== base.origin) {
    throw new Error("Invalid shooting data URL.");
  }
  return url.toString();
}

export async function loadShootingRecords(
  apiBaseUrl: string,
  year: number | null,
  options: { fetcher?: Fetcher; signal?: AbortSignal } = {},
): Promise<ShootingRecordResult> {
  const fetcher = options.fetcher ?? globalThis.fetch.bind(globalThis);
  const request = async (url: string, accept: string) => {
    const response = await fetcher(url, {
      headers: { Accept: accept },
      signal: options.signal,
    });
    if (!response.ok) {
      throw new Error(`Shooting data request failed with ${response.status}.`);
    }
    return response;
  };

  const loadOnce = async (): Promise<ShootingRecordResult | null> => {
    const metaResponse = await request(
      apiUrl(apiBaseUrl, "/shootings/meta"),
      "application/json",
    );
    const meta = readMeta(await metaResponse.json());
    const years =
      year === null
        ? Object.keys(meta.years_meta)
            .map(Number)
            .filter(Number.isInteger)
            .sort((left, right) => right - left)
        : [year];
    if (years.length === 0) throw new Error("No shooting records are available.");

    const responses = await Promise.all(
      years.map(async (dataYear) => {
        const yearMeta = readYearMeta(meta, dataYear);
        const response = await fetcher(apiUrl(apiBaseUrl, yearMeta.rows_url), {
          headers: { Accept: "application/x-ndjson" },
          signal: options.signal,
        });
        return { dataYear, response, yearMeta };
      }),
    );

    // The API keeps only its current version. Refresh the manifest once if it
    // changed between the manifest and any versioned rows request.
    if (responses.some(({ response }) => response.status === 404)) return null;

    const rows: ShootingRow[] = [];
    for (const { dataYear, response, yearMeta } of responses) {
      if (!response.ok) {
        throw new Error(`Shooting data request failed with ${response.status}.`);
      }
      const yearRows = parseShootingRows(await response.text());
      if (yearRows.length !== yearMeta.rows) {
        throw new Error(`Incomplete shooting records for ${dataYear}.`);
      }
      rows.push(...yearRows);
    }
    return summarizeShootingRecords(rows);
  };

  const first = await loadOnce();
  if (first) return first;
  const second = await loadOnce();
  if (second) return second;
  throw new Error(
    `Shooting records changed while loading ${year ?? "all years"}.`,
  );
}
