import type {
  Feature,
  FeatureCollection,
  GeoJsonProperties,
  Geometry,
} from "geojson";

import type { BoundaryMapLayerId } from "./mapLayers";
import type { ShootingRow } from "./shootingRecords";

export interface BoundaryOverlayConfig {
  column: keyof ShootingRow;
  dataset: string;
  geoid: string;
  id: BoundaryMapLayerId;
  label: string;
  legendUnit: string;
}

export const BOUNDARY_OVERLAYS: BoundaryOverlayConfig[] = [
  {
    id: "police-districts",
    label: "Police Districts",
    dataset: "police_districts",
    column: "police_district",
    geoid: "police_district",
    legendUnit: "police district",
  },
  {
    id: "council-districts",
    label: "Council Districts",
    dataset: "council_districts",
    column: "council_district",
    geoid: "council_district",
    legendUnit: "council district",
  },
  {
    id: "zip-codes",
    label: "ZIP Codes",
    dataset: "zip_codes",
    column: "zip_code",
    geoid: "zip_code",
    legendUnit: "ZIP code",
  },
  {
    id: "neighborhoods",
    label: "Neighborhoods",
    dataset: "neighborhoods",
    column: "neighborhood",
    geoid: "neighborhood",
    legendUnit: "neighborhood",
  },
  {
    id: "pa-house-districts",
    label: "PA House Districts",
    dataset: "pa_house_districts",
    column: "house_district",
    geoid: "house_district",
    legendUnit: "PA House district",
  },
  {
    id: "pa-senate-districts",
    label: "PA Senate Districts",
    dataset: "pa_senate_districts",
    column: "senate_district",
    geoid: "senate_district",
    legendUnit: "PA Senate district",
  },
  {
    id: "school-catchments",
    label: "School Catchments",
    dataset: "school_catchments",
    column: "school_name",
    geoid: "school_name",
    legendUnit: "school catchment",
  },
];

export const CITY_LIMITS_DATASET = "city_limits";

export type CountedFeatureProperties = NonNullable<GeoJsonProperties> & {
  fatal: number;
  nonfatal: number;
  total_shootings: number;
};

export interface CountedFeatureCollection extends FeatureCollection<
  Geometry,
  CountedFeatureProperties
> {
  maxCount: number;
  representedCount: number;
}

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;

function apiUrl(apiBaseUrl: string, path: string): string {
  const base = new URL(apiBaseUrl.endsWith("/") ? apiBaseUrl : `${apiBaseUrl}/`);
  const url = new URL(path.replace(/^\/+/, ""), base);
  if (url.origin !== base.origin) throw new Error("Invalid overlay data URL.");
  return url.toString();
}

function readFeatureCollection(value: unknown): FeatureCollection<Geometry> {
  if (!value || typeof value !== "object") {
    throw new Error("Invalid map overlay data.");
  }
  const collection = value as Record<string, unknown>;
  if (collection.type !== "FeatureCollection" || !Array.isArray(collection.features)) {
    throw new Error("Invalid map overlay data.");
  }
  return collection as unknown as FeatureCollection<Geometry>;
}

export function boundaryOverlayConfig(
  id: BoundaryMapLayerId,
): BoundaryOverlayConfig {
  const config = BOUNDARY_OVERLAYS.find((item) => item.id === id);
  if (!config) throw new Error(`Unknown boundary overlay: ${id}.`);
  return config;
}

export async function fetchOverlayFeatureCollection(
  apiBaseUrl: string,
  path: string,
  options: { fetcher?: Fetcher; signal?: AbortSignal } = {},
): Promise<FeatureCollection<Geometry>> {
  const fetcher = options.fetcher ?? globalThis.fetch.bind(globalThis);
  const response = await fetcher(apiUrl(apiBaseUrl, path), {
    headers: { Accept: "application/geo+json, application/json" },
    signal: options.signal,
  });
  if (!response.ok) {
    throw new Error(`Map overlay request failed with ${response.status}.`);
  }
  return readFeatureCollection(await response.json());
}

interface Counts {
  fatal: number;
  nonfatal: number;
  total: number;
}

function countRows(
  rows: ShootingRow[],
  column: keyof ShootingRow,
): Map<string, Counts> {
  const counts = new Map<string, Counts>();
  for (const row of rows) {
    const raw = row[column];
    if (raw === null || raw === undefined || raw === "") continue;
    const key = String(raw);
    const count = counts.get(key) ?? { fatal: 0, nonfatal: 0, total: 0 };
    count.total += 1;
    if (row.fatal) count.fatal += 1;
    else count.nonfatal += 1;
    counts.set(key, count);
  }
  return counts;
}

export function joinBoundaryCounts(
  collection: FeatureCollection<Geometry>,
  rows: ShootingRow[],
  config: BoundaryOverlayConfig,
): CountedFeatureCollection {
  const counts = countRows(rows, config.column);
  const representedKeys = new Set<string>();
  let maxCount = 0;
  const features = collection.features.map((feature) => {
    const properties = feature.properties ?? {};
    const key = String(properties[config.geoid] ?? "");
    const count = counts.get(key) ?? { fatal: 0, nonfatal: 0, total: 0 };
    if (counts.has(key)) representedKeys.add(key);
    maxCount = Math.max(maxCount, count.total);
    return {
      ...feature,
      properties: {
        ...properties,
        fatal: count.fatal,
        nonfatal: count.nonfatal,
        total_shootings: count.total,
      },
    } as Feature<Geometry, CountedFeatureProperties>;
  });
  const representedCount = [...representedKeys].reduce(
    (total, key) => total + (counts.get(key)?.total ?? 0),
    0,
  );
  return { type: "FeatureCollection", features, maxCount, representedCount };
}

export function joinStreetCounts(
  collection: FeatureCollection<Geometry>,
  rows: ShootingRow[],
): CountedFeatureCollection {
  const counts = countRows(rows, "segment_id");
  const representedKeys = new Set<string>();
  let maxCount = 0;
  const features = collection.features.map((feature) => {
    const properties = feature.properties ?? {};
    const key = String(properties.segment_id ?? "");
    const count = counts.get(key) ?? { fatal: 0, nonfatal: 0, total: 0 };
    if (counts.has(key)) representedKeys.add(key);
    maxCount = Math.max(maxCount, count.total);
    return {
      ...feature,
      properties: {
        ...properties,
        fatal: count.fatal,
        nonfatal: count.nonfatal,
        total_shootings: count.total,
      },
    } as Feature<Geometry, CountedFeatureProperties>;
  });
  const representedCount = [...representedKeys].reduce(
    (total, key) => total + (counts.get(key)?.total ?? 0),
    0,
  );
  return { type: "FeatureCollection", features, maxCount, representedCount };
}

export async function fetchStreetHotSpots(
  apiBaseUrl: string,
  rows: ShootingRow[],
  options: { fetcher?: Fetcher; signal?: AbortSignal } = {},
): Promise<CountedFeatureCollection> {
  const ids = [
    ...new Set(
      rows.flatMap((row) =>
        typeof row.segment_id === "string" && row.segment_id
          ? [row.segment_id]
          : [],
      ),
    ),
  ];
  if (ids.length === 0) {
    return {
      type: "FeatureCollection",
      features: [],
      maxCount: 0,
      representedCount: 0,
    };
  }

  const features: Feature<Geometry>[] = [];
  for (let index = 0; index < ids.length; index += 150) {
    const query = new URLSearchParams({
      limit: "2000",
      offset: "0",
      segment_ids: ids.slice(index, index + 150).join(","),
    });
    const page = await fetchOverlayFeatureCollection(
      apiBaseUrl,
      `/streets?${query}`,
      options,
    );
    features.push(...page.features);
  }

  return joinStreetCounts({ type: "FeatureCollection", features }, rows);
}
