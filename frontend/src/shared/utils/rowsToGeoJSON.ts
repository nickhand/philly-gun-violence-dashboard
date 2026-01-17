/**
 * Utility to convert shooting rows to GeoJSON FeatureCollection.
 *
 * This eliminates the need for a separate GeoJSON API endpoint by building
 * GeoJSON on the client from the rows data (which already has lon/lat).
 *
 * @module rowsToGeoJSON
 */

import type { ShootingRow } from "@/shared/types/shootings";
import { GEOJSON_PROPERTIES } from "@/shared/config/geojsonProperties";

/**
 * GeoJSON Point geometry.
 */
interface PointGeometry {
  type: "Point";
  coordinates: [number, number];
}

/**
 * GeoJSON Feature with Point geometry (non-null, for map rendering).
 */
export interface ShootingFeature {
  type: "Feature";
  geometry: PointGeometry;
  properties: Record<string, unknown>;
}

/**
 * GeoJSON FeatureCollection of shooting features.
 */
export interface ShootingFeatureCollection {
  type: "FeatureCollection";
  features: ShootingFeature[];
}

/**
 * Pick only the specified properties from a row.
 *
 * @param row - The source row with all properties
 * @param keys - The property keys to include
 * @returns Object with only the specified properties
 */
function pickProperties(
  row: ShootingRow,
  keys: readonly string[]
): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const key of keys) {
    if (key in row) {
      result[key] = row[key as keyof ShootingRow];
    }
  }
  return result;
}

/**
 * Convert a single row to a GeoJSON Feature.
 *
 * @param row - The shooting row data
 * @returns GeoJSON Feature with Point geometry, or null if coordinates missing
 */
export function rowToFeature(row: ShootingRow): ShootingFeature | null {
  const { lon, lat } = row;

  // Skip rows without valid coordinates
  if (lon == null || lat == null || isNaN(lon) || isNaN(lat)) {
    return null;
  }

  return {
    type: "Feature",
    geometry: { type: "Point", coordinates: [lon, lat] },
    properties: pickProperties(row, GEOJSON_PROPERTIES),
  };
}

/**
 * Convert an array of shooting rows to a GeoJSON FeatureCollection.
 *
 * This is used to build GeoJSON for map rendering from the row data
 * that was fetched for Arquero filtering. Only includes properties
 * needed for tooltip display and map styling.
 *
 * Rows without valid coordinates are filtered out.
 *
 * @param rows - Array of shooting row data
 * @returns GeoJSON FeatureCollection
 *
 * @example
 * ```ts
 * const rows = await fetchShootingsRows(yearMeta.rows_url);
 * const geojson = rowsToGeoJSON(rows);
 * map.getSource('shootings').setData(geojson);
 * ```
 */
export function rowsToGeoJSON(rows: ShootingRow[]): ShootingFeatureCollection {
  const features = rows
    .map(rowToFeature)
    .filter((f): f is ShootingFeature => f !== null);
  return {
    type: "FeatureCollection",
    features,
  };
}
