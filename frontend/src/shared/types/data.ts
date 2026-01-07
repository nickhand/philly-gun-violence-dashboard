import type { GeoJsonObject, Point } from "geojson";

export type UnionToIntersection<U> = (
  U extends any ? (k: U) => void : never
) extends (k: infer I) => void
  ? I
  : never;

export interface GenericFeature extends GeoJsonObject {
  type: "Feature";
  geometry: Point | null;
  id?: string | number | undefined;
  properties: { [name: string]: any };
}

export interface GenericFeatureCollection extends GeoJsonObject {
  type: "FeatureCollection";
  features: GenericFeature[];
}
