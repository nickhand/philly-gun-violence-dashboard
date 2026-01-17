import type { Feature, FeatureCollection, Point } from "geojson";

export type RaceValues = "B" | "H" | "W" | "A" | "Other/Unknown";
export type SexValues = "M" | "F";
export type AgeGroupValues =
  | "18 to 30"
  | "Younger than 18"
  | "31 to 45"
  | "Older than 45"
  | "Unknown";

export interface ShootingVictimsPropertiesBase {
  dc_key: string;
  race: RaceValues;
  sex: SexValues;
  fatal: boolean;
  date: string;
  age_group: AgeGroupValues;
  has_court_case: boolean;
  age: number | null;
  street_name: string | null;
  block_number: number | null;
  zip_code: string | null;
  council_district: string | null;
  police_district: string | null;
  neighborhood: string | null;
  school_name: string | null;
  house_district: string | null;
  senate_district: string | null;
  segment_id: string | null;
}

export interface ShootingVictimsPropertiesDerived extends ShootingVictimsPropertiesBase {
  weekday: number | null;
  timeInMs: number | null;
  dateInMs: number | null;
  unique_id: number;
}

/**
 * Flattened row schema for Arquero tables.
 * Matches the NDJSON output from /shootings/rows endpoint.
 * Includes all properties plus lon/lat extracted from geometry.
 */
export interface ShootingRow extends ShootingVictimsPropertiesDerived {
  /** Longitude from geometry */
  lon: number | null;
  /** Latitude from geometry */
  lat: number | null;
  /** Year extracted from date (for filtering) */
  year: number | null;
}

export type ShootingVictimsGeoJsonApi = FeatureCollection<
  Point | null,
  ShootingVictimsPropertiesBase
>;

export type ShootingVictimsGeoJson = FeatureCollection<
  Point | null,
  ShootingVictimsPropertiesDerived
>;

export type ShootingVictimsFeature = Feature<
  Point | null,
  ShootingVictimsPropertiesDerived
>;
