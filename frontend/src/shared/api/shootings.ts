import { getApiBaseUrl } from "@/shared/api/client";

/** Metadata response from /shootings/meta endpoint */
export interface ShootingsMeta {
  /** Content-based version hash */
  version: string;
  /** ISO timestamp when data was generated */
  generated_at: string;
  /** Total number of rows in dataset */
  rows: number;
  /** Available years in the dataset */
  years: number[];
  /** URL to fetch versioned NDJSON rows */
  rows_url: string;
  /** URL to fetch versioned GeoJSON */
  geojson_url: string;
}

/** Result of fetching meta with conditional request support */
export interface MetaFetchResult {
  /** Whether the data was modified (false = 304 Not Modified) */
  modified: boolean;
  /** Meta data (only present if modified) */
  meta?: ShootingsMeta;
}

/**
 * Fetches shootings metadata with conditional request support (ETag/304).
 *
 * @param lastKnownVersion - Optional last known version for If-None-Match header
 * @returns Promise resolving to meta fetch result
 * @throws Error if the API request fails
 *
 * @example
 * ```ts
 * // First fetch (no version known)
 * const result = await fetchShootingsMeta();
 * if (result.modified) {
 *   console.log(`Version: ${result.meta?.version}`);
 * }
 *
 * // Subsequent fetch with version check
 * const result2 = await fetchShootingsMeta(lastVersion);
 * if (!result2.modified) {
 *   console.log("Data unchanged, use cached version");
 * }
 * ```
 */
export async function fetchShootingsMeta(
  lastKnownVersion?: string | null
): Promise<MetaFetchResult> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/shootings/meta`;

  const headers: HeadersInit = {};
  if (lastKnownVersion) {
    headers["If-None-Match"] = `"${lastKnownVersion}"`;
  }

  const response = await fetch(url, { headers });

  // 304 Not Modified - data unchanged
  if (response.status === 304) {
    return { modified: false };
  }

  if (!response.ok) {
    throw new Error(
      `API request failed: ${response.status} ${response.statusText}`
    );
  }

  const meta = (await response.json()) as ShootingsMeta;
  return { modified: true, meta };
}

/**
 * Fetches shootings rows as NDJSON and parses to array of row objects.
 *
 * @param rowsUrl - Relative URL to the versioned NDJSON endpoint (from meta.rows_url)
 * @returns Promise resolving to array of row objects
 * @throws Error if the API request fails
 *
 * @example
 * ```ts
 * const rows = await fetchShootingsRows("/shootings/rows/abc123def456.ndjson");
 * console.log(`Loaded ${rows.length} rows`);
 * ```
 */
export async function fetchShootingsRows(
  rowsUrl: string
): Promise<Record<string, unknown>[]> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}${rowsUrl}`;

  const response = await fetch(url);

  if (!response.ok) {
    throw new Error(
      `API request failed: ${response.status} ${response.statusText}`
    );
  }

  // Parse NDJSON: one JSON object per line
  const text = await response.text();
  const lines = text.trim().split("\n");

  return lines
    .filter((line) => line.length > 0)
    .map((line) => JSON.parse(line) as Record<string, unknown>);
}
