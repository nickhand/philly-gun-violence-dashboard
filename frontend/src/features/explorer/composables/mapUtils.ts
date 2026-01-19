/**
 * Map utility functions.
 *
 * Pure helper functions for map operations - no state, easily testable.
 *
 * @module mapUtils
 */

/**
 * Convert layer name to MapLibre layer ID.
 * Uses the layer name with spaces replaced by hyphens, lowercase.
 *
 * @param name - Human-readable layer name (e.g., "ZIP Code")
 * @returns Layer ID for MapLibre (e.g., "zip-code")
 *
 * @example
 * ```typescript
 * layerNameToId("Police District"); // "police-district"
 * layerNameToId("ZIP Code"); // "zip-code"
 * ```
 */
export function layerNameToId(name: string): string {
  return name.toLowerCase().replace(/\s+/g, "-");
}

/**
 * Extract unique segment IDs from filtered features.
 * Used to fetch street blocks for the current filter state.
 *
 * @param features - Filtered shooting features
 * @returns Array of unique segment IDs
 *
 * @example
 * ```typescript
 * const features = [{ properties: { segment_id: "123" } }, ...];
 * const ids = getSegmentIdsFromFeatures(features); // ["123", ...]
 * ```
 */
export function getSegmentIdsFromFeatures(
  features: GeoJSON.Feature[]
): string[] {
  const segmentIds = new Set<string>();
  for (const feature of features) {
    const segmentId = feature.properties?.segment_id;
    if (segmentId) {
      segmentIds.add(String(segmentId));
    }
  }
  return Array.from(segmentIds);
}

/**
 * Create an empty GeoJSON FeatureCollection.
 *
 * @returns Empty FeatureCollection
 */
export function emptyFeatureCollection(): GeoJSON.FeatureCollection {
  return { type: "FeatureCollection", features: [] };
}
