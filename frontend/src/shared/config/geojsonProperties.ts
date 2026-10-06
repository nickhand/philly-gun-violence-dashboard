/**
 * Properties to include in GeoJSON features for map rendering.
 *
 * This is a subset of the full row data, including only the properties
 * needed for:
 * - Map layer styling (e.g., fatal for color)
 * - Tooltip display (e.g., date, age, race, sex)
 * - Feature identification (e.g., unique_id, dc_key)
 *
 * Using a subset reduces memory usage when converting rows to GeoJSON.
 *
 * @module geojsonProperties
 */

/**
 * Properties required for GeoJSON features.
 * Update this list if tooltip or layer styling needs change.
 */
export const GEOJSON_PROPERTIES = [
  // Identification
  "unique_id",
  "dc_key",

  // Styling (used by map layer paint expressions)
  "fatal",

  // Tooltip display
  "date",
  "dateInMs",
  "timeInMs",
  "block_number",
  "street_name",
  "age",
  "age_group",
  "race",
  "sex",
  "has_court_case",

  // Aggregation keys (used by overlay layers for choropleth grouping)
  "segment_id",
  "police_district",
  "council_district",
  "zip_code",
  "neighborhood",
  "house_district",
  "senate_district",
  "school_name",
] as const;

export type GeoJSONPropertyKey = (typeof GEOJSON_PROPERTIES)[number];
