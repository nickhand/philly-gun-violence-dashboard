import type { FeatureCollection, Geometry } from "geojson";

export type DataFeatureCollection = FeatureCollection<
  Geometry | null,
  { [name: string]: any }
>;

export interface SourceConfigBase {
  name: string;
  filterColumn?: string;
  formatter?: object;
}

export interface GeoJsonSourceConfig extends SourceConfigBase {
  data: DataFeatureCollection | null;
}

export interface BoundarySourceConfig extends SourceConfigBase {
  dataset: string;
  data?: FeatureCollection<Geometry | null, { [name: string]: any }> | null;
}

export type SourceConfig =
  | GeoJsonSourceConfig
  | BoundarySourceConfig;
